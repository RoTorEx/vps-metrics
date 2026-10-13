import subprocess
from pathlib import Path
import tomllib
version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
tag = "v" + version
assert subprocess.check_output(["git", "branch", "--show-current"], text=True).strip() == "main", "Release push requires main"
assert not subprocess.check_output(["git", "status", "--porcelain"], text=True), "Release push requires a clean worktree"
assert subprocess.check_output(["git", "cat-file", "-t", tag], text=True).strip() == "tag", "Release requires an annotated tag"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True) == subprocess.check_output(["git", "rev-parse", tag + "^{}"], text=True), "Release tag must match HEAD"
subprocess.run(["git", "push", "origin", "main", "--follow-tags"], check=True)
