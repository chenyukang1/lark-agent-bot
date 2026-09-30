import logging
import re

logger = logging.getLogger(__name__)
MAX_CONSOLE_LOG_CHARS = 12000
MAX_ERROR_SNIPPETS = 20

def extract_jenkins_build_errors(console_log: str, max_lines: int = 60) -> str:
    """
    从 Jenkins 控制台日志中提取编译失败、测试失败、Maven 报错等关键行。
    """
    if not console_log.strip():
        return "控制台日志为空，无法提取错误片段。"

    keywords = [
        r"APPLICATION FAILED TO START",
        r"BUILD FAILURE",
        r"Compilation failure",
    ]

    error_index = -1
    lines = console_log.splitlines()
    for i, line in enumerate(lines):
        if any(re.search(kw, line, re.IGNORECASE) for kw in keywords):
            error_index = i
            break

    if error_index != -1:
        logger.debug(f"构建错误成功匹配到核心错误起点（第 {error_index} 行）")
        return "\n".join(lines[error_index:])

    logger.debug(f"构建错误未匹配到核心错误起点，返回最后 {max_lines} 行")
    return "\n".join(lines[-max_lines:])


def extract_server_startup_errors(console_log: str) -> str:
    """
    从 Jenkins 控制台日志中提取服务器启动日志
    """
    if not console_log.strip():
        return "控制台日志为空，无法提取服务器错误信息。"

    error_index = -1
    error_pattern = re.compile(r"最近 100 行启动日志", re.IGNORECASE)
    lines = console_log.splitlines()
    for i, line in enumerate(lines):
        if error_pattern.search(line):
            error_index = i
            break

    if error_index != -1:
        logger.debug(f"启动日志成功匹配到核心错误起点（第 {error_index} 行）")
        return "\n".join(lines[error_index + 1 : error_index + 101])
    else:
        logger.debug("启动日志未匹配到核心错误起点")
        return ""


def truncate_console_log(console_log: str) -> str:
    if len(console_log) <= MAX_CONSOLE_LOG_CHARS:
        return console_log
    return (
        console_log[-MAX_CONSOLE_LOG_CHARS:]
        + f"\n\n(注意：控制台日志过长，已截取尾部最近 {MAX_CONSOLE_LOG_CHARS} 字符)"
    )


def extract_jenkins_console_errors(console_log: str, context_lines: int = 2) -> str:
    """
    从 Jenkins 控制台日志中提取编译失败、测试失败、Maven 报错等关键片段。
    """
    if not console_log.strip():
        return "控制台日志为空，无法提取错误片段。"

    error_patterns = [
        re.compile(r"\[ERROR\].*", re.IGNORECASE),
        re.compile(r"BUILD FAILURE", re.IGNORECASE),
        re.compile(r"Failed to execute goal", re.IGNORECASE),
        re.compile(r"Compilation failure", re.IGNORECASE),
        re.compile(r"Tests run:.*Failures: [1-9]\d*", re.IGNORECASE),
        re.compile(r".*\.java:\d+:\d+:\s+error:", re.IGNORECASE),
        re.compile(r"Caused by:.*", re.IGNORECASE),
        re.compile(r"Exception:.*", re.IGNORECASE),
    ]

    lines = console_log.splitlines()
    matched_chunks: list[str] = []
    covered_lines: set[int] = set()

    for idx, line in enumerate(lines):
        if not any(pattern.search(line) for pattern in error_patterns):
            continue

        start = max(0, idx - context_lines)
        end = min(len(lines), idx + context_lines + 1)
        chunk_lines: list[str] = []

        for line_no in range(start, end):
            if line_no in covered_lines:
                continue
            prefix = "🚨 [ERROR_LINE] " if line_no == idx else "   "
            chunk_lines.append(f"{line_no + 1}: {prefix}{lines[line_no]}")
            covered_lines.add(line_no)

        if chunk_lines:
            matched_chunks.append("\n".join(chunk_lines))

        if len(matched_chunks) >= MAX_ERROR_SNIPPETS:
            break

    if not matched_chunks:
        return "未在控制台日志中匹配到明显的编译/测试失败关键字，请结合 changeSet 和 culprits 继续分析。"

    summary = (
        f"共提取 {len(matched_chunks)} 处关键错误片段：\n\n"
        + "\n\n--- 错误片段分割线 ---\n\n".join(matched_chunks)
    )
    if len(summary) > MAX_CONSOLE_LOG_CHARS:
        return summary[-MAX_CONSOLE_LOG_CHARS:] + "\n\n(注意：错误片段过多，已截取尾部关键内容)"
    return summary
