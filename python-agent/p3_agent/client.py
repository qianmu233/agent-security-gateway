"""Official MCP SDK Streamable HTTP. Identity and grants stay outside the model."""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlparse
from uuid import UUID

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from pydantic import SecretStr

from .contracts import ARGUMENTS, BoundaryError, InventoryData, OrderData, Outcome, validate_call

REASONS = {"FORBIDDEN", "INVALID_ARGUMENTS", "UNKNOWN_TOOL", "INTENT_REQUIRED", "INTENT_INVALID",
           "INTENT_EXPIRED", "INTENT_MISMATCH", "INTENT_REPLAY", "INTERNAL_ERROR"}


@dataclass(frozen=True)
class Connection:
    endpoint: str
    principal: str
    secret: SecretStr = field(repr=False)
    timeout: float = 5

    def validate(self):
        url = urlparse(self.endpoint)
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.path != "/mcp" or
                url.username or url.password or url.query or url.fragment or not url.port):
            raise BoundaryError("LOCAL_MCP_ENDPOINT_REQUIRED")
        if self.principal not in {"reader-a", "buyer-a", "buyer-b"}:
            raise BoundaryError("INVALID_TRUSTED_PRINCIPAL")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", self.secret.get_secret_value()):
            raise BoundaryError("INVALID_CREDENTIAL_CONFIGURATION")
        if not .01 <= self.timeout <= 30:
            raise BoundaryError("INVALID_CLIENT_TIMEOUT")


def reject_sensitive(value, sensitive):
    text = json.dumps(value, ensure_ascii=False, default=str)
    if (any(secret and secret in text for secret in sensitive) or
            re.search(r"\bsk-[A-Za-z0-9_-]{20,}", text) or "PRIVATE KEY-----" in text):
        raise BoundaryError("SENSITIVE_DATA_REJECTED")


def classify(exc):
    if isinstance(exc, BaseExceptionGroup):
        codes = [classify(item) for item in exc.exceptions]
        return next((code for code in codes if code != "MCP_CONNECTION_FAILED"), codes[0])
    if isinstance(exc, BoundaryError):
        return exc.code
    if isinstance(exc, httpx.HTTPStatusError):
        return {401: "MCP_AUTHENTICATION_FAILED", 403: "MCP_HTTP_FORBIDDEN",
                429: "MCP_RATE_LIMITED"}.get(exc.response.status_code, "MCP_HTTP_ERROR")
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "MCP_TIMEOUT"
    if isinstance(exc, McpError):
        # Python SDK 1.x uses HTTP 408 for its local response-wait timeout.
        return "MCP_TIMEOUT" if exc.error.code in {408, -32001} else "MCP_RPC_ERROR"
    return "MCP_CONNECTION_FAILED"


class GatewayClient:
    def __init__(self, session, connection, protocol, *, grant=None):
        self.session, self.connection, self.protocol, self.grant = session, connection, protocol, grant
        self.sensitive = [connection.secret.get_secret_value(),
                          connection.principal + "." + connection.secret.get_secret_value()]
        if grant:
            self.sensitive.append(grant.token.get_secret_value())
        self.calls = 0

    async def discover(self):
        result = await self.session.list_tools()
        names = [tool.name for tool in result.tools]
        if len(names) != 2 or set(names) != set(ARGUMENTS):
            raise BoundaryError("MCP_DISCOVERY_MISMATCH")
        for tool in result.tools:
            expected = {"productId"} if tool.name == "inventory.read" else {"orderId", "quantity", "intentId"}
            if (tool.inputSchema.get("type") != "object" or
                    set(tool.inputSchema.get("properties", {})) != expected or
                    tool.inputSchema.get("additionalProperties") is not False):
                raise BoundaryError("MCP_DISCOVERY_SCHEMA_MISMATCH")
        return names  # Remote descriptions/schemas are not blindly promoted into system messages.

    def decode(self, name, result):
        try:
            if len(result.content) != 1 or result.content[0].type != "text":
                raise ValueError()
            raw = result.content[0].text
            if len(raw) > 8192:
                raise ValueError()
            body = json.loads(raw)
            reject_sensitive(body, self.sensitive)
            UUID(body["requestId"])
            if result.isError:
                if set(body) != {"requestId", "code"} or body["code"] not in REASONS:
                    raise ValueError()
                return Outcome(name, False, body["code"], body["requestId"])
            if set(body) != {"requestId", "data"}:
                raise ValueError()
            schema = InventoryData if name == "inventory.read" else OrderData
            data = schema.model_validate(body["data"]).model_dump()
            return Outcome(name, True, "ALLOW", body["requestId"], data)
        except BoundaryError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            raise BoundaryError("INVALID_MCP_TOOL_RESULT") from None

    async def call(self, name, arguments):
        arguments = validate_call(name, arguments)
        reject_sensitive(arguments, self.sensitive)
        grant = self.grant
        if (name == "purchase_order.update" and grant and grant.principal == self.connection.principal
                and arguments == {"orderId": grant.order, "quantity": grant.quantity}):
            arguments = {**arguments, "intentId": grant.token.get_secret_value()}
        self.calls += 1  # Failed transport attempts still count; no automatic retry.
        try:
            result = await self.session.call_tool(name, arguments,
                read_timeout_seconds=timedelta(seconds=self.connection.timeout))
            outcome = self.decode(name, result)
            if outcome.ok:
                target = "productId" if name == "inventory.read" else "orderId"
                if outcome.data[target] != arguments[target]:
                    raise BoundaryError("MCP_RESULT_RESOURCE_MISMATCH")
            return outcome
        except BoundaryError:
            raise
        except Exception as exc:  # noqa: BLE001 -- sanitize the SDK/provider boundary
            raise BoundaryError(classify(exc)) from None


@asynccontextmanager
async def connect(connection, *, grant=None, transport=None):
    connection.validate()
    headers = {"X-API-Key": connection.principal + "." + connection.secret.get_secret_value()}
    body_error = None
    try:
        async with (
            httpx.AsyncClient(headers=headers, trust_env=False, follow_redirects=False,
                              timeout=connection.timeout, transport=transport) as http,
            streamable_http_client(connection.endpoint, http_client=http) as (read, write, _),
            ClientSession(read, write,
                          read_timeout_seconds=timedelta(seconds=connection.timeout)) as session,
        ):
            initialized = await session.initialize()
            client = GatewayClient(session, connection, initialized.protocolVersion, grant=grant)
            await client.discover()
            try:
                yield client
            except BaseException as exc:
                body_error = exc  # Preserve caller assertions, including unauthorized-side-effect failures.
                raise
    except asyncio.CancelledError:
        raise
    except (Exception, BaseExceptionGroup) as exc:  # noqa: BLE001 -- task-group errors can contain headers
        if body_error is not None:
            raise body_error from None
        raise BoundaryError(classify(exc)) from None
