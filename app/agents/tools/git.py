"""Model-facing adapters for application services."""

from langchain.tools import tool

from app.services import git_analysis

search_file_commit_history = tool(git_analysis.search_file_commit_history)
get_build_commit_range_by_page = tool(git_analysis.get_build_commit_range_by_page)
get_commit_diff = tool(git_analysis.get_commit_diff)
blame_file_at_line = tool(git_analysis.blame_file_at_line)
