import re
from dataclasses import dataclass

from app.config import CodebaseConfig
from app.tools.git import GitCommandError, GitRepository
from app.tools.jenkins import JenkinsClientPool

JENKINS_CLIENT_POOL = JenkinsClientPool()
MAX_DIFF_CHARS = 100_000


@dataclass
class BuildChanges:
    commits: dict[str, dict]
    patches: str


def collect_build_changes(config: CodebaseConfig, build_number: int) -> BuildChanges:
    server = JENKINS_CLIENT_POOL.get_jenkins_client(config.alias)
    build = server.get_build_info(build_number)
    if "changeSet" not in build and "changeSets" not in build:
        raise ValueError("构建缺少 changeSet/changeSets，无法确定提交范围")
    change_sets = [build.get("changeSet") or {}, *(build.get("changeSets") or [])]
    ids = list(
        dict.fromkeys(
            item.get("commitId", "")
            for changes in change_sets
            for item in changes.get("items", [])
        )
    )
    if any(not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", cid) for cid in ids):
        raise ValueError("changeSet 中存在无效或缺失的 Git commit ID")
    repo = GitRepository(config.project_path, timeout=60)
    commits = {}
    patches = []
    fetched = False
    for cid in ids:
        try:
            repo.require_commit(cid)
        except GitCommandError:
            if not fetched:
                repo.fetch()
                fetched = True
            repo.require_commit(cid)
        name, email = repo.commit_author(cid)
        patch, files = repo.commit_changes(cid)
        commits[cid] = {
            "name": name,
            "email": email,
            "files": set(files),
            "patch": patch,
        }
        patches.append(f"COMMIT {cid}\n{patch}")
        if sum(map(len, patches)) > MAX_DIFF_CHARS:
            raise ValueError(
                "构建 diff 超过分析上限，需人工检查 SQL；未截断后交给模型判断"
            )
    return BuildChanges(commits=commits, patches="\n\n".join(patches))
