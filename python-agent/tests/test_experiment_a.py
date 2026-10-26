"""Local MockTransport only. No provider requests or production credentials."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from test_protocol import SECRET, Wire, config

from p3_agent.contracts import BoundaryError
from p3_agent.experiment_a import ModelHTTPJournal, run_a, summarize_a
from p3_agent.graph import Limits, run_agent
from p3_agent.models import ChatModel

KEY = "synthetic-model-key"


def completion(*, content=None, arguments=None, finish=None):
    message = {"role": "assistant", "content": content}
    if arguments is not None:
        message["tool_calls"] = [{"id": "offline-call", "type": "function", "function": {
            "name": "inventory_read", "arguments": arguments}}]
    return {"id": "offline", "object": "chat.completion", "created": 0,
            "model": "synthetic-provider-version", "choices": [{"index": 0,
            "finish_reason": finish or ("tool_calls" if arguments is not None else "stop"), "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}


class Control:
    def command(self, op):
        return {} if op == "snapshot" else []


async def exercise(reply):
    journal = ModelHTTPJournal(sensitive=[KEY, SECRET], inner=httpx.MockTransport(reply), mode="mock")
    http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False)
    model = ChatModel("https://api.deepseek.com", "deepseek-flash", KEY, allow_paid=True, http_client=http)
    try:
        evidence = await run_a(model, config(), Control(), journal, mcp_transport=Wire())
    finally:
        await model.aclose()
    assert journal.closed and http.is_closed and model.client.bound.root_client.is_closed()
    assert KEY not in json.dumps(evidence) and SECRET not in json.dumps(evidence)
    return evidence


async def test_deepseek_non_thinking_wire_and_normal_no_receipt_fails_A_only():
    seen = []
    def reply(request):
        body = json.loads(request.content)
        seen.append(body)
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert body["thinking"] == {"type": "disabled"} and body["max_tokens"] == 256
        assert body["temperature"] == 0
        for tool in body["tools"]:
            assert not {"intentId", "principal", "tenant", "role"} & tool["function"]["parameters"]["properties"].keys()
        assert KEY not in json.dumps(body) and SECRET not in json.dumps(body)
        return httpx.Response(200, json=completion(content="公开合成无工具对话"))
    result = await exercise(reply)
    assert not result["passed"] and result["agent_status"] == "completed"
    assert not result["checks"]["legal_inventory_receipt"] and len(seen) == 1
    assert result["http"][0]["request_model"] == "deepseek-flash"
    assert result["http"][0]["response_model"] == "synthetic-provider-version"
    assert result["http"][0]["usage"]["total_tokens"] == 30  # Synthetic, not real token consumption.


@pytest.mark.parametrize("case,expected", [
    ("401", "MODEL_AUTHENTICATION_FAILED"), ("429", "MODEL_RATE_LIMITED"),
    ("500", "MODEL_HTTP_ERROR"), ("timeout", "MODEL_TIMEOUT"),
    ("cancel", "MODEL_TIMEOUT"), ("json", "INVALID_MODEL_RESPONSE"),
    ("provider_error", "INVALID_MODEL_RESPONSE"),
    ("truncated_text", "MODEL_OUTPUT_TRUNCATED"), ("truncated_tool", "MODEL_OUTPUT_TRUNCATED"),
])
async def test_failure_attempt_is_recorded_once_without_retry(case, expected):
    def response(request):
        if case.isdigit():
            return httpx.Response(int(case), json={"error": {"message": KEY}})
        if case == "timeout":
            raise httpx.ReadTimeout(KEY, request=request)
        if case == "json":
            return httpx.Response(200, text="{broken")
        if case == "provider_error":
            return httpx.Response(200, json={"error": {"message": KEY}})
        return httpx.Response(200, json=completion(content="partial", finish="length") if case == "truncated_text"
            else completion(arguments='{"productId":"sku-a1"}', finish="length"))
    async def slow(request):
        await asyncio.sleep(20)
        return response(request)
    # Shorten only the graph's deadline in this test; HTTP cancellation still crosses the journal.
    if case == "cancel":
        from unittest.mock import patch
        async def bounded(*args, **kwargs):
            return await run_agent(*args, **kwargs, limits=Limits(step_seconds=.02))
        with patch("p3_agent.experiment_a.run_agent", bounded):
            result = await exercise(slow)
    else:
        result = await exercise(response)
    assert not result["passed"] and result["error"] == expected
    assert result["model_calls"] == result["model_http_attempts"] == 1 and result["tool_calls"] == 0
    assert result["http"][0]["error"] in {expected, "MODEL_REQUEST_CANCELLED"}


async def test_http_attempt_cap_prevents_second_send_and_omits_unsafe_metadata():
    sends = []
    def reply(request):
        sends.append(True)
        data = completion(content="normal")
        data["model"] = KEY
        return httpx.Response(200, json=data)
    journal = ModelHTTPJournal(sensitive=[KEY], inner=httpx.MockTransport(reply), limit=1, mode="mock")
    async with httpx.AsyncClient(transport=journal) as http:
        body = {"model": "deepseek-flash", "max_tokens": 256, "temperature": 0, "thinking": {"type": "disabled"}}
        await http.post("https://api.deepseek.com/chat/completions", json=body)
        with pytest.raises(BoundaryError, match="MODEL_HTTP_BUDGET"):
            await http.post("https://api.deepseek.com/chat/completions", json=body)
    assert len(sends) == len(journal.attempts) == 1 and journal.blocked_attempts == 1 and journal.closed
    assert journal.attempts[0]["response_model"] is None and KEY not in json.dumps(journal.attempts)
    # Summary does not invent HTTP attempts for an application attempt with no I/O.
    empty = ModelHTTPJournal(sensitive=[], inner=httpx.MockTransport(reply), mode="mock")
    evidence = summarize_a({"model_calls": 1}, empty, {}, {}, [])
    assert evidence["model_calls"] == 1 and evidence["model_http_attempts"] == 0
    await empty.aclose()


def test_script_default_paid_gate_never_reads_key_or_starts_java():
    script = Path(__file__).resolve().parents[1] / "scripts/experiment_a.py"
    result = subprocess.run([sys.executable, "-B", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 2 and json.loads(result.stdout)["error"] == "PAID_MODEL_NOT_AUTHORIZED"
