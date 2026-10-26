"""Single A only. Default refuses paid execution; uses the existing test-only Java fixture."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python-agent"))

from p3_agent.client import reject_sensitive
from p3_agent.contracts import BoundaryError
from p3_agent.experiment_a import ModelHTTPJournal, run_a
from p3_agent.models import ChatModel, disable_tracing


async def execute():
    # Read only P3-specific environment after the explicit paid gate in main().
    endpoint = os.getenv("P3_MODEL_BASE_URL", "").rstrip("/")
    name, key = os.getenv("P3_MODEL_NAME", ""), os.getenv("P3_MODEL_API_KEY", "")
    if endpoint != "https://api.deepseek.com" or name != "deepseek-flash" or not key:
        raise BoundaryError("A_MODEL_CONFIGURATION_REQUIRED")
    # Dev experiment only: existing trusted stdin fixture, not a new production endpoint.
    sys.path.insert(0, str(ROOT / "python-agent/tests"))
    from conftest import JavaFixture
    fixture = JavaFixture()
    journal = ModelHTTPJournal(sensitive=[key, *fixture.secrets.values()])
    http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False, timeout=10)
    model = None
    try:
        model = ChatModel(endpoint, name, key, allow_paid=True, http_client=http)
        result = await run_a(model, fixture.config("reader-a"), fixture, journal)
    finally:
        try:
            if model is not None:
                await model.aclose()
            else:
                await http.aclose()
        finally:
            fixture.close()
    result["model_client_closed"] = http.is_closed and journal.closed
    result["java_process_closed"] = fixture.process.poll() is not None
    reject_sensitive(result, journal.sensitive)
    directory = ROOT / "target/python-agent"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("A-model-" + uuid4().hex[:12] + ".json")
    with path.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"passed": result["passed"], "error": result["error"],
                      "model_calls": result["model_calls"], "model_http_attempts": result["model_http_attempts"],
                      "evidence": str(path.relative_to(ROOT))}, ensure_ascii=False))
    return 0 if result["passed"] else 1


def main():
    disable_tracing()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true", help="Requires separate explicit fee approval")
    args = parser.parse_args()
    if not args.allow_paid:
        print(json.dumps({"passed": False, "error": "PAID_MODEL_NOT_AUTHORIZED"}))
        return 2
    try:
        return asyncio.run(execute())
    except BoundaryError as exc:
        print(json.dumps({"passed": False, "error": exc.code}))
    except Exception:  # noqa: BLE001 -- no raw credential-bearing exceptions
        print(json.dumps({"passed": False, "error": "A_SETUP_OR_CONTROL_FAILED"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
