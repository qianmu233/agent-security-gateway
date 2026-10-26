"""Scripted Fake LLM by default; optional native tool-calling chat adapter."""
import asyncio
import json
import logging
import os
from collections import deque
from urllib.parse import urlparse

import httpx
from langchain_core.messages import AIMessage

from .contracts import TOOL_SCHEMAS, BoundaryError


def disable_tracing():
    logging.disable(logging.CRITICAL)
    for key in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING",
                "LANGCHAIN_TRACING_V2", "LANGSMITH_OTEL_ENABLED", "DD_TRACE_ENABLED"):
        os.environ[key] = "false"
    os.environ.update(OTEL_SDK_DISABLED="true", OTEL_TRACES_EXPORTER="none",
                      OTEL_METRICS_EXPORTER="none", OTEL_LOGS_EXPORTER="none", OPENAI_LOG="off")
    from langchain_core.globals import set_debug, set_verbose
    set_debug(False)
    set_verbose(False)


def tool_message(name, arguments, number=1):
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments,
                      "id": f"call-{number}", "type": "tool_call"}])


def reject_truncated(response):
    """Do not use even syntactically valid tool arguments from an incomplete response."""
    metadata = getattr(response, "response_metadata", {}) or {}
    if (metadata.get("finish_reason") in {"length", "max_tokens", "max_output_tokens", "truncated"}
            or metadata.get("stop_reason") == "max_tokens"
            or metadata.get("status") in {"incomplete", "truncated"}
            or metadata.get("truncated") is True):
        raise BoundaryError("MODEL_OUTPUT_TRUNCATED")


class FakeLLM:
    """Uses real LangChain AIMessage contracts but no language-model inference."""
    def __init__(self, replies, *, delay=0):
        self.replies, self.delay, self.seen = deque(replies), delay, []
        self.identity = {"provider": "fake", "model": "scripted-deterministic-v1"}

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        await asyncio.sleep(self.delay)
        if not self.replies:
            raise BoundaryError("FAKE_SCRIPT_EXHAUSTED")
        return self.replies.popleft()


class ChatModel:
    def __init__(self, endpoint, model, key, *, allow_paid=False, http_client=None):
        disable_tracing()
        url = urlparse(endpoint)
        local = url.scheme == "http" and url.hostname == "127.0.0.1" and url.path.rstrip("/") == "/v1"
        if (url.username or url.password or url.query or url.fragment or not model or
                (not local and url.scheme != "https")):
            raise BoundaryError("INVALID_MODEL_CONFIGURATION")
        if not local and not allow_paid:
            raise BoundaryError("PAID_MODEL_NOT_AUTHORIZED")
        if not local and not key:
            raise BoundaryError("REMOTE_MODEL_KEY_REQUIRED")
        from langchain_openai import ChatOpenAI
        self.sensitive = [key] if key else []
        self.identity = {"provider": "local-openai-compatible" if local else "remote-openai-compatible",
                         "model": model}
        extra = {"thinking": {"type": "disabled"}} if url.hostname == "api.deepseek.com" else {}
        self.http = http_client if http_client is not None else httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=10)
        self.client = ChatOpenAI(model=model, api_key=key or "local-no-secret", base_url=endpoint,
            max_retries=0, timeout=10, temperature=0, http_async_client=self.http,
            extra_body={"max_tokens": 256, **extra}).bind_tools(TOOL_SCHEMAS)

    async def ainvoke(self, messages):
        # Conservative byte/framing bound, not the provider's exact tokenizer.
        size = sum(len(str(m.content).encode("utf-8")) for m in messages)
        size += len(json.dumps(TOOL_SCHEMAS).encode("utf-8"))
        size += sum(len(json.dumps(getattr(m, "tool_calls", [])).encode("utf-8")) for m in messages)
        if size + 1024 + 256 > 8192:
            raise BoundaryError("MODEL_INPUT_BUDGET")
        try:
            response = await self.client.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 -- no raw response or key-bearing SDK errors
            from openai import APIConnectionError, APIStatusError, APITimeoutError
            if isinstance(exc, APITimeoutError):
                code = "MODEL_TIMEOUT"
            elif isinstance(exc, APIConnectionError):
                code = "MODEL_CONNECTION_FAILED"
            elif isinstance(exc, APIStatusError):
                code = {401: "MODEL_AUTHENTICATION_FAILED", 403: "MODEL_FORBIDDEN",
                        429: "MODEL_RATE_LIMITED"}.get(exc.status_code, "MODEL_HTTP_ERROR")
            else:
                code = "INVALID_MODEL_RESPONSE"
            raise BoundaryError(code) from None
        reject_truncated(response)
        return response

    async def aclose(self):
        await self.client.bound.root_async_client.close()
        self.client.bound.root_client.close()
