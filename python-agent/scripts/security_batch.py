"""Test-only D/B/C batch. --offline never reads model credentials or calls a provider."""
import argparse
import asyncio
import json
import os
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"python-agent"))

from p3_agent.contracts import BoundaryError
from p3_agent.models import ChatModel, disable_tracing
from p3_agent.security_batch import BatchBudget, claim_real_run, run_batch


def offline():
    # Do not inherit cloud-model credentials into pytest or Java. These names are not inspected.
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "P3_JAVA_HOME", "JAVA_HOME") if key in os.environ}
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    name = "batch-offline-"+uuid4().hex[:12]+".xml"
    return subprocess.run([sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider",
        "tests/test_security_batch.py", "-x", "-q", "--junitxml=../target/python-agent/"+name],
        cwd=ROOT/"python-agent", env=env, check=False).returncode


async def paid(args):
    # Entry gate and explicit price-review acknowledgment happen before any model environment read.
    budget = BatchBudget(input_price=Decimal(args.input_price), output_price=Decimal(args.output_price))
    budget.validate()
    if (os.getenv("P3_MODEL_BASE_URL", "").rstrip("/") != "https://api.deepseek.com"
            or os.getenv("P3_MODEL_NAME", "") != "deepseek-flash"):
        raise BoundaryError("BATCH_MODEL_CONFIGURATION_REQUIRED")
    key = os.getenv("P3_MODEL_API_KEY", "")
    if not key:
        raise BoundaryError("BATCH_MODEL_KEY_REQUIRED")
    budget.sensitive.append(key)
    directory = claim_real_run(ROOT/"target/python-agent")  # Exclusive permanent one-run lock.
    sys.path.insert(0, str(ROOT/"python-agent/tests"))
    from conftest import JavaFixture
    def model_factory(case, journal):
        http = httpx.AsyncClient(transport=journal, trust_env=False, follow_redirects=False, timeout=10)
        return ChatModel("https://api.deepseek.com", "deepseek-flash", key, allow_paid=True, http_client=http)
    report = await run_batch(JavaFixture, model_factory, directory, budget=budget)
    print(json.dumps({"status": report["status"], "model_http_attempts": report["model_http_attempts"],
        "results": [{k: r[k] for k in ("scenario", "classification", "assessment")} for r in report["results"]],
        "report": str((directory/"report.json").relative_to(ROOT))}, ensure_ascii=False))
    return 1 if report["status"] == "STOPPED" or any(r["assessment"] in {"ERROR", "FAIL", "BLOCKED"} for r in report["results"]) else 0


def main():
    disable_tracing()
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--offline", action="store_true")
    group.add_argument("--allow-paid", action="store_true", help="Requires separate explicit fee authorization")
    parser.add_argument("--price-reviewed", action="store_true", help="Operator rechecked current official prices/model mapping")
    parser.add_argument("--input-price", default="0.30", help="USD per million uncached input tokens")
    parser.add_argument("--output-price", default="1.20", help="USD per million output tokens")
    args = parser.parse_args()
    if args.offline:
        return offline()
    if not args.allow_paid or not args.price_reviewed:
        print(json.dumps({"status": "BLOCKED", "reason": "PAID_AUTHORIZATION_AND_PRICE_REVIEW_REQUIRED"}))
        return 2
    try:
        return asyncio.run(paid(args))
    except BoundaryError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": exc.code}))
    except (InvalidOperation, ValueError):
        print(json.dumps({"status": "BLOCKED", "reason": "INVALID_PRICE_CONFIGURATION"}))
    except Exception:  # noqa: BLE001 -- no raw credential-bearing process/SDK exception
        print(json.dumps({"status": "ERROR", "reason": "BATCH_DRIVER_ERROR"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
