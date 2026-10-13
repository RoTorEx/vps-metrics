from contextlib import closing
import datetime as dt
import io
import json
import multiprocessing
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from vps_metrics import collect, storage
from vps_metrics.__main__ import run_once
from tools.install_release import unpack, deploy

BASE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def sample(second=0):
    return {'schema_version': 1, 'scope': 'host', 'captured_at': (BASE + dt.timedelta(seconds=second)).isoformat(), 'cpu_percent': float(second), 'network': {'eth0': {'rx_bytes_per_second': None if second == 0 else 10.0, 'tx_bytes_per_second': None if second == 0 else 20.0}}}


def interrupted_writer(path, ready):
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA cache_size=1')
    connection.execute('BEGIN IMMEDIATE')
    for index in range(200):
        connection.execute('INSERT INTO samples VALUES(?,?,?)', (index + 1, 'x' * 16384, '{}'))
    ready.set()
    import time
    time.sleep(60)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / 'metrics.db'

    def write(self, second, **options):
        storage.store(self.database, sample(second), {'boot_id': 'boot'}, **options)

    def test_latest_and_bounded_history(self):
        for second in (0, 1, 2, 30, 31):
            self.write(second)
        self.assertEqual(storage.latest(self.database)['cpu_percent'], 31)
        points = storage.history(self.database, BASE, BASE + dt.timedelta(seconds=60), 4)
        self.assertEqual([p['samples'] for p in points], [3, 2])
        self.assertEqual(points[0]['cpu_percent'], 1)
        self.assertEqual(points[0]['network']['eth0']['rx_bytes_per_second'], 10)
        self.assertEqual(len(points), 2)  # Empty buckets remain gaps.

    def test_retention_and_row_limit(self):
        for second in range(10):
            self.write(second, max_samples=3)
        with closing(storage.read_connection(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 3)
        self.write(2 * 86400, retention_days=1)
        self.assertEqual(len(storage.history(self.database, BASE, BASE + dt.timedelta(days=3))), 1)

    def test_read_connection_cannot_write_or_create(self):
        self.write(0)
        with closing(storage.read_connection(self.database)) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('DELETE FROM samples')
        with self.assertRaises(sqlite3.OperationalError):
            storage.latest(self.root / 'missing.db')
        self.assertFalse((self.root / 'missing.db').exists())

    def test_failed_insert_preserves_committed_sample(self):
        self.write(0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.write(0)
        self.assertEqual(storage.latest(self.database)['cpu_percent'], 0)

    def test_full_database_rolls_back(self):
        self.write(0)
        huge = sample(1)
        huge['extra'] = 'x' * (2 * 1024 * 1024)
        with self.assertRaises(sqlite3.DatabaseError):
            storage.store(self.database, huge, {}, max_db_mib=1)
        self.assertEqual(storage.latest(self.database)['cpu_percent'], 0)
        self.write(2, max_db_mib=1)
        self.assertEqual(storage.latest(self.database)['cpu_percent'], 2)

    def test_failed_history_never_publishes_fresh_json(self):
        target = self.root / 'snapshot.json'
        target.write_text('old')
        with patch('vps_metrics.collect.snapshot', return_value=(sample(), {})), patch('vps_metrics.storage.store', side_effect=sqlite3.OperationalError('full')):
            with self.assertRaises(sqlite3.OperationalError):
                run_once(self.root, '/', 30, 86400, 256)
        self.assertEqual(target.read_text(), 'old')

    def test_container_proc_mount_reaches_persisted_sample(self):
        proc = self.root / 'host-proc'
        values = {
            'stat': 'cpu 10 0 10 70 10 0 0 0',
            'meminfo': 'MemTotal: 100 kB\nMemAvailable: 40 kB\nSwapTotal: 20 kB\nSwapFree: 15 kB',
            'uptime': '1234.0 0.0',
            'sys/kernel/random/boot_id': 'host-boot',
            'net/dev': 'header\nheader\neth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0',
        }
        for name, text in values.items():
            target = proc / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        with patch('vps_metrics.collect.time.sleep', side_effect=lambda _: (proc / 'stat').write_text('cpu 30 0 30 130 10 0 0 0')):
            result = run_once(self.root, self.root, 30, 86400, 256, proc_root=proc)
        committed = storage.latest(self.database)
        self.assertEqual(committed['ram_total_bytes'], 100 * 1024)
        self.assertEqual(committed['uptime_seconds'], 1234.0)
        self.assertEqual(committed['network']['eth0']['tx_bytes'], 200)
        self.assertEqual(committed, result)
        self.assertEqual(storage.previous(self.database)['boot_id'], 'host-boot')

    def test_atomic_publish(self):
        storage.publish(self.root / 'snapshot.json', sample())
        self.assertEqual(json.loads((self.root / 'snapshot.json').read_text()), sample())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['snapshot.json'])

    def test_killed_writer_recovers_before_reading_previous(self):
        self.write(0)
        context = multiprocessing.get_context('spawn')
        ready = context.Event()
        process = context.Process(target=interrupted_writer, args=(self.database, ready))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
        finally:
            process.kill()
            process.join(10)
        self.assertEqual(storage.previous(self.database), {'boot_id': 'boot'})
        self.assertEqual(storage.latest(self.database)['cpu_percent'], 0)
        self.write(30)
        self.assertEqual(storage.latest(self.database)['cpu_percent'], 30)

    def test_unknown_schema_is_preserved(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):
            self.write(0)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 99)


class CounterTests(unittest.TestCase):
    def test_cpu_guest_is_not_counted_twice(self):
        self.assertEqual(collect.cpu_ticks('cpu 10 0 10 70 10 0 0 0 10 0'), (100, 80))
        self.assertEqual(collect.cpu_percent((100, 80), (200, 140)), 40)

    def test_network_reset_and_new_interface(self):
        rates = collect.network_rates({'eth0': {'rx_bytes': 160, 'tx_bytes': 10}, 'wg0': {'rx_bytes': 12, 'tx_bytes': 3}}, {'eth0': {'rx_bytes': 100, 'tx_bytes': 20}}, 30)
        self.assertEqual(rates['eth0']['rx_bytes_per_second'], 2)
        self.assertIsNone(rates['eth0']['tx_bytes_per_second'])
        self.assertIsNone(rates['wg0']['rx_bytes_per_second'])
        self.assertIsNone(collect.network_rates({'eth0': {'rx_bytes': 160, 'tx_bytes': 10}}, {}, None)['eth0']['rx_bytes_per_second'])

    def test_available_ram_and_swap(self):
        value = collect.memory_values('MemTotal: 100 kB\nMemAvailable: 40 kB\nSwapTotal: 20 kB\nSwapFree: 15 kB')
        self.assertEqual(value['ram_used_bytes'], 60 * 1024)
        self.assertEqual(value['swap_used_bytes'], 5 * 1024)


class DeploymentTests(unittest.TestCase):
    def test_native_deploy_cannot_replace_docker_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unit = root / 'collector.service'
            unit.write_text('ExecStart=/usr/bin/docker compose run metrics')
            with patch('tools.install_release.UNIT', unit), patch('tools.install_release.ROOT', root / 'releases'):
                with self.assertRaisesRegex(RuntimeError, 'Docker collection is installed'):
                    deploy(b'invalid archive')
            self.assertFalse((root / 'releases').exists())


    def test_traversal_and_links_are_rejected(self):
        for name, kind in (('../escape', tarfile.REGTYPE), ('vps_metrics/link', tarfile.SYMTYPE)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                member = tarfile.TarInfo(name)
                member.type = kind
                archive.addfile(member)
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError):
                    unpack(stream.getvalue(), Path(temporary))


if __name__ == '__main__':
    unittest.main()
