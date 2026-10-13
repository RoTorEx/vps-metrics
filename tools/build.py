"""Build a bounded source release from tracked, public project files."""
import hashlib
from pathlib import Path
import subprocess
import tarfile
import tomllib
version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
output = Path("dist")
output.mkdir(exist_ok=True)
artifact = output / f"vps-metrics-v{version}.tar.gz"
files = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
with tarfile.open(artifact, "w:gz") as archive:
    for name in sorted(filter(None, files)):
        if name.startswith(("vps_metrics/", "systemd/", "docs/")) or name in ("pyproject.toml", "README.md", "BUSINESS.md", "CHANGELOG.md", "Dockerfile", "compose.yaml", ".dockerignore"):
            path = Path(name)
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"Unexpected release member: {name}")
            archive.add(path, arcname=name, recursive=False)
checksum = artifact.with_suffix(artifact.suffix + ".sha256")
checksum.write_text(hashlib.sha256(artifact.read_bytes()).hexdigest() + "  " + artifact.name + "\n")
print(artifact)
