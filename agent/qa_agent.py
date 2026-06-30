from typing import Sequence


from langchain_core.messages.utils import MessageLikeRepresentation


from langchain_core.messages.base import BaseMessage


import asyncio
import os
import time
import uuid
from langchain.agents import create_agent
from langchain_core.messages import trim_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_HOST = os.getenv("DASHSCOPE_API_HOST")

if not DASHSCOPE_API_KEY or not DASHSCOPE_API_HOST:
    raise ValueError("DASHSCOPE_API_KEY, DASHSCOPE_API_HOST 未配置!")

async def run_qa_agent(user_instruction: str, thread_id: str):
    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": user_instruction,
                }
            ]
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    return result["messages"][-1].content

llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_API_HOST,
    model="qwen-max",
    temperature=0.0,
)

system_prompt = """
# Role
你是一名经验丰富、亲和力强的企业级高级运维架构师（SRE）。你负责为开发人员和初级运维提供日常的技术咨询、最佳实践指导以及系统架构建议。

# Goal
以专业、通俗且规范的语言，解答用户关于 Linux 系统、云原生（Kubernetes/Docker）、网络、监控（Prometheus）以及 CI/CD 流程等日常运维和架构疑问。

# Guidelines & Constraints
1. 【定位清晰】：你当前处于“日常咨询”模式。如果用户提出的问题明显属于“代码编译失败、Jenkins 构建报错、容器部署崩溃”等具体的构建阻塞问题，请礼貌地提示用户：“检测到您遇到了具体的构建/部署错误，正在为您切换到专门的【构建排障专家】分支为您处理...”。
2. 【规范优先】：在提供解决方案时，优先推荐符合企业安全规范和最佳实践的做法（例如：不推荐直接使用 root 权限，推荐使用非对称密钥而非密码等）。
3. 【清晰易读】：回答技术命令时，必须使用 Markdown 代码块（如 ```bash ... ```）包裹，并对关键参数进行简要注释。
4. 【不瞎猜】：对于你不确定的专有名词或企业内部私有流程，诚实地回答不知道，并建议用户查阅公司内部 Wiki。

# Style
你的语气应该既专业严谨，又耐心友好。多使用“建议您...”、“通常的做法是...”等引导性词汇。
"""

message_trimer = trim_messages[Sequence[MessageLikeRepresentation], list[BaseMessage]](
    max_tokens=4000,
    strategy="last",
    token_counter=llm,
    include_system=True,
    start_on="human",
)

agent = create_agent(
    model=llm,
    system_prompt=system_prompt,
    message_trimer=message_trimer,
    checkpointer=InMemorySaver(),
)

if __name__ == "__main__":
    thread_id = str(uuid.uuid4())
    result = asyncio.run(run_qa_agent("如何解决 Jenkins 构建失败的问题？", thread_id))
    print(result)

    time.sleep(1)

    result = asyncio.run(run_qa_agent("我们刚刚在聊什么？", thread_id))
    print(result)