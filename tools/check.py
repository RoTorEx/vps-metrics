"""Read-only syntax and whitespace checks, without third-party tooling."""
import ast
from pathlib import Path
import subprocess
for directory in ("host_metrics", "tests", "tools"):
    for path in Path(directory).glob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
subprocess.run(["sh", "-n", "tools/release.sh"], check=True)
subprocess.run(["git", "diff", "--check"], check=True)
