from app.agents.devops.router import DevopsRouter
from app.agents.devops.v2.subagents.qa import QaAgent


class DevopsAgentV2:
    def __init__(self):
        self.router = DevopsRouter()
        self.qa_agent = QaAgent()

    async def handle_user_query(
        self, chat_id: str, open_id: str, user_input: str, card_callback
    ) -> str:
        decision = self.router.route(user_input)
        if decision.intent == "general_qa":
            thread_id = f"{chat_id}_{open_id}"
            card_callback("正在作为【日常运维助手】回答问题，请稍候...")
            return await self.qa_agent.run(user_input, thread_id)

        elif decision.intent == "troubleshoot":
            if not decision.alias:
                return "如果您的意图是排查构建失败，请重新提问并给出具体的构建失败任务名称。"
            card_callback("正在作为【构建故障分析专家】分析故障原因，请稍候...")
            payload = get_latest_failed_build_info(alias)
            return await codebase_analysis(payload)

        elif decision.intent == "package":
            if not decision.alias:
                return "如果您的意图是执行打包，请重新提问并给出具体的任务名称。"
            card_callback("正在获取 Jenkins 配置并执行打包，请稍候...")
            return trigger_jenkins_build(alias)

        else:
            return "抱歉，我无法处理您的请求。"

    async def handle_image_query(
        self, chat_id: str, open_id: str, image_bytes: bytes, card_callback
    ) -> str:
        card_callback("收到图片故障分析任务，正在识别图片内容...")
        extracted_text = await analyze_image_content(image_bytes)
        if not extracted_text:
            return "未能从图片中识别出有效内容，请发送更清晰的截图或改用文字描述故障。"

        card_callback(
            f"图片识别完成，正在分析故障...\n\n**识别内容：**\n{extracted_text}"
        )
        return await self.handle_user_query(
            chat_id, open_id, extracted_text, card_callback
        )
