"""Only generated test credentials; trusted stdin is never given to the Agent."""
import json
import os
import queue
import re
import secrets
import subprocess
import threading
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr

from p3_agent.client import Connection
from p3_agent.models import disable_tracing

ROOT = Path(__file__).resolve().parents[2]


def java17_home():
    """Use explicit environment configuration; never embed a developer's home directory."""
    configured = os.getenv("P3_JAVA_HOME") or os.getenv("JAVA_HOME")
    message = "Set P3_JAVA_HOME or JAVA_HOME to a real JDK 17 directory"
    if not configured:
        raise AssertionError(message)
    home = Path(configured)
    try:
        valid = ((home / "bin/java.exe").is_file() and
                 re.search(r'^JAVA_VERSION="17[.\"]', (home / "release").read_text("utf-8"), re.MULTILINE))
    except OSError:
        valid = False
    if not valid:
        raise AssertionError(message)
    return home


@pytest.fixture(autouse=True)
def no_tracing():
    disable_tracing()


class JavaFixture:
    def __init__(self):
        self.secrets = {p: secrets.token_hex(24) for p in ("reader-a", "buyer-a", "buyer-b")}
        names = {"reader-a": "P3_READER_A_SECRET", "buyer-a": "P3_BUYER_A_SECRET", "buyer-b": "P3_BUYER_B_SECRET"}
        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ}
        env.update({names[p]: value for p, value in self.secrets.items()})
        java_home = java17_home()
        classpath = (ROOT / "target/python-agent-classpath.txt").read_text("utf-8").strip()
        classpath = os.pathsep.join([str(ROOT / "target/test-classes"), str(ROOT / "target/classes"), classpath])
        self.process = subprocess.Popen([str(java_home / "bin/java.exe"), "-cp", classpath,
            "dev.p3.gateway.support.PythonGatewayHarness", "--server.address=127.0.0.1",
            "--server.port=0", "--debug=false", "--logging.level.root=OFF",
            "--p3.intent-console.enabled=false"], cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.responses = queue.Queue()
        self.records = []
        self.run_id = uuid.uuid4().hex[:12]
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        try:
            ready = self.responses.get(timeout=30)
            assert ready["fixture"] == "ready", "JAVA_FIXTURE_NOT_READY"
            self.endpoint = f"http://127.0.0.1:{ready['port']}/mcp"
        except (AssertionError, queue.Empty, OSError):
            self.close()
            raise AssertionError("JAVA_FIXTURE_START_FAILED") from None

    def read(self):
        for line in self.process.stdout:
            if line.lstrip().startswith("{"):
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if data.get("fixture") in {"ready", "reply", "error"}:
                    self.responses.put(data)
        self.responses.put({"fixture": "exited"})

    def command(self, op, **kwargs):
        with self.lock:
            self.process.stdin.write(json.dumps({"op": op, **kwargs}) + "\n")
            self.process.stdin.flush()
            reply = self.responses.get(timeout=10)
            assert reply["fixture"] == "reply", "TRUSTED_FIXTURE_COMMAND_FAILED"
            return reply["value"]

    def config(self, principal="reader-a", *, wrong=False):
        return Connection(self.endpoint, principal, SecretStr("0"*48 if wrong else self.secrets[principal]))

    def unchanged(self, before):
        # A failure is a hard stop in the documented pytest -x acceptance command.
        assert self.command("snapshot") == before, "UNAUTHORIZED_SIDE_EFFECT_FAILURE_STOP"

    def record(self, name, **result):
        self.records.append({"case": name, **result})

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.reader.join(5)
        if self.records:
            directory = ROOT / "target/python-agent"
            directory.mkdir(exist_ok=True)
            text = json.dumps({"model": "fake-scripted", "real_mcp_java_process": True,
                               "cases": self.records}, ensure_ascii=False, indent=2)
            assert not any(value in text for value in self.secrets.values())
            (directory / ("cross-language-" + self.run_id + ".json")).write_text(text, "utf-8")


@pytest.fixture(scope="module")
def java_server():
    fixture = JavaFixture()
    try:
        yield fixture
    finally:
        fixture.close()
