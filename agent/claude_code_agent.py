import asyncio
from asyncio import subprocess

import lark_oapi as lark

CLAUDE_TIMEOUT_SECONDS = 180


async def run_claude_code_agent(project_path: str, user_instruction: str):
    """
    后台异步任务：将任务派发给本地的 Claude Code Agent
    """
    try:
        # 1. 构造发给 Claude Code 的 Prompt
        full_prompt = f"请进入目录 {project_path}。用户报告了以下问题：'{user_instruction}'。请利用你的工具查看日志、分析故障原因，并给出最终的分析报告。"

        # 2. 用非交互模式启动 Claude Code
        # -p 参数（或者直接通过标准输入传入命令）可以让 Claude 执行完任务后自动退出
        process = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            full_prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_path,  # 限制它的初始工作目录
        )

        lark.logger.debug("Claude Code Agent 已启动，正在自动分析故障中...")

        # 3. 等待 Claude Code 自动运行它所需的工具（这个过程可能需要 1-3 分钟）
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), CLAUDE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return "Claude Code 分析超时, 请稍后重试"

        # 4. 获取 Claude Agent 的最终执行结果
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        if process.returncode != 0:
            lark.logger.error(f"Claude Code 执行失败, returncode: {process.returncode}, stderr: {stderr_text}")
            return "Claude Code 执行失败, 请联系开发人员排查"

        # 5. 调用飞书 API，把 Claude 帮你想好的分析报告延迟回复给用户
        lark.logger.debug("Claude Code 分析完毕, 准备发送给飞书...")

        agent_output = stdout_text
        if stderr_text:
            agent_output += f"\n[系统错误]\n{stderr_text}"

        lark.logger.debug(f"Claude Code 分析结果: {agent_output}")
        return agent_output

    except Exception as e:
        lark.logger.error(f"唤起 Claude Code 失败: {e}")
        return "唤起 Claude Code 失败, 联系开发人员排查"
