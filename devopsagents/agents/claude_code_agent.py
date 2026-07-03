import os
import asyncio
import re
import subprocess
import time
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
import lark_oapi as lark


# Claude Code sdk agent
class ClaudeCoodeAgent:
    def __init__(self):
        if os.getenv("ANTHROPIC_AUTH_TOKEN") is None:
            raise ValueError("ANTHROPIC_AUTH_TOKEN is not set")

    async def run(self, work_dir: str, prompt: str) -> str:
        options = ClaudeAgentOptions(
            cwd=work_dir,
            # allowed_tools=["Read", "Bash"],  # Auto-approve these tools
            permission_mode="plan",  # Auto-approve file edits
        )

        # Agentic loop: streams messages as Claude works
        async for message in query(
            prompt=prompt,
            options=options,
        ):
            if hasattr(message, "result") and message.result:
                lark.logger.debug(f"Claude result: {message.result}")
                return message.result

            # Print human-readable output
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, "text"):
                        print(f"Claude reasoning: {block.text}")
                        lark.logger.debug(f"Claude reasoning: {block.text}")
                    elif hasattr(block, "name"):
                        print(f"Claude tool being called: {block.name}")
                        lark.logger.debug(f"Claude tool being called: {block.name}")
            elif isinstance(message, ResultMessage):
                print(f"Done: {message.subtype}")
                lark.logger.debug(f"Done: {message.subtype}")  # Final result


ANALYSIS_PROMPT = """
你是一个资深的 CI/CD 排障专家，目标是从 Jenkins 最新一次失败构建中，阅读最近的代码提交记录，定位最可能导致失败的提交人（committer）。
你必须在 10 步之内推导出最终结论并给出故障报告。如果你无法在 10 步内完成，请直接输出当前已知的最大嫌疑人。

本次涉及到的信息如下：
jenkins job 名称为 qbit-assets-test,
jenkins 构建号为 123,
jenkins 构建链接为 https://jenkins.qbit.com/job/qbit-assets-test/123/,
jenkins 构建耗时为 1000ms,

jenkins控制台日志如下：
Error starting ApplicationContext. To display the condition evaluation report re-run your application with 'debug' enabled.
2026-07-02 13:48:06.986    [1;31m-ERROR[0;39m [36morg.springframework.boot.diagnostics.LoggingFailureAnalysisReporter:40[0;39m: 

***************************
APPLICATION FAILED TO START
***************************

Description:

The dependencies of some of the beans in the application context form a cycle:

   quantumCardHolderController
      ↓
   cardholderOpenApiV3Service
      ↓
   openApiCardServiceImpl
      ↓
   cardCommonV3Service
┌─────┐
|  qbitCardStatisticsServiceImpl
↑     ↓
|  quantumCardApiCustomerServiceImpl
↑     ↓
|  apiClientDebitRecordServiceImpl
↑     ↓
|  businessTransferHandler
↑     ↓
|  businessTransferExecutionServiceImpl defined in class path resource [com/qbit/common_all/transfer/core/execution/BusinessTransferExecutionServiceImpl.class]
↑     ↓
|  businessTransferQuoteServiceImpl defined in class path resource [com/qbit/common_all/transfer/core/quote/BusinessTransferQuoteServiceImpl.class]
↑     ↓
|  businessTransferFactory
↑     ↓
|  cryptoConnectWalletTransferService defined in class path resource [com/qbit/common_all/transfer/dispatch/CryptoConnectWalletTransferService.class]
↑     ↓
|  cryptoAssetV2ConvertServiceImpl
↑     ↓
|  cryptoAssetsExchangeServiceImpl
↑     ↓
|  exchangeServiceImpl
↑     ↓
|  partnerOrderServiceImpl
↑     ↓
|  salesReportStaticServiceImpl
└─────┘


Action:

Relying upon circular references is discouraged and they are prohibited by default. Update your application to remove the dependency cycle between beans. As a last resort, it may be possible to break the cycle automatically by setting spring.main.allow-circular-references to true.

严格按照以下 Markdown 格式输出最终结论。禁止添加任何“好的”、“没问题”等前后寒暄词，直接填表输出：

### 🚨 Jenkins 故障诊断报告
- **Job / 构建号**：[jenkins_job_name #build_number]
- **构建链接**：[build_url]
- **构建耗时**：[duration_ms]ms
- **失败现象**：[一句话描述编译失败/测试失败/部署失败等]
- **核心报错类型**：[例如：TypeError / DependencyResolutionException]
- **致命提交 (Commit)**：`[7位简短Commit ID]` (作者: [作者姓名])

---

### 🔍 代码级根因分析
> [用1-2大白话解释：XX同学在本次提交中修改了 XXX 文件，将原本的 XXX 删除了/改写成了 XXX。但是，这导致了 [结合第一步报错说明具体原因]，从而导致 Jenkins 编译/打包被阻断。]

### 🛠️ 建议修复方案
- **修复建议**：[给出具体的修改建议。如果是代码问题，请在此处提供一个明晰的修改后示例代码块]

当你分析出最终根因并准备结束回答时，你必须在回答的最末尾另起一行，严格按照以下格式输出元数据标签（以便后台系统识别并转化飞书强提醒，严禁漏写，如果有多个嫌疑人，则输出多行元数据标签）：
$$METADATA:{{"email": "找到的嫌疑人Git邮箱", "name": "找到的嫌疑人Git名字"}}$$
"""

error_log = """
Error starting ApplicationContext. To display the condition evaluation report re-run your application with 'debug' enabled.
2026-07-02 13:48:06.986    [1;31m-ERROR[0;39m [36morg.springframework.boot.diagnostics.LoggingFailureAnalysisReporter:40[0;39m: 

***************************
APPLICATION FAILED TO START
***************************

Description:

The dependencies of some of the beans in the application context form a cycle:

   quantumCardHolderController
      ↓
   cardholderOpenApiV3Service
      ↓
   openApiCardServiceImpl
      ↓
   cardCommonV3Service
┌─────┐
|  qbitCardStatisticsServiceImpl
↑     ↓
|  quantumCardApiCustomerServiceImpl
↑     ↓
|  apiClientDebitRecordServiceImpl
↑     ↓
|  businessTransferHandler
↑     ↓
|  businessTransferExecutionServiceImpl defined in class path resource [com/qbit/common_all/transfer/core/execution/BusinessTransferExecutionServiceImpl.class]
↑     ↓
|  businessTransferQuoteServiceImpl defined in class path resource [com/qbit/common_all/transfer/core/quote/BusinessTransferQuoteServiceImpl.class]
↑     ↓
|  businessTransferFactory
↑     ↓
|  cryptoConnectWalletTransferService defined in class path resource [com/qbit/common_all/transfer/dispatch/CryptoConnectWalletTransferService.class]
↑     ↓
|  cryptoAssetV2ConvertServiceImpl
↑     ↓
|  cryptoAssetsExchangeServiceImpl
↑     ↓
|  exchangeServiceImpl
↑     ↓
|  partnerOrderServiceImpl
↑     ↓
|  salesReportStaticServiceImpl
└─────┘


Action:

Relying upon circular references is discouraged and they are prohibited by default. Update your application to remove the dependency cycle between beans. As a last resort, it may be possible to break the cycle automatically by setting spring.main.allow-circular-references to true.
"""

if __name__ == "__main__":
    time_start = time.time()
    agent = ClaudeCoodeAgent()
    result = asyncio.run(agent.run("/Users/chenyk/work/qbit-assets-test", ANALYSIS_PROMPT))
    print(result)
    time_end = time.time()
    print(f"Time taken: {time_end - time_start} seconds")