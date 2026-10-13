# Manual setup and deployment

Complete the VPS baseline first. Use an administrator with sudo and verify the
server's SSH host key. Python 3.11+ and systemd are required. No new port opens.

## 1. Identity and directories

```sh
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin vps-monitor
sudo install -d -o root -g root -m 755 /srv/monitoring /srv/monitoring/collector
sudo install -d -o vps-monitor -g vps-monitor -m 755 /srv/monitoring/data
sudo install -d -o root -g root -m 700 /srv/monitoring/config
```

Skip user creation if the identity already exists. Keep code root-owned and data
writable only by vps-monitor. Consumers require directory traversal and file read
permission; the data is local host metrics, not secrets.

## 2. Install the administrator-owned deployment endpoint

Clone this public repository on your admin machine, inspect the installer and
service, and transfer these three files to the VPS using your verified admin SSH.
Then install them from the transferred directory:

```sh
sudo install -D -m 755 tools/install_release.py /usr/local/libexec/vps-metrics-install.py
sudo install -D -m 644 systemd/personal-vps-metrics.service /usr/local/share/vps-metrics/personal-vps-metrics.service
sudo install -m 644 systemd/personal-vps-metrics.service /etc/systemd/system/personal-vps-metrics.service
sudo install -m 644 systemd/personal-vps-metrics.timer /etc/systemd/system/personal-vps-metrics.timer
```

Create `/usr/local/sbin/deploy-vps-metrics`, root-owned mode 755:

```sh
#!/bin/sh
exec /usr/bin/python3 -I /usr/local/libexec/vps-metrics-install.py
```

`-I` ignores caller Python paths and environment. This endpoint accepts only an
archive on stdin, no arguments. It extracts validated regular files into a
root-owned immutable release directory and runs new code only through the
unprivileged service. Service definitions supplied by an artifact are never
installed as root. Installer/service changes need an explicit administrator
installation using this stage.

## 3. Restricted deployment identity

```sh
sudo useradd --create-home --shell /bin/sh metrics-deploy
sudo install -d -o metrics-deploy -g metrics-deploy -m 700 /home/metrics-deploy/.ssh
```

Generate a dedicated Ed25519 key on the admin machine. Add ONLY its public key
to `authorized_keys`, prefixed with:

```text
restrict,command="sudo -n /usr/local/sbin/deploy-vps-metrics" ssh-ed25519 PUBLIC_KEY
```

Set authorized_keys mode 600 and ownership metrics-deploy. Add a root-owned
mode-440 `/etc/sudoers.d/metrics-deploy` containing:

```text
metrics-deploy ALL=(root) NOPASSWD: /usr/local/sbin/deploy-vps-metrics ""
```

Validate with `sudo visudo -cf /etc/sudoers.d/metrics-deploy`. This user needs no
Docker, interactive sudo, port forwarding, password authentication or other key.
Use a pinned known_hosts entry obtained through an already trusted admin session.

## 4. First deployment and automation

In this GitHub repository, configure secrets `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_PRIVATE_KEY`, and `DEPLOY_KNOWN_HOSTS`. The last contains the pinned
host-key line. Do not commit private credentials or personal server addresses.

Before the first tag, push committed main and run the manual `Release` workflow;
it checks Linux targets and uploads the same artifact without publishing or
deploying. Then run `make release`, enter the version, and `make release-push`.
Only version tags publish/deploy. Verify the GitHub Release assets and deployment
job, not just the local tag. First-time installation must enable the timer:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now personal-vps-metrics.timer
sudo systemctl start personal-vps-metrics.service
sudo journalctl -u personal-vps-metrics.service -n 20 --no-pager
cd /srv/monitoring/collector/current
python3 -m vps_metrics check
python3 -m vps_metrics latest
```

For an explicit manual deployment of a built checksummed archive, set
`DEPLOY_HOST`, `DEPLOY_KEY` and `DEPLOY_KNOWN_HOSTS_FILE`, then `make deploy`.
The normal tag workflow does this automatically with repository secrets.
Verify repeated timer samples, database integrity, read-only consumer access,
and boot persistence. The collector has no IP access; the external heartbeat
remains a separate service in personal-monitoring.

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
