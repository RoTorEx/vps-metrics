"""SQLite owns history; JSON is published only after a committed sample."""

from contextlib import closing
import datetime as dt
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

SCHEMA_VERSION = 1
UTC = dt.timezone.utc


def timestamp_us(value):
    value = dt.datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required")
    return int(value.timestamp() * 1_000_000)


def read_connection(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        connection.close()
        raise ValueError("Unsupported metrics database schema")
    return connection


def latest(path, include_counters=False):
    with closing(read_connection(path)) as connection:
        row = connection.execute("SELECT sample_json,counters_json FROM samples ORDER BY captured_at_us DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return (json.loads(row[0]), json.loads(row[1])) if include_counters else json.loads(row[0])


def previous(path):
    """The writer recovers an interrupted rollback journal before reading counters."""
    with closing(sqlite3.connect(path, timeout=2)) as connection:
        schema = connection.execute("PRAGMA user_version").fetchone()[0]
        if schema == 0 and not connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
            return None
        if schema != SCHEMA_VERSION:
            raise ValueError("Unsupported metrics database schema")
        row = connection.execute("SELECT counters_json FROM samples ORDER BY captured_at_us DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None


def publish(path, sample):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(sample, handle, allow_nan=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def store(path, sample, counters, retention_days=30, max_samples=86400, max_db_mib=256):
    if not 1 <= retention_days <= 365 or not 1 <= max_samples <= 1_000_000 or not 1 <= max_db_mib <= 1024:
        raise ValueError("Invalid history limits")
    sample_json = json.dumps(sample, allow_nan=False, separators=(",", ":"))
    counters_json = json.dumps(counters, allow_nan=False, separators=(",", ":"))
    captured = timestamp_us(sample["captured_at"])
    cutoff = captured - retention_days * 86400 * 1_000_000
    path = Path(path)
    with closing(sqlite3.connect(path, timeout=2)) as connection, connection:
        schema = connection.execute("PRAGMA user_version").fetchone()[0]
        if schema not in (0, SCHEMA_VERSION):
            raise ValueError("Unsupported metrics database schema")
        if schema == 0 and connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
            raise ValueError("Refusing an unrecognized existing database")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={max_db_mib * 1024 * 1024 // page_size}")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE IF NOT EXISTS samples (captured_at_us INTEGER PRIMARY KEY, sample_json TEXT NOT NULL, counters_json TEXT NOT NULL)")
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.execute("DELETE FROM samples WHERE captured_at_us < ?", (cutoff,))
        connection.execute("INSERT INTO samples VALUES(?,?,?)", (captured, sample_json, counters_json))
        connection.execute("DELETE FROM samples WHERE captured_at_us < (SELECT captured_at_us FROM samples ORDER BY captured_at_us DESC LIMIT 1 OFFSET ?)", (max_samples - 1,))
    path.chmod(0o644)


def history(path, start, end, limit=500):
    """Return bounded time buckets; preserve gaps and first-sample unknown rates."""
    start, end = timestamp_us(start), timestamp_us(end)
    if end <= start or not 1 <= limit <= 2000:
        raise ValueError("Invalid history interval or point limit")
    width = max(1, math.ceil((end - start) / limit))
    result = []
    bucket_id = None
    aggregate = None

    def finish():
        if aggregate is None:
            return
        point = {"captured_at": dt.datetime.fromtimestamp((start + bucket_id * width) / 1_000_000, UTC).isoformat(), "samples": aggregate["count"]}
        point.update({key: total / count for key, (total, count) in aggregate["values"].items()})
        point["network"] = {name: {key: total / count for key, (total, count) in values.items()} for name, values in aggregate["network"].items()}
        result.append(point)

    with closing(read_connection(path)) as connection:
        rows = connection.execute("SELECT captured_at_us,sample_json FROM samples WHERE captured_at_us >= ? AND captured_at_us < ? ORDER BY captured_at_us", (start, end))
        for captured, payload in rows:
            current = (captured - start) // width
            if current != bucket_id:
                finish()
                bucket_id = current
                aggregate = {"count": 0, "values": {}, "network": {}}
            sample = json.loads(payload)
            aggregate["count"] += 1
            for key, value in sample.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) and key != "schema_version":
                    total, count = aggregate["values"].get(key, (0, 0))
                    aggregate["values"][key] = (total + value, count + 1)
            for name, values in sample.get("network", {}).items():
                means = aggregate["network"].setdefault(name, {})
                for key in ("rx_bytes_per_second", "tx_bytes_per_second"):
                    value = values[key]
                    if value is not None:
                        total, count = means.get(key, (0, 0))
                        means[key] = (total + value, count + 1)
        finish()
    return result
