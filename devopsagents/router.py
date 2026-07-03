from typing import Literal
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from devopsagents.config import DEFAULT_CONFIG


SYSTEM_PROMPT_TEMPLATE = """
你是一个意图识别模型，请分析用户的输入，并将其归类为以下明确的意图之一。请以 JSON 格式输出
intent为以下之一:
general_qa: 用户单纯请教运维知识、闲聊; 
troubleshoot: 用户要求排查具体的构建错误、查报错

jenkins_job_name为以下之一:
{jenkins_job_name_list}

请以 JSON 格式输出
"""


class DevopsRouterDecision(BaseModel):
    """分析用户输入，判定意图并提取关键槽位。"""

    intent: Literal["general_qa", "troubleshoot"] = Field(
        description="用户单纯请教运维知识、闲聊选择 'general_qa'；用户要求排查具体的构建错误、查报错选择 'troubleshoot'"
    )
    jenkins_job_name: str | None = Field(
        default=None,
        description="如果用户的意图是排查构建失败, 请从中提取具体的jenkins任务名称",
    )


class DevopsRouter:
    def __init__(self):
        llm = ChatOpenAI(
            api_key=DEFAULT_CONFIG["dashscope_api_key"],
            base_url=DEFAULT_CONFIG["dashscope_api_host"],
            model="qwen-max",
            temperature=0.0,
        )
        self.structured_llm = llm.with_structured_output(DevopsRouterDecision)

    def route(self, user_input: str) -> DevopsRouterDecision:
        jenkins_job_name_list = DEFAULT_CONFIG["codebase_configs"].keys()
        template = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT_TEMPLATE.format(jenkins_job_name_list=jenkins_job_name_list)),
                ("human", "{user_input}"),
            ]
        )
        chain = template | self.structured_llm
        return chain.invoke({"user_input": user_input})

if __name__ == "__main__":
    router = DevopsRouter()
    # decision = router.route("今天java 测试环境 Jenkins 打包一直报 maven 插件找不到，怎么搞？")
    decision = router.route("hi")
    print(decision)