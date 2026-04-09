from __future__ import annotations

import subprocess
from pathlib import Path


class GitSnapshotRepository:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = Path(repo_dir)
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_repo()

    def _run(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=self.repo_dir, check=True, capture_output=True, text=True
        )
        return completed.stdout.strip()

    def _ensure_repo(self) -> None:
        if (self.repo_dir / ".git").exists():
            return
        self._run("init")
        self._run("config", "user.email", "traceagent@local")
        self._run("config", "user.name", "TraceAgent")

    def commit_all(self, message: str) -> str:
        self._run("add", ".")
        status = self._run("status", "--porcelain")
        if status:
            self._run("commit", "-m", message)
            return self._run("rev-parse", "HEAD")
        has_head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=self.repo_dir, capture_output=True
        ).returncode == 0
        if has_head:
            return self._run("rev-parse", "HEAD")
        self._run("commit", "--allow-empty", "-m", message)
        return self._run("rev-parse", "HEAD")

    def diff(self, older_commit: str, newer_commit: str) -> str:
        return self._run("diff", older_commit, newer_commit)

    def revert_to(self, commit_hash: str) -> str:
        self._run("reset", "--hard", commit_hash)
        return self._run("rev-parse", "HEAD")
