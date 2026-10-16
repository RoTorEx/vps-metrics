# Manual setup and deployment

Complete the VPS baseline first. Use an administrator with sudo and verify the
server's SSH host key. Python 3.11+ and systemd are required. No new port opens.

## Docker installation and updates (current VPS runtime)

Use the existing administrator SSH and production Docker. Preserve the
`vps-monitor` identity and `/srv/host-metrics/data`; do not recreate the database.
Clone this public source into `/srv/host-metrics` as root. Before
migration, create an online SQLite backup and a verified off-host recovery copy.

```sh
cd /srv/host-metrics
make docker-build
install -d -m 700 /srv/host-metrics/config
printf 'METRICS_UID=%s\nMETRICS_GID=%s\n' "$(id -u vps-monitor)" "$(id -g vps-monitor)" > /srv/host-metrics/config/collector.env
chmod 600 /srv/host-metrics/config/collector.env
docker compose --env-file /srv/host-metrics/config/collector.env config --quiet
# Preserve the previous native unit for explicit rollback.
cp /etc/systemd/system/host-metrics.service /srv/host-metrics/config/metrics-native.service
systemctl stop host-metrics.timer host-metrics.service
install -m 644 systemd/host-metrics-docker.service /etc/systemd/system/host-metrics.service
systemctl daemon-reload
systemctl start host-metrics.service
systemctl enable --now host-metrics.timer
```

The systemd timer creates one short-lived container every 30 seconds and removes
it after collection. It restarts scheduling after boot; there is no extra
permanent Python daemon. `network_mode: none`, capability drop, read-only root,
64 MiB app memory, 0.2 CPU and 16 tasks bound the collector. The host service
runs the Docker client as administrator, with a 128 MiB client limit and only
AF_UNIX access; application code runs as the unchanged vps-monitor UID/GID.
The container has no Docker socket, host network, privileged mode or host PID
namespace. Only the required proc files are read-only mounts; `/proc/1/net/dev`
provides host network counters even though the container has no network.
The `/data` mount provides truthful host-filesystem statvfs values.

Verify at least two newer SQLite rows, database quick_check, JSON scope/boot ID,
RAM/disk totals against the host, eth0 counters, the bot's read-only snapshot
and a successful independent heartbeat. Test an idle timer stop/start and confirm
Docker and the timer are enabled at boot. Preserve prior history throughout.

For updates, stop the timer, pull the verified source, run checks/build and
start collection again. Verify freshness before resuming the timer; keep the
previous image until verification succeeds. The native restricted deployment
endpoint refuses Docker installations instead of silently reverting them.
Automatic native deployment must remain disabled for this runtime. Docker
updates currently use administrator access, without new credentials or releases.
For native rollback, stop the timer, restore `config/metrics-native.service` to
its original unit path, daemon-reload, start the service and resume the timer.
The native v0.1.0 source and current symlink are retained for this recovery path.

## Native installation (optional alternative)

## 1. Identity and directories

```sh
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin vps-monitor
sudo install -d -o root -g root -m 755 /srv/host-metrics
sudo install -d -o vps-monitor -g vps-monitor -m 755 /srv/host-metrics/data
sudo install -d -o root -g root -m 700 /srv/host-metrics/config
```

Skip user creation if the identity already exists. Keep code root-owned and data
writable only by vps-monitor. Consumers require directory traversal and file read
permission; the data is local host metrics, not secrets.

## 2. Install the administrator-owned deployment endpoint

Clone this public repository on your admin machine, inspect the installer and
service, and transfer these three files to the VPS using your verified admin SSH.
Then install them from the transferred directory:

```sh
sudo install -D -m 755 tools/install_release.py /usr/local/libexec/host-metrics-install.py
sudo install -D -m 644 systemd/host-metrics.service /usr/local/share/host-metrics/host-metrics.service
sudo install -m 644 systemd/host-metrics.service /etc/systemd/system/host-metrics.service
sudo install -m 644 systemd/host-metrics.timer /etc/systemd/system/host-metrics.timer
```

Create `/usr/local/sbin/deploy-host-metrics`, root-owned mode 755:

```sh
#!/bin/sh
exec /usr/bin/python3 -I /usr/local/libexec/host-metrics-install.py
```

`-I` ignores caller Python paths and environment. This endpoint accepts only an
archive on stdin, no arguments. It extracts validated regular files into a
root-owned immutable release directory and runs new code only through the
unprivileged service. Service definitions supplied by an artifact are never
installed as root. Installer/service changes need an explicit administrator
installation using this stage.

## 3. Existing administrator access or optional restricted identity

The first deployment can reuse existing administrator SSH, without creating
users, adding sudo rules, or putting a private key in GitHub. Build/download the
checksummed release, then use:

```sh
python3 tools/deploy.py --admin --host VPS_HOST --user ADMIN_USER \
  --key EXISTING_ADMIN_KEY --known-hosts VERIFIED_KNOWN_HOSTS
```

The administrator installs the endpoint and canonical service from Stage 2.
For optional automated deployment, explicitly authorize the new access boundary
before following the remaining instructions in this stage.

### Optional restricted deployment identity

```sh
sudo useradd --create-home --shell /bin/sh metrics-deploy
sudo install -d -o metrics-deploy -g metrics-deploy -m 700 /home/metrics-deploy/.ssh
```

Generate a dedicated Ed25519 key on the admin machine. Add ONLY its public key
to `authorized_keys`, prefixed with:

```text
restrict,command="sudo -n /usr/local/sbin/deploy-host-metrics" ssh-ed25519 PUBLIC_KEY
```

Set authorized_keys mode 600 and ownership metrics-deploy. Add a root-owned
mode-440 `/etc/sudoers.d/metrics-deploy` containing:

```text
metrics-deploy ALL=(root) NOPASSWD: /usr/local/sbin/deploy-host-metrics ""
```

Validate with `sudo visudo -cf /etc/sudoers.d/metrics-deploy`. This user needs no
Docker, interactive sudo, port forwarding, password authentication or other key.
Use a pinned known_hosts entry obtained through an already trusted admin session.

## 4. First deployment and automation

For optional automatic deployment, configure secrets `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_PRIVATE_KEY`, and `DEPLOY_KNOWN_HOSTS`. The last contains the pinned
host-key line. Do not commit private credentials or personal server addresses.

Before the first tag, push committed main and run the manual `Release` workflow;
it checks Linux targets and uploads the same artifact without publishing or
deploying. Then run `make release`, enter the version, and `make release-push`.
Only version tags publish. Automatic deployment requires setting repository variable
`METRICS_AUTO_DEPLOY=true` after its restricted access is configured. Verify the GitHub Release assets and deployment
job, not just the local tag. First-time installation must enable the timer:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now host-metrics.timer
sudo systemctl start host-metrics.service
sudo journalctl -u host-metrics.service -n 20 --no-pager
cd /srv/host-metrics/current
python3 -m host_metrics check
python3 -m host_metrics latest
```

For an explicit manual deployment of a built checksummed archive, set
`DEPLOY_HOST`, `DEPLOY_KEY` and `DEPLOY_KNOWN_HOSTS_FILE`, then `make deploy`.
An enabled automatic tag workflow does this with repository secrets.
Verify repeated timer samples, database integrity, read-only consumer access,
and boot persistence. The collector has no IP access; the external heartbeat
remains a separate service in host-health.

## 5. Backup and rollback

Use SQLite's online backup API under the writer identity or administrator,
check the resulting `PRAGMA quick_check`, then archive that snapshot. Preserve
code, current symlink, units, administrator-owned installer and private deploy
configuration in protected recovery backups. Runtime journals/locks and rebuilt
JSON do not need raw file copies. Keep a verified off-host copy; local-only
archives do not survive host loss.

A failed deployment automatically restores the prior unit/source and restarts
collection. A database schema upgrade is a separate migration; v0.1.0 only creates
schema 1 and refuses unknown schemas. For manual rollback, send a verified older
release archive through the same installer; confirm its reader supports the
current schema. Historical JSON-only snapshots cannot reconstruct earlier history.
Old version directories remain available for rollback; prune only versions you
no longer need. To remove collection, stop/disable its timer and service, remove
the bot mount separately, and preserve data/backups until intentionally retired.
