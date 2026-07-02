import os
from typing import Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from dotenv import load_dotenv
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_HOST = os.getenv("DASHSCOPE_API_HOST")

# 1. 定义期望的意图结构
class IntentClassifier(BaseModel):
    """分析用户的输入，并将其归类为以下明确的意图之一。"""
    intent: Literal["build_error", "general_ops", "chitchat"] = Field(
        description="build_error: 编译或构建报错; general_ops: 询问日常运维知识; chitchat: 闲聊或打招呼"
    )
    confidence: float = Field(description="置信度分数，范围 0.0 到 1.0")

# 2. 初始化模型并绑定结构化输出
llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_API_HOST,
    model="qwen-max",
    temperature=0.0,
)
structured_llm = llm.with_structured_output(IntentClassifier)

system_prompt = f"""
你是一个意图识别模型，请分析用户的输入，并将其归类为以下明确的意图之一。请以 JSON 格式输出

intent为以下之一：
build_error: 编译或构建报错; 
general_ops: 询问日常运维知识; 
chitchat: 闲聊或打招呼

confidence为0.0到1.0之间的浮点数，表示置信度。

请以 JSON 格式输出
"""

# 3. 组装提示词和链
template = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{user_input}"),
])
intent_chain = template | structured_llm

def route_intent(user_input: str) -> Literal["build_error", "general_ops", "chitchat"]:
    result = intent_chain.invoke({"user_input": user_input})
    return result.intent

# 4. 测试执行
if __name__ == "__main__":
    result = intent_chain.invoke({"user_input": "今天 Jenkins 打包一直报 maven 插件找不到，怎么搞？"})
    print(result.intent)      # 输出: build_error
    print(result.confidence)  # 输出: 0.95