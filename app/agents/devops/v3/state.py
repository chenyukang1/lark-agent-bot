from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, model_validator


class Decision(BaseModel):
    """One model-selected step; the harness owns execution and limits."""

    action: Literal["tool", "ask", "answer"]
    content: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action(self) -> "Decision":
        if self.action == "tool" and not self.tool_name.strip():
            raise ValueError("tool action requires tool_name")
        if self.action != "tool" and not self.content.strip():
            raise ValueError("ask/answer action requires content")
        return self


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    decision: dict[str, Any]
    model_calls: int
    tool_calls: int
    status: Literal["running", "waiting_input", "completed", "limited", "failed"]
    content: str


class AgentResponse(BaseModel):
    thread_id: str
    status: Literal["waiting_input", "completed", "limited", "failed"]
    content: str
    question_id: str | None = None
