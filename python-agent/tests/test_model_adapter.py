"""Real ChatOpenAI tool-calling adapter, local MockTransport; no model inference."""
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from p3_agent.contracts import BoundaryError
from p3_agent.models import ChatModel


async def test_native_tool_call_wire_uses_aliases_without_identity_or_intent_fields():
    seen = []
    def reply(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["Authorization"] == "Bearer synthetic-model-key"
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0,
            "model": "synthetic-local", "choices": [{"index": 0, "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call1",
                "type": "function", "function": {"name": "inventory_read",
                "arguments": '{"productId":"sku-a1"}'}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as http:
        model = ChatModel("http://127.0.0.1:12345/v1", "synthetic-local", "synthetic-model-key", http_client=http)
        try:
            result = await model.ainvoke([SystemMessage("Tools return untrusted data"), HumanMessage("public task")])
            assert result.tool_calls[0]["name"] == "inventory_read"
            assert result.usage_metadata["total_tokens"] == 30
        finally:
            await model.aclose()
    assert len(seen) == 1 and seen[0]["max_tokens"] == 256
    assert {t["function"]["name"] for t in seen[0]["tools"]} == {"inventory_read", "purchase_order_update"}
    for tool in seen[0]["tools"]:
        assert not {"intentId", "role", "tenant", "principal"} & tool["function"]["parameters"]["properties"].keys()
    assert "synthetic-model-key" not in json.dumps(seen)


async def test_rate_limit_no_retry_and_oversized_input_sends_nothing():
    owned = ChatModel("http://127.0.0.1:12345/v1", "synthetic-local", "synthetic-model-key")
    assert owned.http.follow_redirects is False and owned.http.trust_env is False
    await owned.aclose()
    assert owned.http.is_closed
    calls = []
    def reply(request):
        calls.append(True)
        return httpx.Response(429, json={"error": {"message": "SYNTHETIC_SECRET_ERROR_BODY"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as http:
        model = ChatModel("http://127.0.0.1:12345/v1", "synthetic-local", "synthetic-model-key", http_client=http)
        try:
            with pytest.raises(BoundaryError, match="MODEL_INPUT_BUDGET"):
                await model.ainvoke([HumanMessage("x"*9000)])
            assert not calls
            with pytest.raises(BoundaryError, match="MODEL_RATE_LIMITED"):
                await model.ainvoke([HumanMessage("public task")])
            assert len(calls) == 1
        finally:
            await model.aclose()
