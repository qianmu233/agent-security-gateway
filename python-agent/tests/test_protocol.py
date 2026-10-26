"""Actual official SDK over controlled transport; not the Java integration suite."""
import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from p3_agent.client import Connection, connect
from p3_agent.contracts import BoundaryError

SECRET = "synthetic_protocol_secret_0000000000000000"
INVENTORY = {"productId": "sku-a1", "tenant": "tenant-a", "available": 120,
             "note": "public synthetic note", "noteTrust": "UNTRUSTED_DATA"}


class Wire(httpx.AsyncBaseTransport):
    def __init__(self, *, status=200, error=False, data=None, delay=0):
        self.status, self.error, self.data, self.delay = status, error, data, delay
        self.events, self.closed = [], False

    async def handle_async_request(self, request):
        assert request.url.host == "127.0.0.1" and request.url.path == "/mcp"
        assert request.headers["X-API-Key"] == "reader-a." + SECRET
        if request.method == "GET":
            return httpx.Response(405)
        body = json.loads(await request.aread())
        method = body["method"]
        self.events.append({"method": method, "authenticated": True,
                            "protocol": request.headers.get("MCP-Protocol-Version")})
        if self.status != 200:
            return httpx.Response(self.status)
        if method.startswith("notifications/"):
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "synthetic-contract", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "inputSchema": {"type": "object", "additionalProperties": False,
                 "properties": {k: {"type": "string"} for k in keys}}}
                for name, keys in (("inventory.read", ["productId"]),
                                  ("purchase_order.update", ["orderId", "quantity", "intentId"]))]}
        elif method == "tools/call":
            await asyncio.sleep(self.delay)
            envelope = {"requestId": "00000000-0000-0000-0000-000000000001"}
            envelope.update({"code": "FORBIDDEN"} if self.error else {"data": self.data or INVENTORY})
            result = {"isError": self.error, "content": [{"type": "text", "text": json.dumps(envelope)}]}
        else:
            raise AssertionError("Unexpected SDK request")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    async def aclose(self):
        self.closed = True


def config(timeout=1):
    return Connection("http://127.0.0.1:12345/mcp", "reader-a", SecretStr(SECRET), timeout)


async def test_official_sdk_initialize_list_call_headers_negotiation_and_close():
    wire = Wire()
    async with connect(config(), transport=wire) as client:
        assert client.protocol == "2025-06-18"
        result = await client.call("inventory.read", {"productId": "sku-a1"})
        assert result.ok and result.data == INVENTORY and client.calls == 1
    assert wire.closed
    methods = [e["method"] for e in wire.events]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert methods.count("tools/call") == 1
    assert next(e for e in wire.events if e["method"] == "tools/call")["protocol"] == "2025-06-18"


async def test_http_200_mcp_iserror_is_denial_not_success():
    wire = Wire(error=True)
    async with connect(config(), transport=wire) as client:
        result = await client.call("inventory.read", {"productId": "sku-b1"})
        assert not result.ok and result.code == "FORBIDDEN" and result.data is None
    assert wire.closed


@pytest.mark.parametrize("status,code", [(401, "MCP_AUTHENTICATION_FAILED"),
                                       (403, "MCP_HTTP_FORBIDDEN"), (500, "MCP_HTTP_ERROR")])
async def test_http_failure_classification_without_retry(status, code):
    wire = Wire(status=status)
    with pytest.raises(BoundaryError, match=code):
        async with connect(config(), transport=wire):
            raise AssertionError("Must not connect")
    assert wire.closed and len(wire.events) == 1


@pytest.mark.parametrize("data,code", [({**INVENTORY, "available": "120"}, "INVALID_MCP_TOOL_RESULT"),
                                     ({**INVENTORY, "note": SECRET}, "SENSITIVE_DATA_REJECTED")])
async def test_invalid_or_sensitive_result_cannot_enter_model_context(data, code):
    async with connect(config(), transport=Wire(data=data)) as client:
        with pytest.raises(BoundaryError, match=code):
            await client.call("inventory.read", {"productId": "sku-a1"})


async def test_sdk_tool_timeout_is_counted_once_and_client_closes():
    wire = Wire(delay=.2)
    async with connect(config(.03), transport=wire) as client:
        with pytest.raises(BoundaryError, match="MCP_TIMEOUT"):
            await client.call("inventory.read", {"productId": "sku-a1"})
        assert client.calls == 1
    assert wire.closed and sum(e["method"] == "tools/call" for e in wire.events) == 1
