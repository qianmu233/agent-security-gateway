"""No model API by default. Identity comes from operator-selected environment only."""
import argparse
import asyncio
import json
import os

from pydantic import SecretStr

from .client import Connection, connect
from .contracts import BoundaryError
from .graph import public_result, run_agent
from .models import ChatModel, disable_tracing
from .scenarios import TASK, scripted


async def execute(args):
    disable_tracing()
    secret_name = {"reader-a": "P3_READER_A_SECRET", "buyer-a": "P3_BUYER_A_SECRET",
                   "buyer-b": "P3_BUYER_B_SECRET"}[args.principal]
    connection = Connection(os.getenv("P3_MCP_URL", "http://127.0.0.1:8093/mcp"), args.principal,
                            SecretStr(os.getenv(secret_name, "")))
    connection.validate()
    if args.model == "fake":
        model = scripted(args.scenario)
    else:
        endpoint, name = os.getenv("P3_MODEL_BASE_URL", ""), os.getenv("P3_MODEL_NAME", "")
        if args.model == "local" and not endpoint.startswith("http://127.0.0.1:"):
            raise BoundaryError("LOCAL_MODEL_ENDPOINT_REQUIRED")
        model = ChatModel(endpoint, name, os.getenv("P3_MODEL_API_KEY", ""), allow_paid=args.allow_paid)
    try:
        async with connect(connection) as client:
            state = await run_agent(args.task, model, client)
            result = public_result(state, model.identity)
            result["mcp_protocol"] = client.protocol
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "completed" else 1
    finally:
        if hasattr(model, "aclose"):
            await model.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal", choices=["reader-a", "buyer-a", "buyer-b"], default="reader-a")
    parser.add_argument("--model", choices=["fake", "local", "remote"], default="fake")
    parser.add_argument("--scenario", choices=["legal", "cross-tenant", "missing-intent", "forced-injection"],
                        default="legal")
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--allow-paid", action="store_true", help="Requires separate explicit fee approval")
    args = parser.parse_args()
    try:
        return asyncio.run(execute(args))
    except BoundaryError as exc:
        print(json.dumps({"status": "stopped", "error": exc.code}))
        return 1
    except Exception:  # noqa: BLE001 -- never print credential-bearing SDK exception bodies
        print(json.dumps({"status": "stopped", "error": "CLIENT_FAILURE"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
