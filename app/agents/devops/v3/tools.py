"""Read-only tools scoped to configured repositories and immutable Git objects."""

import fnmatch
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from langchain_core.tools import BaseTool, tool

from app.config import CodebaseConfig
from app.tools.git import GitRepository

_SECRET_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "id_rsa*",
                    "id_ed25519*", "codebase_configs.json", "user_mapping.json")
_SECRET_DIRS = {".git", ".ssh", ".aws", ".secrets"}


def _allowed_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and not path.startswith("/") and all(
        part not in {"..", ".", *_SECRET_DIRS}
        and not any(fnmatch.fnmatch(part, pattern) for pattern in _SECRET_PATTERNS)
        for part in parts
    ) and ":" not in path and "\x00" not in path and "\\" not in path


def create_tools(configs: Mapping[str, CodebaseConfig]) -> list[BaseTool]:
    """Build tools without exposing local paths or Jenkins credentials to models."""
    configs = dict(configs)

    def repository(alias: str) -> GitRepository:
        return GitRepository(configs[alias].project_path, timeout=15)

    def require_sha(sha: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
            raise ValueError("resolve a revision to a full SHA first")

    @tool
    def list_projects() -> list[dict]:
        """列出可查询项目、语义说明和默认分支，不返回凭据。"""
        return [{"alias": config.alias, "description": config.semantics_hit_rule,
                 "default_branch": config.git_branch} for config in configs.values()]

    @tool
    def resolve_revision(alias: str, revision: str = "") -> dict:
        """将本地已有分支或 commit 解析为 SHA，后续工具必须使用该 SHA。不 fetch。"""
        ref = revision or configs[alias].git_branch
        sha = repository(alias).output(
            "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
        ).strip()
        require_sha(sha)
        return {"alias": alias, "sha": sha}

    @tool
    def list_files(alias: str, sha: str, pattern: str = "*", limit: int = 100) -> dict:
        """列出指定 SHA 的文件，支持 glob 过滤；不显示已知凭据路径。"""
        require_sha(sha)
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        paths = repository(alias).output("ls-tree", "-r", "--name-only", "-z", sha).split("\0")
        matches = [path for path in paths if _allowed_path(path) and fnmatch.fnmatch(path, pattern)]
        return {"sha": sha, "files": matches[:limit], "truncated": len(matches) > limit}

    @tool
    def read_file(
        alias: str, sha: str, path: str, start_line: int = 1, end_line: int = 120
    ) -> dict:
        """读取指定 SHA 的文本文件行，返回可引用的版本、路径和行号。"""
        require_sha(sha)
        if not _allowed_path(path):
            raise ValueError("path is not allowed")
        if start_line < 1 or end_line < start_line or end_line - start_line >= 200:
            raise ValueError("request between 1 and 200 lines")
        repo = repository(alias)
        spec = f"{sha}:{path}"
        # Inspect the tree entry: never dereference Git symlinks or submodules.
        entry = repo.output("ls-tree", sha, "--", path)
        if not entry.startswith(("100644 blob ", "100755 blob ")):
            raise ValueError("path must be a regular tracked file")
        if int(repo.output("cat-file", "-s", spec)) > 512_000:
            raise ValueError("file exceeds 512 KB")
        content = repo.output("show", spec)
        if "\x00" in content:
            raise ValueError("binary file")
        lines = content.splitlines()
        if start_line > len(lines):
            raise ValueError("start_line is past end of file")
        end = min(end_line, len(lines))
        excerpt = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start_line, end + 1))
        return {"citation": f"{alias}@{sha}:{path}:L{start_line}-L{end}",
                "content": excerpt[:16_000], "truncated": len(excerpt) > 16_000}

    @tool
    def search_code(alias: str, sha: str, query: str, limit: int = 30) -> dict:
        """在指定 SHA 中搜索字面文本，返回文件、行号和片段；凭据路径被排除。"""
        require_sha(sha)
        if not query.strip() or "\n" in query or len(query) > 500 or not 1 <= limit <= 100:
            raise ValueError("provide a single-line query and limit between 1 and 100")
        exclusions = [f":(glob,exclude)**/{pattern}" for pattern in _SECRET_PATTERNS]
        exclusions += [f":(glob,exclude)**/{directory}/**" for directory in _SECRET_DIRS]
        result = GitRepository(configs[alias].project_path, check=False).run(
            ["grep", "-n", "-I", "-F", "-e", query, sha, "--", ".", *exclusions]
        )
        if result.returncode not in (0, 1):
            raise ValueError("git search failed")
        matches = []
        for row in result.stdout.splitlines():
            parts = row.split(":", 3)
            if len(parts) != 4:
                continue
            _, path, line, text = parts
            if _allowed_path(path) and line.isdigit():
                matches.append({"citation": f"{alias}@{sha}:{path}:L{line}-L{line}",
                                "text": text[:500]})
                if len(matches) > limit:
                    break
        return {"matches": matches[:limit], "truncated": len(matches) > limit}

    @tool
    def get_failed_build(alias: str, build_number: int) -> dict:
        """查询明确构建号的失败日志和 changeSet，不触发构建、不查询漂移的最新构建。"""
        from app.tools.jenkins import JenkinsClient

        if alias not in configs or build_number < 1:
            raise ValueError("provide a configured alias and positive build number")
        payload = json.loads(
            JenkinsClient(codebase_config=configs[alias]).get_failed_build_info(build_number)
        )
        payload.pop("project_path", None)
        for key in ("build_errors", "server_errors"):
            value = payload.get(key, "")
            payload[key] = value[:12_000]
            payload[f"{key}_truncated"] = len(value) > 12_000
        return payload

    return [list_projects, resolve_revision, list_files, read_file, search_code, get_failed_build]
