from typing import Literal
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class GatewayDecision(BaseModel):
    """分析用户输入，判定意图并提取关键槽位。"""
    intent: Literal["general_qa", "troubleshoot"] = Field(
        description="用户单纯请教运维知识、闲聊选择 'general_qa'；用户要求排查具体的构建错误、查报错选择 'troubleshoot'"
    )
    project_name: str = Field(
        default=None,
        description="如果用户的意图是排查构建失败，请从中提取具体的项目名"
    )

class GatewayRouter:
    def __init__(self):

        llm = ChatOpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_API_HOST,
            model="qwen-max",
            temperature=0.0,
        )
        self.router = None

    def route(self, user_input: str):
        return self.router.route(user_input)