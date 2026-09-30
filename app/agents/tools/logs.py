import os

from langchain.tools import tool

from app.parsers.error_logs import analyze_error_logs


@tool
def analyze_local_java_error_logs(max_lines: int = 100):
    """
    专门用于扫描和提取本地日志文件中的 ERROR 和 Exception 及其上下文。
    定位java服务报错优先使用此工具精准定位报错根因，禁止全盘读取原始日志
    :param max_lines: 读取的最大行数，防止大文件撑爆大模型上下文
    """
    path = os.getenv("LOCAL_JAVA_LOG_FILE_PATH")
    if not path:
        raise ValueError("LOCAL_JAVA_LOG_FILE_PATH 未配置")
    return analyze_error_logs(path, 10)
