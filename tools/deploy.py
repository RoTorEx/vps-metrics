"""Send a release archive to the restricted SSH installer."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tomllib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifact')
parser.add_argument('--host', default=os.environ.get('DEPLOY_HOST'))
parser.add_argument('--user', default=os.environ.get('DEPLOY_USER', 'metrics-deploy'))
parser.add_argument('--key', default=os.environ.get('DEPLOY_KEY'))
parser.add_argument('--known-hosts', default=os.environ.get('DEPLOY_KNOWN_HOSTS_FILE'))
args = parser.parse_args()
version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
artifact = Path(args.artifact or f'dist/vps-metrics-v{version}.tar.gz')
expected = artifact.with_suffix(artifact.suffix + '.sha256').read_text().split()[0]
if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
    raise SystemExit('Artifact checksum mismatch')
if not args.host or not args.key or not args.known_hosts:
    raise SystemExit('Set DEPLOY_HOST, DEPLOY_KEY, and DEPLOY_KNOWN_HOSTS_FILE')
with artifact.open('rb') as payload:
    subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + args.known_hosts, '-i', args.key, args.user + '@' + args.host], stdin=payload, check=True, timeout=90)
