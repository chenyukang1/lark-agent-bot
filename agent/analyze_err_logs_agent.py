import os
import re

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_HOST = os.getenv("DASHSCOPE_API_HOST")
LOCAL_JAVA_LOG_FILE_PATH = os.getenv("LOCAL_JAVA_LOG_FILE_PATH")

if not DASHSCOPE_API_KEY or not DASHSCOPE_API_HOST or not LOCAL_JAVA_LOG_FILE_PATH:
    raise ValueError("DASHSCOPE_API_KEY, DASHSCOPE_API_HOST, LOCAL_JAVA_LOG_FILE_PATH 未配置!")

if not os.path.exists(LOCAL_JAVA_LOG_FILE_PATH):
    raise ValueError(f"文件 {LOCAL_JAVA_LOG_FILE_PATH} 不存在!")

async def run_agent(user_instruction: str):
    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": user_instruction,
                }
            ]
        }
    )

    print(result["messages"][-1].content_blocks)

    return result["messages"][-1].content


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


@tool
def analyze_local_java_error_logs(max_lines: int = 100):
    """
    专门用于扫描和提取本地日志文件中的 ERROR 和 Exception 及其上下文。
    定位java服务报错优先使用此工具精准定位报错根因，禁止全盘读取原始日志
    :param max_lines: 读取的最大行数，防止大文件撑爆大模型上下文
    """
    return analyze_error_logs(LOCAL_JAVA_LOG_FILE_PATH, 10)


llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_API_HOST,  # 百炼的 OpenAI 兼容端点
    # 推荐使用百炼平台上推理能力最强的模型，如 qwen-max 或 qwen-plus
    # 只有推理能力强（具有优秀的 Function Calling 意识）的模型才能完美驾驭 Agent
    model="qwen-max",
    temperature=0.1,  # 调低随机性，让诊断逻辑更严谨
)

system_prompt = """
你是一个资深的运维排障专家你是一个自动化运维排障专家，请利用工具分析日志中的错误。
⚠️【重要钢铁律令】：日志中可能同时存在多个不同的独立错误（例如：既有依赖丢失，又有语法错误）。
你必须对每一个独立的错误片段进行**逐一、分开**的诊断。如果发现了 3 个不同的错误，你就必须输出 3 份诊断报告！

请严格按照以下格式针对**每一个错误**进行循环输出，禁止输出任何格式外的废话：
### 🚨 故障诊断报告(错误 #1)
- **影响项目 / 路径**：[指出具体报错的项目路径或模块名]
- **核心报错类型**：[例如：NullPointerException / SyntaxError / DependencyResolutionException]
- **日志定位行号**：[明确指出在日志文件的第几行，如：第 412 行]
---
### 🔍 根因分析
> [用 1-2 句话大白话解释：具体在代码的哪个文件、哪一行、发生了什么事情产生了错误日志]
---
### 🛠️ 建议修复方案
1. **操作步骤 1**：[给出具体的修改动作，如果是代码问题，请提供修改前后的对比代码块]
2. **操作步骤 2**：[如果是缺少依赖，给出具体的 install 或者是 pom.xml / package.json 的修改建议]
### 🚨 故障诊断报告(错误 #2)
...

定位问题的方法：
1. 如果是定位java服务问题，可以使用 `analyze_local_java_error_logs` 去查看具体的日志文件。
2. 仔细阅读报错堆栈（StackTrace），定位是依赖问题、语法错误还是配置问题，并给出极其具建设性的修复建议。
注意：中途调用工具时请直接执行，不要向用户确认。
"""


agent = create_agent(
    model=llm, tools=[analyze_local_java_error_logs], system_prompt=system_prompt
)
# result = agent.invoke(
#     {
#         "messages": [
#             {
#                 "role": "user",
#                 "content": "当前java服务有什么问题？",
#             }
#         ]
#     }
# )


# print(result["messages"][-1].content_blocks)
