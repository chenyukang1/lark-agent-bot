import os
import re

def analyze_error_logs(file_path: str, context_lines: int = 5) -> str:
    """
    专门用于扫描和提取本地日志文件中的 ERROR 和 Exception 及其上下文。
    优先使用此工具精准定位报错根因，禁止全盘读取原始日志。
    :param file_path: 日志文件的绝对路径
    :param context_lines: 发现错误行时，向前和向后额外提取的上下文行数
    """
    if not os.path.exists(file_path):
        return f"错误：日志文件 【{file_path}】 不存在。"

    # 定义错误匹配的正则表达式（忽略大小写）
    error_pattern = re.compile(r"(ERROR|Exception|Failed)")

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_lines = len(lines)
        matched_chunks = []
        # 用于记录哪些行已经被包含在上下文里了，防止重复提取
        covered_lines = set()

        for idx, line in enumerate(lines):
            if error_pattern.search(line):
                # 计算上下文的开始和结束行
                start = max(0, idx - context_lines)
                end = min(total_lines, idx + context_lines + 1)

                chunk = []
                for i in range(start, end):
                    if i not in covered_lines:
                        # 标记当前行是命中的错误行还是上下文行
                        prefix = "🚨 [ERROR_LINE] " if i == idx else "   "
                        chunk.append(f"{i + 1}: {prefix}{lines[i].strip()}")
                        covered_lines.add(i)

                if chunk:
                    matched_chunks.append("\n".join(chunk))

        if not matched_chunks:
            return f"检查完毕：在日志【{file_path}】中未匹配到明显的 ERROR 或 Exception 关键字。"

        # 组装最终结果
        result_summary = (
            f"汇总：在日志中筛选出 {len(matched_chunks)} 处关键错误片段：\n\n"
        )
        result_summary += "\n\n--- 错误片段分割线 ---\n\n".join(matched_chunks)

        # 兜底：如果错误太多，截取最新的 4000 个字符给大模型
        if len(result_summary) > 10000:
            print(result_summary[-10000:])
            return (
                result_summary[-10000:]
                + "\n\n(注意：日志报错过多，已自动截取尾部关键片段...)"
            )

        return result_summary

    except Exception as e:
        return f"分析日志时发生异常: {str(e)}"
