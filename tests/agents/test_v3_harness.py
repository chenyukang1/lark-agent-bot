import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agents.devops.v3 import AgentHarness, Decision, DevopsAgentV3


def model_with(*decisions):
    model = Mock()
    runner = Mock(ainvoke=AsyncMock(side_effect=list(decisions)))
    model.with_structured_output.return_value = runner
    return model, runner


class HarnessTest(unittest.IsolatedAsyncioTestCase):
    async def test_tool_observation_and_follow_up_share_history(self):
        @tool
        def lookup(project: str) -> str:
            """Read project information."""
            return f"evidence for {project}"

        model, runner = model_with(
            Decision(action="tool", tool_name="lookup", arguments={"project": "api"}),
            Decision(action="answer", content="first answer"),
            Decision(action="answer", content="follow up"),
        )
        agent = DevopsAgentV3(model=model, tools=[lookup])
        result = await agent.run("user-a", "explain api")
        self.assertEqual(result.status, "completed")
        observations = runner.ainvoke.call_args_list[1].args[0]
        self.assertIn("evidence for api", observations[-1].content)
        await agent.run("user-a", "why?")
        history = runner.ainvoke.call_args.args[0]
        self.assertTrue(any(message.content == "first answer" for message in history))

    async def test_interrupt_resumes_only_with_current_question(self):
        model, runner = model_with(
            Decision(action="ask", content="which project?"),
            Decision(action="answer", content="api explained"),
        )
        harness = AgentHarness(model)
        question = await harness.run("a", "explain project")
        self.assertEqual(question.status, "waiting_input")
        self.assertIsNotNone(question.question_id)
        with self.assertRaises(ValueError):
            await harness.run("a", "api")
        result = await harness.run("a", "api", question_id=question.question_id)
        self.assertEqual(result.content, "api explained")
        history = runner.ainvoke.call_args.args[0]
        self.assertEqual(history[-2].content, "which project?")
        self.assertIsInstance(history[-1], HumanMessage)
        with self.assertRaises(ValueError):
            await harness.run("a", "api", question_id=question.question_id)

    async def test_threads_are_isolated(self):
        model, runner = model_with(
            Decision(action="answer", content="secret-a"),
            Decision(action="answer", content="answer-b"),
        )
        harness = AgentHarness(model)
        await harness.run("a", "project-a")
        await harness.run("b", "project-b")
        self.assertNotIn("project-a", str(runner.ainvoke.call_args.args[0]))

    async def test_unknown_tool_is_observation_and_model_budget_stops_loop(self):
        model, runner = model_with(Decision(action="tool", tool_name="shell"))
        harness = AgentHarness(model, max_model_calls=1)
        result = await harness.run("a", "execute")
        self.assertEqual(result.status, "limited")
        state = await harness.graph.aget_state({"configurable": {"thread_id": "a"}})
        self.assertIn('"status": "error"', state.values["messages"][-1].content)
        self.assertEqual(runner.ainvoke.await_count, 1)

    async def test_tool_budget_stops_before_second_execution(self):
        calls = []

        @tool
        def lookup() -> str:
            """Read information."""
            calls.append(True)
            return "ok"

        model, _ = model_with(*[Decision(action="tool", tool_name="lookup")] * 2)
        result = await AgentHarness(model, [lookup], max_tool_calls=1).run("a", "read")
        self.assertEqual(result.status, "limited")
        self.assertEqual(len(calls), 1)

    async def test_tool_timeout_can_be_explained_by_model(self):
        @tool
        async def slow() -> str:
            """A slow read."""
            await asyncio.sleep(1)
            return "ok"

        model, runner = model_with(
            Decision(action="tool", tool_name="slow"),
            Decision(action="answer", content="read timed out"),
        )
        result = await AgentHarness(model, [slow], timeout=0.05).run("a", "read")
        self.assertEqual(result.status, "completed")
        self.assertIn("TimeoutError", runner.ainvoke.call_args.args[0][-1].content)
