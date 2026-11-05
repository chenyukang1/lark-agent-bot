import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents.devops.v3.tools import create_tools
from app.config import CodebaseConfig


class CodeToolsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-b", "main")
        (self.root / "src").mkdir()
        (self.root / "src/api.py").write_text("def handle():\n    return 'needle'\n")
        (self.root / ".env").write_text("TOKEN=needle-secret\n")
        (self.root / "src/.env.local").write_text("TOKEN=needle-secret\n")
        (self.root / "link").symlink_to("src/api.py")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.com",
                 "-c", "commit.gpgsign=false", "commit", "-m", "fixture")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.config = CodebaseConfig(
            alias="api", jenkins_job_name="api-build", jenkins_url="https://example.test",
            jenkins_user="private-user", jenkins_token="private-token",
            project_path=str(self.root), git_branch="main", semantics_hit_rule="API 服务",
        )
        self.tools = {tool.name: tool for tool in create_tools({"api": self.config})}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              text=True, capture_output=True).stdout

    def call(self, name, **kwargs):
        return self.tools[name].invoke(kwargs)

    def test_catalog_hides_credentials_and_local_path(self):
        catalog = json.dumps(self.call("list_projects"))
        for value in ("private-user", "private-token", str(self.root)):
            self.assertNotIn(value, catalog)
        self.assertIn("api", catalog)

    def test_resolved_sha_reads_committed_content_despite_dirty_worktree(self):
        revision = self.call("resolve_revision", alias="api")
        self.assertEqual(revision["sha"], self.sha)
        (self.root / "src/api.py").write_text("dirty worktree\n")
        result = self.call("read_file", alias="api", sha=self.sha, path="src/api.py")
        self.assertIn("2:     return 'needle'", result["content"])
        self.assertEqual(result["citation"], f"api@{self.sha}:src/api.py:L1-L2")

    def test_file_listing_limits_and_filters_secrets(self):
        result = self.call("list_files", alias="api", sha=self.sha, limit=1)
        self.assertEqual(len(result["files"]), 1)
        self.assertTrue(result["truncated"])
        files = self.call("list_files", alias="api", sha=self.sha)["files"]
        self.assertNotIn(".env", files)
        self.assertNotIn("src/.env.local", files)

    def test_search_returns_citations_and_excludes_secrets(self):
        result = self.call("search_code", alias="api", sha=self.sha, query="needle")
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["citation"], f"api@{self.sha}:src/api.py:L2-L2")
        self.assertNotIn("needle-secret", json.dumps(result))
        self.assertEqual(self.call("search_code", alias="api", sha=self.sha,
                                   query="absent")["matches"], [])

    def test_read_rejects_unsafe_paths_symlinks_and_unresolved_revision(self):
        for path in ("../outside", "/etc/passwd", ".env", "src/.env.local", "link"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.call("read_file", alias="api", sha=self.sha, path=path)
        with self.assertRaises(ValueError):
            self.call("read_file", alias="api", sha="HEAD", path="src/api.py")
        with self.assertRaises(KeyError):
            self.call("resolve_revision", alias="unknown")

    def test_failed_build_uses_exact_number_and_hides_local_path(self):
        with patch("app.tools.jenkins.JenkinsClient") as client:
            client.return_value.get_failed_build_info.return_value = json.dumps({
                "build_number": 42, "project_path": str(self.root),
                "build_errors": "x" * 13_000, "server_errors": "",
            })
            result = self.call("get_failed_build", alias="api", build_number=42)
        client.return_value.get_failed_build_info.assert_called_once_with(42)
        self.assertNotIn("project_path", result)
        self.assertEqual(len(result["build_errors"]), 12_000)
        self.assertTrue(result["build_errors_truncated"])
