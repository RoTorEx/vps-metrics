"""Root-owned forced-command installer; application code runs only as vps-monitor."""
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib

ROOT = Path('/srv/host-metrics')
SERVICE = 'host-metrics.service'
TIMER = 'host-metrics.timer'
UNIT = Path('/etc/systemd/system') / SERVICE


def command(*args):
    subprocess.run(args, check=True, timeout=30)


def unpack(payload, destination):
    if len(payload) > 5 * 1024 * 1024:
        raise ValueError('Release exceeds 5 MiB')
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        members = archive.getmembers()
        if len(members) > 128 or sum(m.size for m in members) > 5 * 1024 * 1024:
            raise ValueError('Release has too many files or excessive expanded size')
        names = set()
        for member in members:
            parts = Path(member.name).parts
            if (not member.isfile() or member.name.startswith('/') or '..' in parts
                or member.name in names or not parts
                or not (parts[0] in ('host_metrics', 'systemd', 'docs') or member.name in ('pyproject.toml', 'README.md', 'BUSINESS.md', 'CHANGELOG.md', 'Dockerfile', 'compose.yaml', '.dockerignore'))):
                raise ValueError('Unsafe release member')
            names.add(member.name)
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)
    metadata = tomllib.loads((destination / 'pyproject.toml').read_text())['project']
    if metadata['name'] != 'host-metrics' or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', metadata['version']):
        raise ValueError('Invalid release identity')
    for name in ('__init__.py', '__main__.py', 'collect.py', 'storage.py'):
        if not (destination / 'host_metrics' / name).is_file():
            raise ValueError('Incomplete release')
    return metadata['version']


def deploy(payload):
    if UNIT.exists() and 'docker compose' in UNIT.read_text():
        raise RuntimeError('Docker collection is installed; use the administrator Docker deployment procedure.')
    ROOT.mkdir(parents=True, exist_ok=True)
    releases = ROOT / 'releases'
    releases.mkdir(exist_ok=True)
    with (ROOT / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(dir=releases, prefix='.incoming-') as temporary:
            staging = Path(temporary)
            version = unpack(payload, staging)
            final = releases / ('v' + version)
            if final.exists():
                expected = {str(p.relative_to(staging)): p.read_bytes() for p in staging.rglob('*') if p.is_file()}
                actual = {str(p.relative_to(final)): p.read_bytes() for p in final.rglob('*') if p.is_file()}
                if expected != actual:
                    raise ValueError('Refusing to replace an existing version with different content')
            else:
                shutil.copytree(staging, final)
                final.chmod(0o755)
        current = ROOT / 'current'
        previous = os.readlink(current) if current.is_symlink() else None
        previous_unit = UNIT.read_bytes()
        started = time.time()
        command('systemctl', 'stop', TIMER, SERVICE)
        try:
            switch = ROOT / '.next'
            switch.unlink(missing_ok=True)
            switch.symlink_to(final.relative_to(ROOT))
            switch.replace(current)
            # The administrator installs this canonical unit once. Never install
            # a unit or execute a script supplied by the SSH deployment caller as root.
            shutil.copyfile('/usr/local/share/host-metrics/host-metrics.service', UNIT)
            command('systemctl', 'daemon-reload')
            command('systemctl', 'start', SERVICE)
            sample = json.loads(Path('/srv/host-metrics/data/snapshot.json').read_text())
            from datetime import datetime
            if sample['collector_version'] != version or datetime.fromisoformat(sample['captured_at']).timestamp() < started:
                raise RuntimeError('Fresh committed sample verification failed')
        except BaseException:
            if previous is not None:
                switch = ROOT / '.rollback'
                switch.unlink(missing_ok=True)
                switch.symlink_to(previous)
                switch.replace(current)
            else:
                current.unlink(missing_ok=True)
            UNIT.write_bytes(previous_unit)
            command('systemctl', 'daemon-reload')
            command('systemctl', 'start', SERVICE)
            raise
        finally:
            command('systemctl', 'start', TIMER)
        print(json.dumps({'deployed': version, 'captured_at': sample['captured_at']}))


if __name__ == '__main__':
    os.umask(0o022)
    if os.geteuid() != 0 or len(sys.argv) != 1:
        sys.exit('Installer requires root and accepts no arguments')
    deploy(sys.stdin.buffer.read(5 * 1024 * 1024 + 1))
