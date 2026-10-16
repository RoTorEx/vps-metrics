# Reader contract

Schema version 1 uses a `samples` table with `captured_at_us` (UTC Unix
microseconds, primary key), `sample_json` and private `counters_json` columns.
`PRAGMA user_version` is 1. Consumers read `sample_json`; internal counters are
for the writer's boot-aware deltas, not a consumer API.

```python
from host_metrics.storage import latest, history
snapshot = latest('/run/host-metrics/metrics.db')
points = history('/run/host-metrics/metrics.db',
                 '2026-10-13T00:00:00Z', '2026-10-14T00:00:00Z', limit=500)
```

Alternatively use standard-library SQLite directly in a bot without installing
this project. Open `file:/run/host-metrics/metrics.db?mode=ro` with `uri=True`, set
`PRAGMA query_only=ON`, verify user_version, and select latest `sample_json` by
`captured_at_us DESC LIMIT 1`. Close the connection after each short query;
a SQLite connection context manager does not close it. Never open with
`immutable=1` or copy a live database with ordinary file copy.

Snapshot fields include aware UTC `captured_at`, `schema_version=1`, `scope=host`,
`collector_version`, CPU percentage and sampling window, RAM total/available/used
bytes, swap total/used bytes, filesystem total/used/free/available bytes,
load_1m/5m/15m and uptime_seconds. `network` contains each non-loopback interface
with rx_bytes/tx_bytes and nullable rx_bytes_per_second/tx_bytes_per_second.
Network counters describe the host, not billable provider traffic. Boot changes,
interface resets and intervals beyond 120 seconds yield unknown rates.

History requires timezone-aware bounds and uses [start,end), indexed by time.
Numeric host values are averaged within evenly sized buckets; each point includes
its UTC bucket start and observed sample count. Network rates average known
values only. Missing buckets are omitted; never draw a false zero through a gap.
The returned result is bounded to the requested number of buckets (max 2,000).
Raw interface byte totals are available in latest/raw rows, not averaged history.

Missing databases, incompatible schema, corruption or busy timeouts are errors;
consumers should show unavailable/stale data and permit retry, not fabricate zero.
A fresh JSON only proves a committed collector run, not every application alive.
Telegram history UI is a separate consumer feature.
