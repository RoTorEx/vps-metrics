"""Collect once, or read the latest sample and bounded history."""

from contextlib import closing
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import sys
import tomllib

from . import collect, storage


def version():
    return tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["version"]


def run_once(directory, disk, retention_days, max_samples, max_db_mib, proc_root="/proc"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A collector run is already active") from None
        database = directory / "metrics.db"
        previous = storage.previous(database) if database.exists() else None
        sample, counters = collect.snapshot(disk, previous, proc=Path(proc_root))
        sample["collector_version"] = version()
        storage.store(database, sample, counters, retention_days, max_samples, max_db_mib)
        storage.publish(directory / "snapshot.json", sample)
        return sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=version())
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("collect")
    command.add_argument("--data-dir", default="/srv/host-metrics/data")
    command.add_argument("--disk", default="/srv")
    command.add_argument("--proc-root", default="/proc", help="Read-only host counters mount for container collection.")
    command.add_argument("--retention-days", type=int, default=30)
    command.add_argument("--max-samples", type=int, default=86400)
    command.add_argument("--max-db-mib", type=int, default=256)
    for name in ("latest", "history", "check"):
        command = commands.add_parser(name)
        command.add_argument("--database", default="/srv/host-metrics/data/metrics.db")
        if name == "history":
            command.add_argument("--start", required=True)
            command.add_argument("--end", required=True)
            command.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    try:
        if args.command == "collect":
            os.umask(0o022)
            data = run_once(args.data_dir, args.disk, args.retention_days, args.max_samples, args.max_db_mib, args.proc_root)
            print(json.dumps({"captured_at": data["captured_at"], "service": "host-metrics", "version": version(), "revision": os.environ.get("SERVICE_REVISION", "unknown"), "collector_version": data["collector_version"], "history": "committed"}))
        elif args.command == "latest":
            print(json.dumps(storage.latest(args.database), allow_nan=False))
        elif args.command == "history":
            print(json.dumps(storage.history(args.database, args.start, args.end, args.limit), allow_nan=False))
        else:
            with closing(storage.read_connection(args.database)) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()[0]
                if result != "ok":
                    raise RuntimeError("Metrics database integrity check failed")
                print(json.dumps({"integrity": result, "samples": connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0]}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "service": "host-metrics", "version": version(), "revision": os.environ.get("SERVICE_REVISION", "unknown"), "event": "Metrics operation failed", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
