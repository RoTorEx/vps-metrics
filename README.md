# VPS Metrics

Dependency-free Linux host metrics collector: Docker + systemd + SQLite, with a compatible
atomic JSON snapshot for an existing bot. Python 3.11+; the collector has no Docker socket,
privileged collector, public listener, or monitoring daemon.

## Layout

```text
/srv/monitoring/
  collector/
    docker/               # Administrator-owned Docker source checkout
    releases/v0.1.0/       # Immutable application source
    current -> releases/v0.1.0
  config/                 # Private configuration owned by the setup repository
  data/                   # metrics.db, snapshot.json, writer lock
  logs/                   # Optional exports; systemd uses journald
```

Keep runtime data outside Git. Mount the whole `data/` directory read-only into
consumers: atomic JSON replacements stay visible, and SQLite DELETE journaling
needs no writable WAL directory. Do not use SQLite `immutable=1` on this live DB.

## Commands

```sh
make check
make build
python3 -m vps_metrics --version
python3 -m vps_metrics collect --data-dir ./data --disk /
python3 -m vps_metrics latest --database ./data/metrics.db
python3 -m vps_metrics history --database ./data/metrics.db \
  --start 2026-10-13T00:00:00Z --end 2026-10-14T00:00:00Z --limit 500
python3 -m vps_metrics check --database ./data/metrics.db
```

Collection runs on Linux. Storage and release tests also run on macOS. The
Makefile uses Homebrew Python 3.13 when available on macOS; override `PYTHON`
when needed. Standard-library-only runtime and tests require no dependency install.
Docker collection uses the same SQLite/JSON writer, scheduled every 30 seconds
by systemd. Its multi-stage image runs tests before copying only runtime source.
The container has no network or capabilities, writes only data, and reads five
individual host proc counters. It does not mount the host root or all of /proc.
The original native service remains available for explicit rollback.

See [reader contract](docs/READER.md), [manual setup and deployment](docs/DEPLOYMENT.md),
and [business rules](BUSINESS.md).

## Release

Follow the same interactive workflow as the related infrastructure repositories:

```sh
make release
# Enter MAJOR.MINOR.PATCH when prompted.
make release-push
```

The first command verifies the clean main branch, runs checks, updates the
native version/changelog, commits and creates an annotated tag. The second
pushes main and its release tag. GitHub Actions builds a checksummed source
archive, publishes a GitHub Release. Deployment uses the checked SSH installer;
automatic deployment is opt-in through the METRICS_AUTO_DEPLOY repository variable. A failed deploy restores the prior service/source and resumes the
timer. Source versions remain immutable; the runtime data directory is retained.
Public pull requests use GitHub-hosted runners and have no deployment secrets.
The manual `Release` workflow validates build/upload without publishing or deploying.

## Kernel maintenance

This project commits local copies of Vibecoding Kernel rules. Configure the
local source once, then refresh the managed rules and routing:

```sh
make vibe-kernel-set KERNEL=/absolute/path/to/vibecoding-kernel
make vibe-pull
```

`make vibe-kernel-path` shows the configured source. The machine-specific
`.vibe/KERNEL_SOURCE` is ignored by Git. `make vibe-propose` submits an
interactive, reviewable proposal to that source; it changes no shared rule.

## Runtime log identity

Collection records and error diagnostics include service/version/revision. Native
version comes from pyproject.toml; `make docker-build` bakes the source commit.
The host timer captures output in `journalctl -u personal-vps-metrics.service`;
API/CLI data responses and stored measurement schemas remain unchanged.
