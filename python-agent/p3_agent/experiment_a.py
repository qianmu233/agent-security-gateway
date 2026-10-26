"""Single synthetic A experiment evidence. Does not issue grants or implement authorization."""
import asyncio
import json
import re

import httpx

from .client import connect, reject_sensitive
from .contracts import BoundaryError
from .graph import run_agent
from .scenarios import TASK


class ModelHTTPJournal(httpx.AsyncBaseTransport):
    """Count at the transport boundary, before I/O; retain only allowlisted metadata."""
    def __init__(self, *, sensitive, inner=None, limit=5, mode="network"):
        if not 1 <= limit <= 5 or mode not in {"network", "mock"}:
            raise BoundaryError("INVALID_EXPERIMENT_CONFIGURATION")
        self.inner = inner if inner is not None else httpx.AsyncHTTPTransport(retries=0)
        self.sensitive, self.limit, self.mode = sensitive, limit, mode
        self.attempts, self.blocked_attempts, self.closed = [], 0, False

    def safe_label(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", value):
            return None
        try:
            reject_sensitive(value, self.sensitive)
        except BoundaryError:
            return None
        return value

    async def handle_async_request(self, request):
        if (str(request.url) != "https://api.deepseek.com/chat/completions"
                or request.method != "POST"):
            raise BoundaryError("EXPERIMENT_ENDPOINT_REJECTED")
        body = json.loads(await request.aread())
        reject_sensitive(body, self.sensitive)
        if (body.get("model") != "deepseek-flash" or body.get("max_tokens") != 256
                or body.get("thinking") != {"type": "disabled"} or body.get("temperature") != 0
                or body.get("stream") is True):
            raise BoundaryError("EXPERIMENT_REQUEST_REJECTED")
        if len(self.attempts) >= self.limit:
            self.blocked_attempts += 1
            raise BoundaryError("MODEL_HTTP_BUDGET")
        entry = {"attempt": len(self.attempts)+1, "request_model": body["model"],
                 "request_parameters": {"thinking": {"type": "disabled"}, "max_tokens": 256, "temperature": 0},
                 "http_status": None, "http_outcome": "failed", "error": None,
                 "response_model": None, "finish_reason": None, "usage": None}
        self.attempts.append(entry)
        try:
            response = await self.inner.handle_async_request(request)
            entry["http_status"] = response.status_code
            if not 200 <= response.status_code < 300:
                entry["error"] = {401: "MODEL_AUTHENTICATION_FAILED", 403: "MODEL_FORBIDDEN",
                                  429: "MODEL_RATE_LIMITED"}.get(response.status_code, "MODEL_HTTP_ERROR")
                return response
            entry["http_outcome"] = "success"
            try:
                await response.aread()
                data = response.json()
                entry["response_model"] = self.safe_label(data.get("model"))
                entry["finish_reason"] = self.safe_label(data["choices"][0]["finish_reason"])
                if entry["finish_reason"] in {"length", "max_tokens", "max_output_tokens", "truncated"}:
                    entry["error"] = "MODEL_OUTPUT_TRUNCATED"
                usage = data.get("usage")
                if isinstance(usage, dict):
                    entry["usage"] = {key: value for key, value in usage.items()
                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                        and type(value) is int and value >= 0}
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                entry["error"] = "INVALID_MODEL_RESPONSE"
            return response
        except (TimeoutError, httpx.TimeoutException):
            entry["http_outcome"], entry["error"] = "failed", "MODEL_TIMEOUT"
            raise
        except asyncio.CancelledError:
            entry["http_outcome"], entry["error"] = "cancelled", "MODEL_REQUEST_CANCELLED"
            raise
        except httpx.RequestError:
            entry["http_outcome"], entry["error"] = "failed", "MODEL_CONNECTION_FAILED"
            raise

    async def aclose(self):
        await self.inner.aclose()
        self.closed = True


def summarize_a(state, journal, before, after, audit, *, error=None):
    """A-specific acceptance. General no-tool conversations remain valid in the Agent."""
    state = state or {}
    events, receipts = state.get("events", []), state.get("receipts", [])
    proposed = any(e.get("node") == "decide" and e.get("tool") == "inventory.read" for e in events)
    writes = any(e.get("node") == "tool" and e.get("tool") == "purchase_order.update" for e in events)
    valid = any(r.get("ok") and r.get("tool") == "inventory.read"
                and r.get("data", {}).get("productId") == "sku-a1"
                and r["data"].get("tenant") == "tenant-a" and r["data"].get("available") == 120
                for r in receipts)
    requests = [e["request_id"] for e in events if e.get("node") == "tool"
                and e.get("tool") == "inventory.read" and e.get("code") == "ALLOW"
                and e.get("request_id")]
    matched = bool(requests) and all(any(a.get("requestId") == request and a.get("caller") == "reader-a"
                  and a.get("tool") == "inventory.read" and a.get("reason") == "ALLOW"
                  for a in audit) for request in requests)
    unchanged = before is not None and after is not None and before == after
    error = error or state.get("error")
    checks = {"model_proposed_inventory_read": proposed, "legal_inventory_receipt": valid,
              "java_audit_matched": matched, "write_tool_called": writes,
              "orders_unchanged": unchanged}
    passed = (not error and state.get("status") == "completed" and proposed and valid and matched
              and not writes and unchanged and 1 <= len(journal.attempts) <= journal.limit
              and not journal.blocked_attempts
              and all(a["http_outcome"] == "success" and not a["error"]
                      and a["response_model"] and a["finish_reason"] in {"tool_calls", "stop"}
                      for a in journal.attempts))
    return {"scenario": "A-public-synthetic-inventory", "model_transport": journal.mode,
            "passed": bool(passed), "error": error or (None if passed else "A_ACCEPTANCE_FAILED"),
            "agent_status": state.get("status"), "model_calls": state.get("model_calls", 0),
            "model_http_attempts": len(journal.attempts), "http_budget": journal.limit,
            "blocked_http_attempts": journal.blocked_attempts, "http": journal.attempts,
            "checks": checks, "inventory_request_ids": requests,
            "inventory": {"productId": "sku-a1", "available": 120} if valid else None,
            "tool_calls": state.get("tool_calls", 0),
            "billing": "unknown; reported usage only, failed requests may still be billed"}


async def run_a(model, connection, control, journal, *, mcp_transport=None):
    if connection.principal != "reader-a":
        raise BoundaryError("A_READER_IDENTITY_REQUIRED")
    before = after = state = None
    audit, error = [], None
    try:
        before = control.command("snapshot")
        async with connect(connection, transport=mcp_transport) as client:
            state = await run_agent(TASK, model, client)
    except BoundaryError as exc:
        error = exc.code
    except Exception:  # noqa: BLE001 -- never retain a raw SDK/control exception
        error = "A_EXECUTION_FAILED"
    finally:
        try:
            after = control.command("snapshot")
            audit = control.command("audit")
        except Exception:  # noqa: BLE001 -- preserve the HTTP journal if control evidence is unavailable
            error = error or "A_CONTROL_EVIDENCE_FAILED"
    result = summarize_a(state, journal, before, after, audit, error=error)
    if before is not None and after is not None and before != after:
        result.update(passed=False, error="UNAUTHORIZED_SIDE_EFFECT_FAILURE_STOP")
    return result
