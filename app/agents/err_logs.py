from functools import lru_cache

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.config import get_config

from .tools.logs import analyze_local_java_error_logs


async def run_err_logs_agent(user_instruction: str):
    result = await get_agent().ainvoke(
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


@lru_cache(maxsize=1)
def get_agent():
    config = get_config()
    llm = ChatOpenAI(
        api_key=config["dashscope_api_key"],
        base_url=config["dashscope_api_host"],
        model="qwen-max",
        temperature=0.1,
    )
    return create_agent(
        model=llm, tools=[analyze_local_java_error_logs], system_prompt=system_prompt
    )
