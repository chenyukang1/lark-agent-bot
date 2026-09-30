import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tools.git import GitCommandError, GitRepository


class GitRepositoryTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.repo = GitRepository(self.path)
        self.repo.run(["init"])
        self.repo.run(["config", "user.name", "Alice"])
        self.repo.run(["config", "user.email", "alice@example.com"])
        self.repo.run(["config", "commit.gpgsign", "false"])
        (self.path / "file with spaces.txt").write_text("original\n")
        self.repo.run(["add", "."])
        self.repo.run(["commit", "-m", "initial"])
        self.commit = self.repo.output("rev-parse", "HEAD").strip()

    def test_reads_committed_patch_without_changing_dirty_checkout(self):
        target = self.path / "file with spaces.txt"
        target.write_text("uncommitted edit\n")
        before = self.repo.output("status", "--porcelain")

        self.repo.require_commit(self.commit)
        self.assertEqual(
            self.repo.commit_author(self.commit), ("Alice", "alice@example.com")
        )
        diff, files = self.repo.commit_changes(self.commit)

        self.assertEqual(files, {"file with spaces.txt"})
        self.assertIn("+original", diff)
        self.assertNotIn("uncommitted edit", diff)
        self.assertEqual(self.repo.output("status", "--porcelain"), before)
        self.assertEqual(target.read_text(), "uncommitted edit\n")

    def test_failure_preserves_git_diagnostics(self):
        with self.assertRaises(GitCommandError) as error:
            self.repo.require_commit("missing-commit")
        self.assertNotEqual(error.exception.returncode, 0)
        self.assertTrue(error.exception.stderr)

    def test_unchecked_mode_returns_failure_for_legacy_tool_formatting(self):
        result = GitRepository(self.path, check=False).run(
            ["rev-parse", "missing-commit"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr)

    def test_timeout_is_not_reported_as_success(self):
        with (
            patch(
                "app.integrations.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["git", "fetch"], 1),
            ),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            self.repo.fetch()
