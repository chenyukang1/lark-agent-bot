"""Lark Agent Bot application modules."""

from app.agents.code_review.ddl_notice import DDLNoticeAgent
from app.agents.devops.v1.agent import DevopsAgentV1
from app.agents.devops.v2.agent import DevopsAgentV2

devopsAgentV1 = DevopsAgentV1()
devopsAgentV2 = DevopsAgentV2()
ddl_notice_agent = DDLNoticeAgent()
