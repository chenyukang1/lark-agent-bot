"""Model-facing adapters for application services."""

from langchain.tools import tool

from app.services import jenkins_queries

get_latest_failed_build_info = tool(jenkins_queries.get_latest_failed_build_info)
extract_failed_build_console_errors = tool(
    jenkins_queries.extract_failed_build_console_errors
)
