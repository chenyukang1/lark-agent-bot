"""Git operations independent of application settings and agent frameworks."""

import subprocess
from collections.abc import Sequence
from pathlib import Path


class GitCommandError(subprocess.CalledProcessError):
    """A Git command failed; stdout, stderr and exit status are available."""


class GitRepository:
    def __init__(
        self, path: str | Path, *, timeout: float = 15, check: bool = True
    ) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.check = check

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if self.check and result.returncode:
            raise GitCommandError(
                result.returncode, result.args, output=result.stdout, stderr=result.stderr
            )
        return result

    def output(self, *args: str) -> str:
        return self.run(args).stdout

    def fetch(self, remote: str = "origin") -> str:
        return self.output("fetch", remote)

    def pull(self) -> str:
        return self.output("pull")

    def require_commit(self, commit_id: str) -> None:
        self.output("cat-file", "-e", f"{commit_id}^{{commit}}")

    def commit_author(self, commit_id: str) -> tuple[str, str]:
        name, email = self.output(
            "show", "-s", "--format=%an%x00%ae", commit_id, "--"
        ).strip().split("\0")
        return name, email

    def commit_changes(self, commit_id: str) -> tuple[str, set[str]]:
        """Read a commit's patch and paths, comparing merges to the first parent."""
        parents = self.output(
            "rev-list", "--parents", "-n", "1", commit_id, "--"
        ).split()[1:]
        diff_args = ("diff", parents[0], commit_id) if parents else (
            "show", "--format=", commit_id
        )
        patch = self.output(
            *diff_args, "--no-ext-diff", "--no-textconv", "--unified=5", "--"
        )
        files = self.output(*diff_args, "--name-only", "-z", "--")
        return patch, set(filter(None, files.split("\0")))

    def switch_to_remote(self, branch: str, remote: str = "origin") -> str:
        """Reset the local branch to a remote ref; callers own this policy."""
        return self.output("switch", "-C", branch, f"{remote}/{branch}")
