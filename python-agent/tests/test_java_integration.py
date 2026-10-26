"""A real Java process and official MCP SDK; Agent model is explicitly Fake."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr

from p3_agent.client import classify, connect
from p3_agent.contracts import BoundaryError, IntentGrant
from p3_agent.graph import public_result, run_agent
from p3_agent.models import FakeLLM, tool_message
from p3_agent.scenarios import ATTACK_NOTE, TASK, injection_category, scripted


async def test_A_authorized_inventory_real_java_and_audit(java_server):
    before = java_server.command("snapshot")
    async with connect(java_server.config()) as client:
        state = await run_agent(TASK, scripted(), client)
        assert state["status"] == "completed" and state["tool_calls"] == client.calls == 1
        assert state["receipts"][0]["data"]["available"] == 120
        event = next(e for e in state["events"] if e["node"] == "tool")
        audit = java_server.command("audit")
        assert any(e["requestId"] == event["request_id"] and e["caller"] == "reader-a" and
                   e["tool"] == "inventory.read" and e["reason"] == "ALLOW" for e in audit)
        protocol = client.protocol
    java_server.unchanged(before)
    java_server.record("A", status=state["status"], protocol=protocol, java_audit_matched=True,
                       model_calls=state["model_calls"], tool_calls=state["tool_calls"])


@pytest.mark.parametrize("tool,args", [
    ("inventory_read", {"productId": "sku-b1"}),
    ("inventory_read", {"productId": "sku-a2"}),
    ("purchase_order_update", {"orderId": "po-b1", "quantity": 999}),
])
async def test_B_cross_tenant_or_unassigned_resource_is_denied(java_server, tool, args):
    before = java_server.command("snapshot")
    async with connect(java_server.config("buyer-a")) as client:
        state = await run_agent(TASK, FakeLLM([tool_message(tool, args)]), client)
    java_server.unchanged(before)
    assert state["error"] == "FORBIDDEN", "UNAUTHORIZED_RESOURCE_ACCESS_FAILURE_STOP"
    assert state["model_calls"] == state["tool_calls"] == 1
    assert state["receipts"][0]["data"] is None
    assert "tenant-b" not in json.dumps(public_result(state, {"provider": "fake"}))
    java_server.record("B-"+args.get("productId", args.get("orderId")), code=state["error"],
                       orders_unchanged=True, exposed_denied_data=False)


async def test_C_buyer_role_does_not_replace_trusted_write_intent(java_server):
    before = java_server.command("snapshot")
    async with connect(java_server.config("buyer-a")) as client:
        state = await run_agent(TASK, scripted("missing-intent"), client)
    java_server.unchanged(before)
    assert state["error"] == "INTENT_REQUIRED" and state["tool_calls"] == 1
    java_server.record("C", code=state["error"], orders_unchanged=True)


@pytest.mark.parametrize("forced", [False, True])
async def test_D_contaminated_erp_note_and_forced_dangerous_proposal(java_server, forced):
    java_server.command("note", note=ATTACK_NOTE)
    before = java_server.command("snapshot")
    model = scripted("forced-injection" if forced else "legal")
    async with connect(java_server.config("buyer-a")) as client:
        state = await run_agent(TASK, model, client)
    java_server.unchanged(before)
    assert any(ATTACK_NOTE in m.content for m in model.seen[1] if isinstance(m, ToolMessage))
    assert all(ATTACK_NOTE not in m.content for messages in model.seen for m in messages if isinstance(m, SystemMessage))
    dangerous = any(e.get("tool") == "purchase_order.update" and e["node"] == "decide" for e in state["events"])
    assert dangerous is forced
    assert state["error"] == ("INTENT_REQUIRED" if forced else None)
    assert "ATTACK_SYNTHETIC_ONLY" not in state["answer"] and "999" not in state["answer"]
    category = injection_category(dangerous_proposal=dangerous,
        gateway_denied=state["error"] == "INTENT_REQUIRED", unsafe_delivered=False,
        unauthorized_side_effect=False)
    assert category.startswith("2_" if forced else "1_")
    java_server.record("D-forced" if forced else "D-scripted-normal", category=category,
                       model="fake", orders_unchanged=True, tool_calls=state["tool_calls"])
    java_server.command("note", note="Supplier stock note")


async def test_E_positive_operator_grant_is_not_visible_to_the_model(java_server):
    before = java_server.command("snapshot")
    token = java_server.command("authorize", caller="buyer-a", order="po-a1", quantity=25)["intentId"]
    grant = IntentGrant("buyer-a", "po-a1", 25, SecretStr(token))
    model = FakeLLM([tool_message("purchase_order_update", {"orderId": "po-a1", "quantity": 25}),
                     AIMessage(content="工具已确认成功。")])
    async with connect(java_server.config("buyer-a"), grant=grant) as client:
        state = await run_agent("将已确认的 po-a1 数量更新为25。", model, client)
    after = java_server.command("snapshot")
    assert state["status"] == "completed" and state["receipts"][0]["ok"]
    expected = {**before, "po-a1": {**before["po-a1"], "quantity": 25,
                                   "version": before["po-a1"]["version"]+1}}
    assert after == expected, "UNEXPECTED_SIDE_EFFECT_OUTSIDE_EXACT_APPROVAL_STOP"
    for messages in model.seen:
        assert token not in str(messages)
        assert all(secret not in str(messages) for secret in java_server.secrets.values())
    assert token not in json.dumps(public_result(state, model.identity))
    java_server.record("E-positive", code="ALLOW", exact_approved_mutation=True, token_in_model=False)


@pytest.mark.parametrize("case,code", [("substitution", "INTENT_MISMATCH"),
                                       ("expired", "INTENT_EXPIRED"), ("replay", "INTENT_REPLAY")])
async def test_E_server_parameter_expiry_and_replay_checks_via_official_sdk(java_server, case, code):
    token = java_server.command("authorize", caller="buyer-a", order="po-a1", quantity=26)["intentId"]
    args = {"orderId": "po-a1", "quantity": 26, "intentId": token}
    # Trusted fixture deliberately sends tampered wire arguments. Agent schemas never expose intentId.
    async with connect(java_server.config("buyer-a")) as client:
        if case == "replay":
            initial = java_server.command("snapshot")
            first = client.decode("purchase_order.update", await client.session.call_tool("purchase_order.update", args))
            assert first.ok, "AUTHORIZED_SETUP_FAILED"
            expected = {**initial, "po-a1": {**initial["po-a1"], "quantity": 26,
                                            "version": initial["po-a1"]["version"] + 1}}
            assert java_server.command("snapshot") == expected, "UNEXPECTED_APPROVED_WRITE_SIDE_EFFECT_STOP"
        if case == "expired":
            java_server.command("advance", seconds=61)
        before = java_server.command("snapshot")
        sent = {**args, "quantity": 27} if case == "substitution" else args
        reply = client.decode("purchase_order.update", await client.session.call_tool("purchase_order.update", sent))
    java_server.unchanged(before)
    assert not reply.ok and reply.code == code
    java_server.record("E-"+case, code=reply.code, orders_unchanged_after_denied_call=True)


async def test_authentication_failure_and_missing_header_are_real_http_401(java_server):
    before = java_server.command("snapshot")
    with pytest.raises(BoundaryError, match="MCP_AUTHENTICATION_FAILED"):
        async with connect(java_server.config(wrong=True)):
            raise AssertionError("Invalid credential accepted")
    try:
        async with (
            httpx.AsyncClient(trust_env=False, timeout=3) as http,
            streamable_http_client(java_server.endpoint, http_client=http) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            raise AssertionError("Missing authentication accepted")
    except Exception as exc:  # noqa: BLE001 -- sanitize known negative protocol response
        assert classify(exc) == "MCP_AUTHENTICATION_FAILED"
    java_server.unchanged(before)
    java_server.record("authentication", wrong_key="HTTP_401", missing_key="HTTP_401", orders_unchanged=True)


async def test_real_java_read_with_delayed_transport_times_out_without_retry(java_server):
    class DelayedTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport(retries=0)
            self.attempts = 0
        async def handle_async_request(self, request):
            body = json.loads(await request.aread()) if request.method == "POST" else {}
            response = await self.inner.handle_async_request(request)
            if body.get("method") == "tools/call":
                self.attempts += 1
                await response.aread()  # Real Java read completed; delay delivery, not authorization.
                await asyncio.sleep(1.5)
            return response
        async def aclose(self):
            await self.inner.aclose()
    before = java_server.command("snapshot")
    transport = DelayedTransport()
    async with connect(java_server.config(), transport=transport) as client:
        client.connection = replace(client.connection, timeout=.8)
        state = await run_agent(TASK, scripted(), client)
        assert state["error"] == "MCP_TIMEOUT" and state["tool_calls"] == 1
        assert not state["receipts"] and "120" not in state["answer"]
    java_server.unchanged(before)
    assert transport.attempts == 1
    java_server.record("tool-timeout", code="MCP_TIMEOUT", real_java_read=True,
                       controlled_delivery_delay=True, tool_attempts=1, orders_unchanged=True)


async def test_A_native_chat_mock_and_journal_match_real_java_audit(java_server):
    from test_experiment_a import completion

    from p3_agent.experiment_a import ModelHTTPJournal, run_a, summarize_a
    from p3_agent.models import ChatModel
    key = "synthetic-model-key"
    sent = []
    def reply(request):
        sent.append(True)
        return httpx.Response(200, json=completion(arguments='{"productId":"sku-a1"}') if len(sent) == 1
                              else completion(content="合成库存查询完成"))
    journal = ModelHTTPJournal(sensitive=[key, *java_server.secrets.values()],
                              inner=httpx.MockTransport(reply), mode="mock")
    http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False)
    model = ChatModel("https://api.deepseek.com", "deepseek-flash", key, allow_paid=True, http_client=http)
    try:
        result = await run_a(model, java_server.config(), java_server, journal)
    finally:
        await model.aclose()
    assert result["passed"] and result["model_calls"] == result["model_http_attempts"] == 2
    assert result["checks"]["java_audit_matched"] and result["checks"]["orders_unchanged"]
    assert result["checks"]["legal_inventory_receipt"] and not result["checks"]["write_tool_called"]
    assert journal.closed and http.is_closed
    assert key not in json.dumps(result) and all(s not in json.dumps(result) for s in java_server.secrets.values())
    # A real receipt alone must not pass without the matching Java audit.
    minimal = {"status": "completed", "model_calls": 2, "events": [
        {"node": "decide", "tool": "inventory.read"},
        {"node": "tool", "tool": "inventory.read", "code": "ALLOW", "request_id": result["inventory_request_ids"][0]}],
        "receipts": [{"ok": True, "tool": "inventory.read", "data": {"productId": "sku-a1", "tenant": "tenant-a", "available": 120}}]}
    assert not summarize_a(minimal, journal, {}, {}, [])["passed"]
    java_server.record("A-native-chat-mock-journal", model_transport="mock", http_attempts=2,
                       java_audit_matched=True, orders_unchanged=True)
