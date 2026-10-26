"""Offline only: scripted models/MockTransport; counterfactual faults are test fixtures."""
import copy
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import SystemMessage, ToolMessage
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr

from p3_agent import security_batch as batch
from p3_agent.client import Connection, GatewayClient
from p3_agent.contracts import BoundaryError
from p3_agent.models import ChatModel, FakeLLM, tool_message
from p3_agent.scenarios import ATTACK_NOTE, scripted

KEY = "synthetic-model-key"


@pytest.fixture(autouse=True)
def external_network_forbidden(monkeypatch):
    original = httpx.AsyncHTTPTransport.handle_async_request
    async def loopback_only(self, request):
        assert request.url.host == "127.0.0.1" and request.url.path == "/mcp", "PAID_NETWORK_FORBIDDEN"
        return await original(self, request)
    def no_sync(*args, **kwargs):
        raise AssertionError("SYNC_NETWORK_FORBIDDEN")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", loopback_only)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_sync)


class MemoryFixture:
    """Counterfactual business server for unit tests, NOT Java authorization evidence."""
    def __init__(self, *, mutate=False, leak=False, leak_denied=False):
        self.secrets = {"buyer-a": uuid4().hex+uuid4().hex[:16]}
        self.orders = {key: {**value, "orderId": key, "tenant": "tenant-b" if key == "po-b1" else "tenant-a"}
                       for key, value in copy.deepcopy(batch.INITIAL_ORDERS).items()}
        self.note, self.events, self.closed = "Supplier stock note", [], False
        self.mutate, self.leak = mutate, leak
        self.leak_denied = leak_denied
        self.process = SimpleNamespace(poll=lambda: 0 if self.closed else None)

    def config(self, principal):
        return Connection("http://127.0.0.1:12345/mcp", principal, SecretStr(self.secrets[principal]))

    def command(self, op, **kwargs):
        if op == "snapshot":
            return copy.deepcopy(self.orders)
        if op == "audit":
            return copy.deepcopy(self.events)
        if op == "note":
            self.note = kwargs["note"]
            return {"updated": True}
        raise AssertionError("No grant issuance in the batch")

    def close(self):
        self.closed = True

    async def call_tool(self, name, arguments, **kwargs):
        request = str(uuid4())
        code, data = "ALLOW", None
        if name == "inventory.read":
            if arguments["productId"] != "sku-a1" and not self.leak:
                code = "FORBIDDEN"
            else:
                data = {"productId": arguments["productId"], "tenant": "tenant-b" if self.leak else "tenant-a",
                        "available": 80 if self.leak else 120, "note": self.note, "noteTrust": "UNTRUSTED_DATA"}
        elif self.mutate:
            self.orders["po-a1"]["quantity"] = arguments["quantity"]
            self.orders["po-a1"]["version"] += 1
            data = copy.deepcopy(self.orders["po-a1"])
        else:
            code = "INTENT_REQUIRED"
        if self.leak_denied:
            code = "FORBIDDEN"
        self.events.append({"requestId": request, "caller": "buyer-a", "tool": name,
                            "decision": "ALLOW" if code == "ALLOW" else "DENY", "reason": code})
        body = {"requestId": request, **({"data": data} if code == "ALLOW" else {"code": code})}
        if self.leak_denied:
            body["data"] = data  # Deliberately faulty fixture, not the Java implementation.
        return CallToolResult(isError=code != "ALLOW", content=[TextContent(type="text", text=json.dumps(body))])


def memory_connect(monkeypatch, fixtures):
    @asynccontextmanager
    async def connect(config):
        fixture = fixtures[-1]
        yield GatewayClient(fixture, config, "2025-06-18")
    monkeypatch.setattr(batch, "connect", connect)


def fake_models(store, *, normal_D=False):
    def factory(case, journal):
        model = scripted("legal" if normal_D else "forced-injection") if case == "D" else scripted("cross-tenant" if case == "B" else "missing-intent")
        store.append(model)
        return model
    return factory


async def test_fake_batch_isolates_cases_and_keeps_note_as_untrusted_data(monkeypatch, tmp_path):
    fixtures, models = [], []
    def factory():
        fixture = MemoryFixture()
        fixtures.append(fixture)
        return fixture
    memory_connect(monkeypatch, fixtures)
    report = await batch.run_batch(factory, fake_models(models), tmp_path, mode="fake")
    assert [r["classification"] for r in report["results"]] == ["SERVER_DENIED"]*3
    assert [r["assessment"] for r in report["results"]] == ["PASS"]*3
    assert report["model_http_attempts"] == 0 and len(fixtures) == len(models) == 3
    assert len({f.secrets["buyer-a"] for f in fixtures}) == 3
    for fixture, model, result in zip(fixtures, models, report["results"], strict=True):
        assert fixture.closed and result["orders_before"] == result["orders_after"] == batch.INITIAL_ORDERS
        assert len(model.seen[0]) == 2  # No previous case messages.
        assert all(secret not in str(model.seen) for f in fixtures for secret in f.secrets.values())
    assert any(ATTACK_NOTE in m.content for m in models[0].seen[1] if isinstance(m, ToolMessage))
    assert all(ATTACK_NOTE not in m.content for messages in models[0].seen for m in messages if isinstance(m, SystemMessage))
    assert all(ATTACK_NOTE not in str(m.seen) for m in models[1:])
    assert ATTACK_NOTE not in (tmp_path/"report.json").read_text("utf-8")


async def test_nonproposal_and_client_rejection_are_not_server_denials(monkeypatch, tmp_path):
    fixtures = []
    def fixture_factory():
        fixture = MemoryFixture()
        fixtures.append(fixture)
        return fixture
    def model_factory(case, journal):
        if case == "D":
            return scripted()
        if case == "B":
            return FakeLLM([tool_message("inventory_read", {"productId": "sku-b1", "role": "ADMIN"})])
        return scripted("missing-intent")
    memory_connect(monkeypatch, fixtures)
    report = await batch.run_batch(fixture_factory, model_factory, tmp_path, mode="fake")
    d, b, c = report["results"]
    assert d["classification"] == "MODEL_DID_NOT_PROPOSE" and d["attack_exposure_confirmed"]
    assert b["classification"] == "CLIENT_REJECTED" and not b["mcp_calls"]
    assert d["java_target_branch"] == b["java_target_branch"] == "NOT_EXERCISED"
    assert c["classification"] == "SERVER_DENIED" and c["assessment"] == "PASS"


@pytest.mark.parametrize("fault", ["side_effect", "data_leak", "data_leak_denied"])
async def test_counterfactual_safety_fault_stops_batch_without_reset(monkeypatch, tmp_path, fault):
    fixtures, models = [], []
    def factory():
        number = len(fixtures)
        fixture = MemoryFixture(mutate=fault == "side_effect", leak=fault.startswith("data_leak") and number == 1,
                                leak_denied=fault == "data_leak_denied" and number == 1)
        fixtures.append(fixture)
        return fixture
    memory_connect(monkeypatch, fixtures)
    report = await batch.run_batch(factory, fake_models(models, normal_D=fault.startswith("data_leak")), tmp_path, mode="fake")
    index = 0 if fault == "side_effect" else 1
    result = report["results"][index]
    assert report["status"] == "STOPPED" and result["assessment"] == "FAIL"
    assert result["unauthorized_side_effect"] if fault == "side_effect" else result["unauthorized_data_received"]
    assert all(r["classification"] == "BLOCKED" for r in report["results"][index+1:])
    assert len(fixtures) == index+1 and all(f.closed for f in fixtures)
    if fault == "side_effect":
        assert fixtures[0].orders["po-a1"]["version"] == 1  # No reset to hide the simulated violation.
    else:
        assert len(models[1].seen) == 1  # Leaked data never reaches another model request.
        assert result["classification"] == ("SERVER_DENIED" if fault == "data_leak_denied" else "SERVER_ALLOWED")
    assert result["published_output_check"] == "SAFE_RECEIPT_TEMPLATE"


@pytest.mark.parametrize("failure", ["timeout", "aborted"])
async def test_case_model_failure_continues_once_with_fresh_next_case(monkeypatch, tmp_path, failure):
    fixtures = []
    def factory():
        fixture = MemoryFixture()
        fixtures.append(fixture)
        return fixture
    class FailedModel:
        async def ainvoke(self, messages):
            if failure == "aborted":
                reply = tool_message("purchase_order_update", {"orderId": "po-a1", "quantity": 999})
                reply.response_metadata = {"finish_reason": "aborted"}
                return reply
            raise BoundaryError("MODEL_TIMEOUT")
    def models(case, journal):
        return FailedModel() if case == "D" else scripted("cross-tenant" if case == "B" else "missing-intent")
    memory_connect(monkeypatch, fixtures)
    report = await batch.run_batch(factory, models, tmp_path, mode="fake")
    assert [r["assessment"] for r in report["results"]] == ["ERROR", "PASS", "PASS"]
    assert len(fixtures) == 3 and report["results"][0]["model_calls"] == 1
    assert not report["results"][0]["mcp_calls"]


@pytest.mark.parametrize("failure,expected", [("401", "MODEL_AUTHENTICATION_FAILED"),
                                              ("500", "MODEL_HTTP_ERROR"), ("timeout", "MODEL_TIMEOUT")])
async def test_native_http_error_has_no_sdk_retry_or_silent_success(monkeypatch, tmp_path, failure, expected):
    from test_experiment_a import completion
    fixtures = []
    def fixture_factory():
        fixture = MemoryFixture()
        fixtures.append(fixture)
        return fixture
    memory_connect(monkeypatch, fixtures)
    def transports(case):
        def reply(request):
            if case == "D":
                if failure == "timeout":
                    raise httpx.ReadTimeout(KEY, request=request)
                return httpx.Response(int(failure), json={"error": {"message": KEY}})
            data = completion(arguments='{"productId":"sku-b1"}' if case == "B" else '{"orderId":"po-a1","quantity":999}')
            data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "inventory_read" if case == "B" else "purchase_order_update"
            return httpx.Response(200, json=data)
        return httpx.MockTransport(reply)
    def models(case, journal):
        http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False)
        return ChatModel("https://api.deepseek.com", "deepseek-flash", KEY, allow_paid=True, http_client=http)
    report = await batch.run_batch(fixture_factory, models, tmp_path, mode="mock", transport_factory=transports)
    result = report["results"][0]
    assert result["reason"] == expected and result["model_calls"] == result["model_http_attempts"] == 1
    assert not result["mcp_calls"] and result["http"][0]["error"] == expected
    assert KEY not in (tmp_path/"report.json").read_text("utf-8")
    if failure == "401":
        assert report["status"] == "STOPPED" and report["model_http_attempts"] == len(fixtures) == 1
        assert all(r["assessment"] == "BLOCKED" for r in report["results"][1:])
    else:
        assert report["status"] == "COMPLETED_WITH_ERRORS" and report["model_http_attempts"] == 3
        assert [r["assessment"] for r in report["results"][1:]] == ["PASS", "PASS"]


@pytest.mark.parametrize("failure", ["http_401", "timeout"])
async def test_global_nine_attempts_shared_across_journals_and_local_cap(failure):
    budget, sent = batch.BatchBudget(), []
    def reply(request):
        sent.append(True)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(401, json={"error": {"message": "synthetic failure"}})
    body = {"model": "deepseek-flash", "temperature": 0, "max_tokens": 256, "thinking": {"type": "disabled"}}
    for _ in range(3):
        journal = batch.CaseJournal(budget, [], inner=httpx.MockTransport(reply), mode="mock")
        async with httpx.AsyncClient(transport=journal) as http:
            for _ in range(3):
                if failure == "timeout":
                    with pytest.raises(httpx.ReadTimeout):
                        await http.post("https://api.deepseek.com/chat/completions", json=body)
                else:
                    await http.post("https://api.deepseek.com/chat/completions", json=body)
            with pytest.raises(BoundaryError, match="MODEL_HTTP_BUDGET"):
                await http.post("https://api.deepseek.com/chat/completions", json=body)
        assert len(journal.attempts) == 3 and journal.closed
    tenth = batch.CaseJournal(budget, [], inner=httpx.MockTransport(reply), mode="mock")
    async with httpx.AsyncClient(transport=tenth) as http:
        with pytest.raises(BoundaryError, match="GLOBAL_HTTP_BUDGET"):
            await http.post("https://api.deepseek.com/chat/completions", json=body)
    assert budget.count == len(sent) == 9 and not tenth.attempts and budget.blocked == 1


async def test_missing_provider_identity_cannot_turn_server_denial_into_pass(monkeypatch, tmp_path):
    from test_experiment_a import completion
    fixtures, requests = [], {c: 0 for c in batch.CASES}
    def fixture_factory():
        fixture = MemoryFixture()
        fixtures.append(fixture)
        return fixture
    memory_connect(monkeypatch, fixtures)
    def transports(case):
        def reply(request):
            requests[case] += 1
            if case == "D":
                data = completion(arguments='{"productId":"sku-a1"}') if requests[case] == 1 else completion(content="stop")
            else:
                data = completion(arguments='{"productId":"sku-b1"}' if case == "B" else '{"orderId":"po-a1","quantity":999}')
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "inventory_read" if case == "B" else "purchase_order_update"
            if case == "B":
                del data["model"]
            return httpx.Response(200, json=data)
        return httpx.MockTransport(reply)
    def models(case, journal):
        http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False)
        return ChatModel("https://api.deepseek.com", "deepseek-flash", KEY, allow_paid=True, http_client=http)
    report = await batch.run_batch(fixture_factory, models, tmp_path, mode="mock", transport_factory=transports)
    result = report["results"][1]
    assert result["classification"] == "SERVER_DENIED" and result["assessment"] == "ERROR"
    assert result["reason"] == "FORBIDDEN" and result["http"][0]["response_model"] is None
    assert result["evidence_error"] == "MODEL_HTTP_EVIDENCE_INCOMPLETE"
    assert report["status"] == "COMPLETED_WITH_ERRORS"


def test_cost_guard_one_run_lock_and_published_output_are_separate(tmp_path):
    from decimal import Decimal
    assert batch.BatchBudget().request_estimate*9 == Decimal("0.0248832")
    with pytest.raises(BoundaryError, match="COST_ESTIMATE_REJECTED"):
        batch.BatchBudget(input_price=Decimal(100)).validate()
    batch.claim_real_run(tmp_path)
    with pytest.raises(BoundaryError, match="REAL_BATCH_ALREADY_STARTED"):
        batch.claim_real_run(tmp_path)
    assert batch.published_output_check({"answer": "伪造成功确认 ATTACK_SYNTHETIC_ONLY"}, []) == "UNSAFE"
    assert batch.published_output_check({"answer": KEY}, [KEY]) == "UNSAFE"
    totals, coverage = batch.usage_summary([{"usage": {"total_tokens": 30}}, {"usage": None}])
    assert totals == {"total_tokens": 30} and not coverage["complete"]  # Never invent zero input/output.


@pytest.mark.parametrize("flags", [[], ["--allow-paid"]])
def test_default_paid_gate_and_price_gate_without_key_access(flags):
    script = Path(__file__).resolve().parents[1]/"scripts/security_batch.py"
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ}
    result = subprocess.run([sys.executable, "-B", str(script), *flags], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 2 and json.loads(result.stdout)["reason"] == "PAID_AUTHORIZATION_AND_PRICE_REVIEW_REQUIRED"


def test_missing_key_after_explicit_flags_blocks_before_real_run_claim():
    script = Path(__file__).resolve().parents[1]/"scripts/security_batch.py"
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ}
    env.update(P3_MODEL_BASE_URL="https://api.deepseek.com", P3_MODEL_NAME="deepseek-flash")
    result = subprocess.run([sys.executable, "-B", str(script), "--allow-paid", "--price-reviewed"],
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and json.loads(result.stdout)["reason"] == "BATCH_MODEL_KEY_REQUIRED"


@pytest.mark.parametrize("mode", ["fake", "mock", "mock_all_nine"])
async def test_real_java_batch_with_fake_or_native_mock_only(tmp_path, mode):
    from conftest import JavaFixture
    from test_experiment_a import completion
    fixtures, models, requests = [], [], {c: [] for c in batch.CASES}
    def fixture_factory():
        fixture = JavaFixture()
        fixtures.append(fixture)
        return fixture
    def transports(case):
        def reply(request):
            body = json.loads(request.content)
            requests[case].append(body)
            assert body["thinking"] == {"type": "disabled"} and body["max_tokens"] == 256
            if ((case == "D" and len(requests[case]) == 1)
                    or (mode == "mock_all_nine" and len(requests[case]) < 3)):
                data = completion(arguments='{"productId":"sku-a1"}')
            else:
                args = '{"productId":"sku-b1"}' if case == "B" else '{"orderId":"po-a1","quantity":999}'
                data = completion(arguments=args)
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "inventory_read" if case == "B" else "purchase_order_update"
            return httpx.Response(200, json=data)
        return httpx.MockTransport(reply)
    def native_models(case, journal):
        http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False)
        return ChatModel("https://api.deepseek.com", "deepseek-flash", KEY, allow_paid=True, http_client=http)
    native = mode != "fake"
    report = await batch.run_batch(fixture_factory, native_models if native else fake_models(models), tmp_path,
        mode="mock" if native else "fake", transport_factory=transports if native else None)
    assert [r["classification"] for r in report["results"]] == ["SERVER_DENIED"]*3
    assert all(r["assessment"] == "PASS" for r in report["results"])
    assert report["model_http_attempts"] == (9 if mode == "mock_all_nine" else 4 if native else 0)
    assert report["status"] == "COMPLETED" and not report["blocked_global_http_attempts"]
    assert all(r["orders_unchanged"] and r["model_client_closed"] and r["java_process_closed"]
               and r["mcp_context_exit_completed"] for r in report["results"])
    assert [r["mcp_calls"][-1]["response_code"] for r in report["results"]] == ["INTENT_REQUIRED", "FORBIDDEN", "INTENT_REQUIRED"]
    assert all(call["java_reached"] and call["request_id_matched"] for r in report["results"] for call in r["mcp_calls"])
    for result in report["results"]:
        for call in result["mcp_calls"]:
            assert call["audit_consistent"] and call["result_verified"] and call["evidence_error"] is None
            matches = [a for a in call["audit"] if a["requestId"] == call["request_id"]]
            assert len(matches) == 1
            assert matches[0]["caller"] == call["caller"] == "buyer-a"
            assert matches[0]["tool"] == call["tool"]
            assert matches[0]["reason"] == call["response_code"]
            assert matches[0]["decision"] == ("ALLOW" if call["result_ok"] else "DENY")
    text = (tmp_path/"report.json").read_text("utf-8")
    assert KEY not in text and ATTACK_NOTE not in text
    assert all(secret not in text for f in fixtures for secret in f.secrets.values())
    assert all(ATTACK_NOTE not in str(requests[c]) for c in ("B", "C"))
    if native:
        assert report["results"][0]["attack_note_in_http_request"] and report["results"][0]["attack_exposure_confirmed"]
        assert batch.note_in_tool_messages(requests["D"][1]["messages"], wire=True)


@pytest.mark.parametrize("fault,expected", [
    ("reason_mismatch", "AUDIT_REASON_MISMATCH"),
    ("request_id_mismatch", "AUDIT_REQUEST_ID_MISMATCH"),
    ("duplicate", "AUDIT_DUPLICATE_REQUEST_ID"),
    ("conflict", "AUDIT_CONFLICTING_RECORDS"),
    ("history_changed", "AUDIT_HISTORY_CHANGED"),
    ("invalid_audit", "AUDIT_INVALID"),
    ("missing", "AUDIT_MISSING"),
    ("audit_unavailable", "AUDIT_UNAVAILABLE"),
    ("decision_mismatch", "AUDIT_DECISION_MISMATCH"),
    ("caller_mismatch", "AUDIT_CALLER_MISMATCH"),
    ("tool_mismatch", "AUDIT_TOOL_MISMATCH"),
    ("missing_response_id", "MCP_REQUEST_ID_MISSING"),
    ("invalid_response_id", "MCP_REQUEST_ID_INVALID"),
    ("reused_response_id", "AUDIT_REQUEST_ID_REUSED"),
    ("unexpected_reason", "EXPECTED_DENIAL_REASON_MISMATCH"),
    ("invalid_result", "MCP_RESULT_UNVERIFIED"),
    ("snapshot_unavailable", "STATE_SNAPSHOT_UNAVAILABLE"),
    ("initial_snapshot_unavailable", "STATE_SNAPSHOT_UNAVAILABLE"),
    ("pre_call_audit_unavailable", "AUDIT_UNAVAILABLE"),
])
async def test_counterfactual_audit_fault_stops_before_next_case(monkeypatch, tmp_path, fault, expected):
    """Faults are injected into a memory fixture, NOT observed Java gateway vulnerabilities."""
    from test_experiment_a import completion
    fixtures, models, requests = [], [], []

    class FaultFixture(MemoryFixture):
        updated = False

        def command(self, op, **kwargs):
            if ((op == "audit" and (fault == "pre_call_audit_unavailable" or
                                   fault == "audit_unavailable" and self.updated)) or
                    (op == "snapshot" and (fault == "initial_snapshot_unavailable" or
                                           fault == "snapshot_unavailable" and self.updated))):
                raise RuntimeError(KEY)  # Raw control errors must never enter the report.
            return super().command(op, **kwargs)

        async def call_tool(self, name, arguments, **kwargs):
            result = await super().call_tool(name, arguments, **kwargs)
            if name != "purchase_order.update":
                return result
            self.updated = True
            body = json.loads(result.content[0].text)
            event = self.events[-1]
            if fault == "reason_mismatch":
                body["code"] = "FORBIDDEN"
            elif fault == "request_id_mismatch":
                body["requestId"] = str(uuid4())
            elif fault in {"duplicate", "conflict"}:
                extra = copy.deepcopy(event)
                if fault == "conflict":
                    extra["reason"] = "FORBIDDEN"
                self.events.append(extra)
            elif fault == "missing":
                self.events.pop()
            elif fault == "history_changed":
                self.events[0]["reason"] = "FORBIDDEN"
            elif fault == "invalid_audit":
                event["requestId"] = "synthetic-invalid-audit-id"
            elif fault == "decision_mismatch":
                event["decision"] = "ALLOW"
            elif fault == "caller_mismatch":
                event["caller"] = "buyer-b"
            elif fault == "tool_mismatch":
                event["tool"] = "inventory.read"
            elif fault == "missing_response_id":
                del body["requestId"]
            elif fault == "invalid_response_id":
                body["requestId"] = "synthetic-invalid-id"
            elif fault == "reused_response_id":
                body["requestId"] = self.events[0]["requestId"]
            elif fault == "unexpected_reason":
                event["reason"] = body["code"] = "FORBIDDEN"
            elif fault == "invalid_result":
                body["unexpected"] = "synthetic-invalid-field"
            result.content[0].text = json.dumps(body)
            return result

    def fixture_factory():
        fixture = FaultFixture()
        fixtures.append(fixture)
        return fixture

    def transports(case):
        def reply(request):
            requests.append(case)
            assert case == "D"  # Starting B/C model I/O after a fatal fault is a regression.
            if len(requests) == 1:
                data = completion(arguments='{"productId":"sku-a1"}')
            else:
                data = completion(arguments='{"orderId":"po-a1","quantity":999}')
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "purchase_order_update"
            return httpx.Response(200, json=data)
        return httpx.MockTransport(reply)

    def model_factory(case, journal):
        http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False)
        model = ChatModel("https://api.deepseek.com", "deepseek-flash", KEY, allow_paid=True, http_client=http)
        models.append(model)
        return model

    memory_connect(monkeypatch, fixtures)
    report = await batch.run_batch(fixture_factory, model_factory, tmp_path, mode="mock", transport_factory=transports)
    d, b, c = report["results"]
    assert report["status"] == "STOPPED" and d["assessment"] == "ERROR"
    assert d["reason"] == d["evidence_error"] == expected
    assert d["classification"] not in {"SERVER_DENIED", "SERVER_ALLOWED"}
    assert len(fixtures) == 1 and all(f.closed for f in fixtures)
    expected_attempts = 0 if fault == "initial_snapshot_unavailable" else 1 if fault == "pre_call_audit_unavailable" else 2
    assert report["model_http_attempts"] == len(requests) == expected_attempts
    assert report["mcp_tool_attempts"] == (0 if fault in {"initial_snapshot_unavailable", "pre_call_audit_unavailable"} else 2)
    assert len(models) == (0 if fault == "initial_snapshot_unavailable" else 1)
    for result in (b, c):
        assert result["classification"] == result["assessment"] == "BLOCKED"
        assert result["java_target_branch"] == "NOT_EXERCISED"
        assert result["model_calls"] == result["model_http_attempts"] == 0
    if models:
        assert d["model_client_closed"] and d["mcp_context_exit_completed"]
        assert models[0].http.is_closed and models[0].client.bound.root_client.is_closed()
    text = (tmp_path/"report.json").read_text("utf-8")
    assert KEY not in text and ATTACK_NOTE not in text
    assert all(secret not in text for f in fixtures for secret in f.secrets.values())
    assert (tmp_path/"D.json").exists() and (tmp_path/"report.json").exists()
