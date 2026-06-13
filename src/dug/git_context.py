import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Commit:
    hash: str
    message: str
    timestamp: datetime
    files_touched: list[str] = field(default_factory=list)

    @property
    def days_ago(self) -> int:
        delta = datetime.now(timezone.utc) - self.timestamp.astimezone(timezone.utc)
        return delta.days


def get_git_history(root: Path, depth: int = 50) -> list[Commit]:
    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--format=%H|%s|%aI", f"-n{depth}"],
            capture_output=True,
            text=True,
            cwd=root,
        )
    except FileNotFoundError:
        return []

    if result.returncode != 0:
        return []

    commits: list[Commit] = []
    current: Commit | None = None

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line and len(line.split("|")) >= 3:
            parts = line.split("|", 2)
            try:
                ts = datetime.fromisoformat(parts[2])
            except ValueError:
                ts = datetime.now(timezone.utc)
            if current:
                commits.append(current)
            current = Commit(hash=parts[0], message=parts[1], timestamp=ts)
        elif current is not None:
            current.files_touched.append(line)

    if current:
        commits.append(current)

    return commits
