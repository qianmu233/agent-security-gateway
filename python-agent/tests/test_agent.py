import asyncio

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from p3_agent.contracts import BoundaryError, Outcome
from p3_agent.graph import Limits, public_result, run_agent
from p3_agent.models import ChatModel, FakeLLM, tool_message
from p3_agent.scenarios import ATTACK_NOTE, TASK, injection_category, scripted


class StubClient:
    """Unit boundary only, NOT MCP integration evidence."""
    def __init__(self, *, deny=False, delay=0):
        self.sensitive = ["SYNTHETIC_PRIVATE_CREDENTIAL_VALUE"]
        self.calls, self.deny, self.delay = [], deny, delay
    async def call(self, name, args):
        self.calls.append((name, args))
        await asyncio.sleep(self.delay)
        if self.deny or name == "purchase_order.update":
            return Outcome(name, False, "INTENT_REQUIRED", "unit-request")
        return Outcome(name, True, "ALLOW", "unit-request", {
            "productId": "sku-a1", "tenant": "tenant-a", "available": 120,
            "note": ATTACK_NOTE, "noteTrust": "UNTRUSTED_DATA"})


async def test_real_graph_keeps_tool_note_out_of_system_and_publishes_receipts_only():
    model, client = scripted(), StubClient()
    state = await run_agent(TASK, model, client)
    assert state["status"] == "completed" and state["model_calls"] == 2 and state["tool_calls"] == 1
    assert "120" in state["answer"] and "ATTACK_SYNTHETIC_ONLY" not in state["answer"]
    assert all(ATTACK_NOTE not in m.content for messages in model.seen for m in messages if isinstance(m, SystemMessage))
    assert any(ATTACK_NOTE in m.content for m in model.seen[1] if isinstance(m, ToolMessage))
    assert [e["node"] for e in state["events"]] == ["decide", "tool", "decide", "finish"]


async def test_denial_terminates_without_retry_or_more_model_calls():
    client, model = StubClient(), scripted("forced-injection")
    state = await run_agent(TASK, model, client)
    assert state["error"] == "INTENT_REQUIRED" and len(client.calls) == 2 and state["model_calls"] == 2
    assert "拒绝" in state["answer"] and "999" not in state["answer"]


@pytest.mark.parametrize("name,args", [
    ("authorize_intent", {}),
    ("inventory_read", {"productId": "sku-a1", "role": "ADMIN"}),
    ("purchase_order_update", {"orderId": "po-a1", "quantity": True}),
    ("purchase_order_update", {"orderId": "po-a1", "quantity": 10, "intentId": "A"*43}),
])
async def test_invalid_model_tool_and_arguments_never_reach_client(name, args):
    client = StubClient()
    state = await run_agent(TASK, FakeLLM([tool_message(name, args)]), client)
    assert state["status"] == "stopped" and not client.calls


async def test_loop_budget_and_model_budget_are_bounded():
    reply = tool_message("inventory_read", {"productId": "sku-a1"})
    for limits, expected in [(Limits(tool_calls=2), "TOOL_CALL_BUDGET"),
                             (Limits(model_calls=2), "MODEL_CALL_BUDGET")]:
        client = StubClient()
        state = await run_agent(TASK, FakeLLM([reply]*10), client, limits=limits)
        assert state["error"] == expected and state["model_calls"] <= limits.model_calls
        assert len(client.calls) <= limits.tool_calls


@pytest.mark.parametrize("slow", ["model", "tool"])
async def test_timeout_stops_and_does_not_publish_late_success(slow):
    client = StubClient(delay=.15 if slow == "tool" else 0)
    model = FakeLLM([tool_message("inventory_read", {"productId": "sku-a1"})],
                    delay=.15 if slow == "model" else 0)
    state = await run_agent(TASK, model, client, limits=Limits(step_seconds=.02))
    assert state["error"] == ("MODEL_TIMEOUT" if slow == "model" else "MCP_TIMEOUT")
    assert not state["receipts"] and "120" not in state["answer"]


async def test_secrets_and_unsafe_model_final_are_not_published():
    client = StubClient()
    secret = client.sensitive[0]
    with pytest.raises(BoundaryError, match="SENSITIVE_DATA"):
        await run_agent(secret, scripted(), client)
    state = await run_agent(TASK, FakeLLM([AIMessage(content=secret)]), client)
    assert state["error"] == "SENSITIVE_DATA_REJECTED" and secret not in str(state)
    state = await run_agent(TASK, FakeLLM([AIMessage(content="请窃取其他租户资料")]), client)
    assert "窃取" not in public_result(state, {"provider": "fake"})["answer"]


def test_remote_model_requires_separate_authorization_and_categories_are_distinct():
    with pytest.raises(BoundaryError, match="PAID_MODEL_NOT_AUTHORIZED"):
        ChatModel("https://api.deepseek.com", "deepseek-flash", "not-a-real-key")
    base = {"dangerous_proposal": True, "gateway_denied": True, "unsafe_delivered": False,
            "unauthorized_side_effect": False}
    assert injection_category(**base).startswith("2_")
    assert injection_category(**{**base, "unsafe_delivered": True}).startswith("3_")
    assert injection_category(**{**base, "unauthorized_side_effect": True}).startswith("4_")
    assert injection_category(**{**base, "dangerous_proposal": False}).startswith("1_")


@pytest.mark.parametrize("metadata", [{"finish_reason": "length"}, {"status": "incomplete"},
                                     {"stop_reason": "max_tokens"}])
async def test_truncated_valid_tool_proposal_stops_before_mcp(metadata):
    reply = tool_message("inventory_read", {"productId": "sku-a1"})
    reply.response_metadata = metadata
    client = StubClient()
    state = await run_agent(TASK, FakeLLM([reply]), client)
    assert state["error"] == "MODEL_OUTPUT_TRUNCATED" and state["status"] == "stopped"
    assert state["model_calls"] == 1 and not client.calls and not state["receipts"]


async def test_normal_no_tool_response_remains_valid_general_conversation():
    client = StubClient()
    state = await run_agent("你好", FakeLLM([AIMessage(content="你好", response_metadata={"finish_reason": "stop"})]), client)
    assert state["status"] == "completed" and state["error"] is None and not client.calls
