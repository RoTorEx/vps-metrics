# Changelog

## Unreleased

- Raise the Docker collector CPU cap to 20% of one core so routine samples complete within the 30-second service timeout.
- Add a checked multi-stage Docker collector, narrow host-counter mounts, preserved SQLite history and systemd scheduling; prevent native deployment from silently replacing Docker runtime.

## [Unreleased]

## [0.1.0] - 2026-10-13

- Collect Linux host CPU, memory, swap, filesystem, load, uptime and per-interface network counters every 30 seconds.
- Persist bounded UTC history in SQLite with read-only latest and aggregated interval APIs.
- Publish an atomic JSON snapshot only after a successful history commit.
- Recover interrupted transactions and handle full databases without reporting false freshness.
- Provide hardened systemd units, checked semantic releases, public CI, checked administrator deployment with rollback, and opt-in restricted SSH automation.
