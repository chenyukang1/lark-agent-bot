import base64
import os

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from devopsagents.config import DEFAULT_CONFIG

IMAGE_ANALYSIS_PROMPT = """
请仔细分析这张图片，提取其中与 Jenkins 构建失败、服务器报错、代码编译/测试失败相关的所有信息。

请以一段可直接用于故障排查的自然语言描述输出，需尽量包含：
- Jenkins Job 名称或项目/环境别名（如有）
- 构建号（如有）
- 核心报错信息与堆栈片段
- 提交人、Commit ID 等线索（如有）

只输出识别结果，不要添加寒暄或解释。若图片中没有明显故障信息，请如实描述图片内容。
"""

_VISION_MODEL = os.getenv("DASHSCOPE_VISION_MODEL", "qwen-vl-max")


def _guess_mime_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


async def analyze_image_content(image_bytes: bytes) -> str:
    mime_type = _guess_mime_type(image_bytes)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    llm = ChatOpenAI(
        api_key=DEFAULT_CONFIG["dashscope_api_key"],
        base_url=DEFAULT_CONFIG["dashscope_api_host"],
        model=_VISION_MODEL,
        temperature=0.0,
    )

    response = await llm.ainvoke(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": IMAGE_ANALYSIS_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                    },
                ]
            )
        ]
    )

    content = response.content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    return str(content).strip()
