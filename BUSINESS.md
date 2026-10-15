# VPS Metrics

## Purpose and actors

A VPS owner needs truthful host metrics and bounded history without running a
monitoring stack. A systemd-scheduled, unprivileged Docker writer collects Linux counters;
a bot or another local consumer reads the committed SQLite database and JSON.
Administrators install service units and a restricted deployment endpoint.

## Flow and invariants

Read host counters, calculate deltas, commit one UTC sample, then atomically
publish the compatible JSON snapshot. A failed database write must never look
like a successful fresh collection. A single advisory lock serializes writers.
The reader opens an existing database in SQLite read-only/query-only mode.
Use DELETE journals, not WAL: consumers mount the whole data directory read-only
and need no writable WAL sidecars. Reads may briefly wait or fail while an
interrupted writer awaits recovery; the next writer performs recovery.

## Decision-bearing limits

- Collect every 30 seconds (systemd timer, one short-lived container per tick): enough resolution for a personal VPS
  with 2,880 expected samples/day, without a daemon or persistent processes.
- Keep 30 days and at most 86,400 samples: constrain history even with manual
  extra runs or clock changes. Expiration occurs on each successful collection.
- Cap the database at 256 MiB by default: prevent unbounded disk use. SQLite may
  also need a temporary rollback journal. Full-database failures preserve the
  previous commit and suppress JSON freshness. The cap is not a total directory
  quota. Deletes reuse pages; they do not shrink the file.
- Valid counter deltas require the same boot and a positive interval <=120
  seconds: avoid rate spikes after reboot, reset, or long pauses. Unknown
  network rates remain null. Interfaces are separate; summing bridges, tunnels,
  and physical interfaces double-counts traffic. These are host counters, not
  the provider's billing meter. Initial CPU uses a one-second measured window.
- History emits at most 500 buckets by default, configurable up to 2,000:
  protect consumers from huge results. Means use existing observations and
  gaps stay missing. Query intervals are timezone-aware and half-open [start,end).
- SQLite busy timeout is 2 seconds; collector container memory 64 MiB,
  CPU quota 20%, task limit 16; Docker scheduling service timeout 30 seconds
  and client memory 128 MiB: allow short collection bursts without exhausting
  the service deadline while bounding interference with the bot/VPN/CI. The
  former 5% cap throttled every observed CPU period and repeatedly timed out
  the 30-second Docker service on the production VPS. Large recovery exceeding
  these limits requires administrator investigation rather than weakening limits
  silently.
- Deployment accepts at most 5 MiB compressed/expanded and 128 regular files:
  release code is small; reject traversal, symlinks, duplicated names, and
  unexpected paths. Release versions are immutable, retrying identical bytes
  is safe. Retain prior releases for explicit rollback; administrators prune
  obsolete versions manually.

Storage, counter, disk-full, recovery and deployment tests protect these rules.
Change limits together with the CLI, service, documentation and relevant tests.

## Boundaries and ownership

This repository owns collection, persistence, read APIs, service units and release
artifacts. `personal-monitoring` owns the VPS setup guide and external heartbeat.
`assistant_bot` owns Telegram display and future history charts. No public port,
Docker socket, root collector, credentials, external alerts, dashboard, or UI
is part of the collector. Disk I/O and container status are deferred.

## Code map

`vps_metrics/collect.py`: Linux counters and rates. `storage.py`: transactions,
retention, atomic JSON and read APIs. `__main__.py`: CLI and writer lock.
`Dockerfile` and `compose.yaml`: checked runtime and narrow host-counter mounts.
`systemd/`: service isolation and schedule. `tools/`: checked release and deploy.

Docker collection reads host proc files explicitly via `--proc-root`; using
container-local network counters would falsely label a namespace as host scope.
The data mount is on the host root filesystem and supplies its disk counters.
The same 30-day SQLite history, writer identity and bot read-only mount survive
runtime migration. Docker updates are administrator operations; the native
restricted installer refuses to replace an installed Docker service silently.
No release, new deployment identity or public endpoint is implied by migration.
