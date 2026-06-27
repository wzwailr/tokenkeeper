# Tokenkeeper Final Goal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tokenkeeper honestly deliver automatic LLM usage and cost accounting for supported Python entrypoints, OpenAI-compatible domestic and international providers, common agent frameworks, and a documented proxy/manual fallback for unsupported runtimes.

**Architecture:** Use layered capture instead of claiming impossible universal interception. Layer 1 patches provider SDKs in-process. Layer 2 adapts common agent frameworks and callbacks. Layer 3 offers an OpenAI-compatible proxy or manual `guard.record()` API for non-Python, native, Rust, Node, remote, or opaque agents. All claims must map to tests, wheel smoke checks, and docs.

**Tech Stack:** Python 3.10+, SQLite, optional PostgreSQL, OpenAI SDK, Anthropic SDK, LangChain callback APIs, Streamlit, pytest, mypy, build, wheel installation smoke tests.

---

## Scope And Acceptance

The final product may claim:

- OpenAI official Python SDK automatic accounting for sync, async, and stream calls.
- OpenAI-compatible HTTP providers automatic accounting when used through the OpenAI Python SDK, including DeepSeek, Qwen/DashScope compatible mode, Moonshot, MiniMax, Zhipu-compatible endpoints, and other providers that return OpenAI-style `usage`.
- Anthropic official Python SDK automatic accounting for sync, async, and stream calls after class-level patching is fixed.
- Agent frameworks automatic accounting only when they call a supported SDK in the same Python process or use a tokenkeeper-provided framework adapter.
- Unsupported agents can still be tracked through explicit instrumentation, importing a tokenkeeper callback, pointing traffic to a tokenkeeper proxy, or syncing a known local state database.

The final product must not claim:

- Automatic tracking for every possible model, runtime, language, desktop app, SaaS agent, browser extension, Rust binary, Node process, or private gateway with zero integration.
- Accurate cost for every model without either built-in pricing, provider-returned cost, or user-provided pricing.
- Provider coverage where the provider does not return usage and tokenkeeper does not tokenize or infer usage with tested provider-specific logic.

## File Structure

- `tokenkeeper/_version.py`: Single source of package version.
- `tokenkeeper/capture.py`: Shared capture primitives for request metadata, response usage, cost calculation, and ledger writes.
- `tokenkeeper/integrations/openai_compat.py`: OpenAI SDK sync, async, and stream patching.
- `tokenkeeper/integrations/anthropic.py`: Anthropic SDK class-level sync, async, and stream patching.
- `tokenkeeper/integrations/langchain.py`: LangChain callback handler.
- `tokenkeeper/proxy/openai_compat.py`: Optional OpenAI-compatible local proxy for unsupported runtimes.
- `tokenkeeper/dashboard/app.py`: Streamlit dashboard.
- `tokenkeeper/cli.py`: CLI commands for version, info, dashboard, proxy, and diagnostics.
- `tests/test_packaging.py`: Version, package data, wheel content, and CLI smoke tests.
- `tests/test_openai_capture.py`: Fake OpenAI SDK capture tests.
- `tests/test_anthropic_capture.py`: Fake Anthropic SDK capture tests.
- `tests/test_agent_frameworks.py`: LangChain and framework adapter tests.
- `tests/test_proxy.py`: OpenAI-compatible proxy request/response accounting tests.
- `tests/test_dashboard_smoke.py`: Dashboard import and seeded DB smoke tests.
- `docs/CAPTURE_MATRIX.md`: Truthful support matrix by runtime, SDK, framework, and provider.
- `README.md`, `ROADMAP.md`, `SECURITY.md`, `docs/ARCHITECTURE.md`: Updated claims and boundaries.

---

### Task 1: Define Truthful Capture Matrix

**Files:**
- Create: `docs/CAPTURE_MATRIX.md`
- Modify: `README.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Write the support matrix document**

Create `docs/CAPTURE_MATRIX.md` with this structure:

```markdown
# tokenkeeper Capture Matrix

## Strong Automatic Capture

| Entry point | Runtime | Requirement | Status target |
| --- | --- | --- | --- |
| OpenAI Python SDK `chat.completions.create` | Same Python process | `guard.install(auto_patch_openai=True)` | Tested sync/async/stream |
| OpenAI-compatible provider through OpenAI Python SDK | Same Python process | Provider returns OpenAI-style `usage` | Tested with fake provider responses |
| Anthropic Python SDK `messages.create` | Same Python process | `guard.install(auto_patch_openai=True)` | Tested sync/async/stream |

## Adapter-Based Capture

| Framework | Requirement | Status target |
| --- | --- | --- |
| LangChain | `TokenKeeperCallbackHandler` passed to model callbacks | Tested callback ledger write |
| Custom Python agent | Import `guard` and call `guard.install()` or `guard.record()` | Tested manual path |

## Proxy Or Sync Capture

| Scenario | Requirement | Status target |
| --- | --- | --- |
| Node/Rust/native/desktop agent using OpenAI-compatible HTTP | Configure base URL to tokenkeeper proxy | Tested proxy accounting |
| Hermes local app | Sync known state DB format | Tested fixture DB sync |

## Not Automatically Capturable

tokenkeeper cannot silently observe traffic from another process, another language runtime, a SaaS-hosted agent, encrypted traffic, a provider SDK that does not expose usage, or a desktop app that does not route through tokenkeeper. Those cases need a proxy, callback, manual record call, provider export, or local state sync.
```

- [ ] **Step 2: Update README wording**

Replace universal wording with:

```markdown
tokenkeeper automatically records calls made through supported Python SDKs and adapters. For agents outside the current Python process, use the OpenAI-compatible proxy, a framework callback, or manual `guard.record()`.
```

- [ ] **Step 3: Update ROADMAP statuses**

Use these status labels:

```markdown
- [x] Core SQLite ledger
- [x] Pricing table validation
- [ ] Wheel-installed dashboard smoke test
- [ ] OpenAI sync/async/stream capture tests
- [ ] Anthropic sync/async/stream capture tests
- [ ] LangChain callback write test
- [ ] OpenAI-compatible proxy
- [ ] PostgreSQL integration test
```

- [ ] **Step 4: Verify docs**

Run:

```powershell
rg -n "<broad-claim-patterns>" README.md ROADMAP.md docs
```

Expected: every remaining broad claim is followed by a concrete supported entrypoint or fallback path.

- [ ] **Step 5: Commit**

```powershell
git add README.md ROADMAP.md docs/CAPTURE_MATRIX.md
git commit -m "docs: define truthful capture matrix"
```

---

### Task 2: Fix Packaging And Version Truth

**Files:**
- Create: `tokenkeeper/_version.py`
- Modify: `tokenkeeper/__init__.py`
- Modify: `pyproject.toml`
- Modify: `tokenkeeper/cli.py`
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Write failing packaging tests**

Add `tests/test_packaging.py`:

```python
from __future__ import annotations

import importlib.metadata as metadata
import subprocess
import sys
import zipfile
from pathlib import Path

import tokenkeeper


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_version_matches_distribution_metadata() -> None:
    assert tokenkeeper.__version__ == metadata.version("tokenkeeper-ai")


def test_dashboard_package_is_in_built_wheel() -> None:
    subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=ROOT, check=True)
    wheel = sorted((ROOT / "dist").glob("tokenkeeper_ai-*.whl"))[-1]
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
    assert "tokenkeeper/dashboard/app.py" in names
    assert "tokenkeeper/dashboard/__init__.py" in names


def test_cli_version_uses_runtime_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tokenkeeper.cli", "version"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert result.stdout.strip() == f"tokenkeeper {tokenkeeper.__version__}"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_packaging.py -v
```

Expected: FAIL because runtime version is `0.1.0` and dashboard is missing from the wheel.

- [ ] **Step 3: Add version source**

Create `tokenkeeper/_version.py`:

```python
from __future__ import annotations

__version__ = "0.3.0a0"
```

Modify `tokenkeeper/__init__.py`:

```python
from ._version import __version__
```

Remove the old literal:

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Fix package discovery**

Replace explicit packages in `pyproject.toml`:

```toml
[tool.setuptools.packages.find]
include = ["tokenkeeper*"]
```

Remove:

```toml
[tool.setuptools]
packages = ["tokenkeeper", "tokenkeeper.integrations"]
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_packaging.py -v
python -m build --wheel
```

Expected: tests pass and built wheel includes `tokenkeeper/dashboard/app.py`.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml tokenkeeper/__init__.py tokenkeeper/_version.py tests/test_packaging.py
git commit -m "fix: package dashboard and align versions"
```

---

### Task 3: Extract Shared Capture Primitives

**Files:**
- Create: `tokenkeeper/capture.py`
- Test: `tests/test_capture.py`

- [ ] **Step 1: Write capture tests**

Create `tests/test_capture.py`:

```python
from __future__ import annotations

import time

from tokenkeeper.capture import Usage, record_success
from tokenkeeper.ledger import Ledger


def test_record_success_writes_costed_call(tmp_path) -> None:
    ledger = Ledger(tmp_path / "calls.db")
    usage = Usage(prompt_tokens=1000, completion_tokens=500, cached_tokens=0)

    rowid = record_success(
        ledger=ledger,
        project="proj",
        user="alice",
        provider="openai",
        model="gpt-4o",
        usage=usage,
        latency_ms=12.5,
        timestamp=time.time(),
    )

    assert rowid is not None
    calls = ledger.query(project="proj")
    assert len(calls) == 1
    assert calls[0].user == "alice"
    assert calls[0].provider == "openai"
    assert calls[0].model == "gpt-4o"
    assert calls[0].prompt_tokens == 1000
    assert calls[0].completion_tokens == 500
    assert calls[0].cost_usd > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_capture.py -v
```

Expected: FAIL because `tokenkeeper.capture` does not exist.

- [ ] **Step 3: Implement capture primitives**

Create `tokenkeeper/capture.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tokenkeeper.ledger import CallRecord, Ledger
from tokenkeeper.pricing import calculate_cost


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0


def record_success(
    *,
    ledger: Ledger,
    project: str,
    user: str,
    provider: str,
    model: str,
    usage: Usage,
    latency_ms: float,
    timestamp: float,
) -> Optional[int]:
    cost = calculate_cost(
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_tokens=usage.cached_tokens,
    )
    return ledger.record(
        CallRecord(
            timestamp=timestamp,
            project=project,
            user=user,
            provider=provider,
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cached_tokens=usage.cached_tokens,
            cost_usd=cost.cost_usd,
            cost_cny=cost.cost_cny,
            latency_ms=latency_ms,
            status="success",
        )
    )
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_capture.py tests/test_basic.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tokenkeeper/capture.py tests/test_capture.py
git commit -m "refactor: add shared capture primitives"
```

---

### Task 4: Make OpenAI Capture Actually Tested

**Files:**
- Modify: `tokenkeeper/integrations/openai_compat.py`
- Test: `tests/test_openai_capture.py`

- [ ] **Step 1: Write fake sync and stream tests**

Create `tests/test_openai_capture.py`:

```python
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from openai.resources.chat import completions as chat_completions

from tokenkeeper import guard


def teardown_function() -> None:
    if guard.is_installed():
        guard.uninstall()


def test_openai_sync_create_records_usage(monkeypatch) -> None:
    original = chat_completions.Completions.create

    def fake_create(self, *args, **kwargs):
        return SimpleNamespace(
            model="gpt-4o",
            usage=SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=500,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
        )

    monkeypatch.setattr(chat_completions.Completions, "create", fake_create)
    with tempfile.TemporaryDirectory() as tmp:
        guard.install(db_path=os.path.join(tmp, "calls.db"), project="proj", user="u")
        resource = object.__new__(chat_completions.Completions)
        chat_completions.Completions.create(
            resource,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hello"}],
        )
        calls = guard.ledger().query()

    assert len(calls) == 1
    assert calls[0].provider == "openai"
    assert calls[0].model == "gpt-4o"
    assert calls[0].prompt_tokens == 1000
    chat_completions.Completions.create = original


def test_openai_stream_create_records_final_usage(monkeypatch) -> None:
    def fake_create(self, *args, **kwargs):
        assert kwargs["stream_options"]["include_usage"] is True
        yield SimpleNamespace(
            model="gpt-4o-mini",
            usage=None,
            choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"))],
        )
        yield SimpleNamespace(
            model="gpt-4o-mini",
            usage=SimpleNamespace(
                prompt_tokens=300,
                completion_tokens=100,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
            choices=[],
        )

    monkeypatch.setattr(chat_completions.Completions, "create", fake_create)
    with tempfile.TemporaryDirectory() as tmp:
        guard.install(db_path=os.path.join(tmp, "calls.db"), project="proj", user="u")
        resource = object.__new__(chat_completions.Completions)
        stream = chat_completions.Completions.create(
            resource,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
        )
        list(stream)
        calls = guard.ledger().query()

    assert len(calls) == 1
    assert calls[0].model == "gpt-4o-mini"
    assert calls[0].prompt_tokens == 300
```

- [ ] **Step 2: Run test to verify failures**

Run:

```powershell
python -m pytest tests/test_openai_capture.py -v
```

Expected: FAIL until patching preserves fake originals and stream accounting is stable.

- [ ] **Step 3: Implement minimal fixes**

Modify `openai_compat.py` so sync and async keep separate originals:

```python
_original_create: Optional[Any] = None
_original_async_create: Optional[Any] = None
```

In `install()`:

```python
_original_create = Completions.create
Completions.create = _wrap_create
_original_async_create = AsyncCompletions.create
AsyncCompletions.create = _wrap_async_create
```

In `uninstall()`:

```python
Completions.create = _original_create
AsyncCompletions.create = _original_async_create
```

Use `record_success()` from `tokenkeeper.capture` in sync and stream paths.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_openai_capture.py tests/test_basic.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tokenkeeper/integrations/openai_compat.py tests/test_openai_capture.py
git commit -m "fix: verify openai capture paths"
```

---

### Task 5: Fix Anthropic Class-Level Capture

**Files:**
- Modify: `tokenkeeper/integrations/anthropic.py`
- Test: `tests/test_anthropic_capture.py`

- [ ] **Step 1: Write failing class patch test**

Create `tests/test_anthropic_capture.py`:

```python
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from anthropic.resources.messages import Messages

from tokenkeeper import guard


def teardown_function() -> None:
    if guard.is_installed():
        guard.uninstall()


def test_anthropic_class_method_is_patched(monkeypatch) -> None:
    original = Messages.create

    def fake_create(self, *args, **kwargs):
        return SimpleNamespace(
            model="claude-sonnet-4",
            usage=SimpleNamespace(
                input_tokens=200,
                output_tokens=50,
                cache_read_input_tokens=0,
            ),
        )

    monkeypatch.setattr(Messages, "create", fake_create)
    with tempfile.TemporaryDirectory() as tmp:
        guard.install(db_path=os.path.join(tmp, "calls.db"), project="proj", user="u")
        assert Messages.create is not fake_create
        resource = object.__new__(Messages)
        Messages.create(resource, model="claude-sonnet-4", max_tokens=20, messages=[])
        calls = guard.ledger().query()

    assert len(calls) == 1
    assert calls[0].provider == "anthropic"
    assert calls[0].model == "claude-sonnet-4"
    assert calls[0].prompt_tokens == 200
    Messages.create = original
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_anthropic_capture.py -v
```

Expected: FAIL because current implementation patches `anthropic.Anthropic().messages.create` on an instance instead of the `Messages` class.

- [ ] **Step 3: Patch the SDK class**

Modify `tokenkeeper/integrations/anthropic.py`:

```python
from anthropic.resources.messages import Messages
from anthropic.resources.messages import AsyncMessages

_original_anthropic_create = Messages.create
Messages.create = _wrap_create
_original_async_anthropic_create = AsyncMessages.create
AsyncMessages.create = _wrap_async_create
```

In `uninstall()` restore both class methods.

- [ ] **Step 4: Record through shared capture**

Use:

```python
from tokenkeeper.capture import Usage, record_success
```

Create `Usage(input_tokens, output_tokens, cached_tokens)` from Anthropic response usage and call `record_success(provider="anthropic", ...)`.

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_anthropic_capture.py tests/test_integration_ext.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add tokenkeeper/integrations/anthropic.py tests/test_anthropic_capture.py
git commit -m "fix: patch anthropic class methods"
```

---

### Task 6: Make Agent Framework Coverage Honest

**Files:**
- Modify: `tokenkeeper/integrations/langchain.py`
- Test: `tests/test_agent_frameworks.py`
- Modify: `README.md`

- [ ] **Step 1: Write LangChain ledger write test without requiring LangChain runtime**

Create `tests/test_agent_frameworks.py`:

```python
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from tokenkeeper import guard
from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler


def teardown_function() -> None:
    if guard.is_installed():
        guard.uninstall()


def test_langchain_callback_records_usage(monkeypatch) -> None:
    monkeypatch.setattr("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    with tempfile.TemporaryDirectory() as tmp:
        guard.install(db_path=os.path.join(tmp, "calls.db"), project="lc", user="u", auto_patch_openai=False)
        handler = TokenKeeperCallbackHandler(project="lc", user="u", auto_install=False)
        handler._start_times["run-1"] = 1.0
        response = SimpleNamespace(
            llm_output={
                "model_name": "gpt-4o-mini",
                "token_usage": {
                    "prompt_tokens": 500,
                    "completion_tokens": 200,
                    "total_tokens": 700,
                },
            }
        )
        handler.on_llm_end(response, run_id="run-1")
        calls = guard.ledger().query()

    assert len(calls) == 1
    assert calls[0].project == "lc"
    assert calls[0].model == "gpt-4o-mini"
```

- [ ] **Step 2: Run test to verify behavior**

Run:

```powershell
python -m pytest tests/test_agent_frameworks.py -v
```

Expected: PASS after import and `HAS_LANGCHAIN` handling are stable. If it fails due to inheritance at import time, split callback logic into a dependency-free base helper.

- [ ] **Step 3: Document agent framework boundary**

Add to README:

```markdown
Agent frameworks are tracked when they either call a supported SDK in the same Python process or pass tokenkeeper's callback/handler. Agents running in another process, another language, or a hosted SaaS environment need the proxy or manual record path.
```

- [ ] **Step 4: Commit**

```powershell
git add tokenkeeper/integrations/langchain.py tests/test_agent_frameworks.py README.md
git commit -m "test: verify langchain callback accounting"
```

---

### Task 7: Add OpenAI-Compatible Proxy Fallback

**Files:**
- Create: `tokenkeeper/proxy/__init__.py`
- Create: `tokenkeeper/proxy/openai_compat.py`
- Modify: `tokenkeeper/cli.py`
- Test: `tests/test_proxy.py`

- [ ] **Step 1: Write proxy accounting test**

Create `tests/test_proxy.py`:

```python
from __future__ import annotations

from tokenkeeper.proxy.openai_compat import extract_openai_usage


def test_extract_openai_usage_from_response_json() -> None:
    payload = {
        "model": "gpt-4o-mini",
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 4,
            "total_tokens": 16,
            "prompt_tokens_details": {"cached_tokens": 3},
        },
    }
    model, usage = extract_openai_usage(payload, fallback_model="requested")
    assert model == "gpt-4o-mini"
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 4
    assert usage.cached_tokens == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_proxy.py -v
```

Expected: FAIL because proxy module does not exist.

- [ ] **Step 3: Implement proxy extraction core**

Create `tokenkeeper/proxy/openai_compat.py`:

```python
from __future__ import annotations

from typing import Any

from tokenkeeper.capture import Usage


def extract_openai_usage(payload: dict[str, Any], fallback_model: str) -> tuple[str, Usage]:
    usage_payload = payload.get("usage") or {}
    details = usage_payload.get("prompt_tokens_details") or {}
    return (
        str(payload.get("model") or fallback_model),
        Usage(
            prompt_tokens=int(usage_payload.get("prompt_tokens") or 0),
            completion_tokens=int(usage_payload.get("completion_tokens") or 0),
            cached_tokens=int(details.get("cached_tokens") or 0),
        ),
    )
```

- [ ] **Step 4: Implement minimal forwarding proxy**

Extend `tokenkeeper/proxy/openai_compat.py`:

```python
from __future__ import annotations

import json
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tokenkeeper.capture import Usage, record_success
from tokenkeeper.ledger import Ledger


def extract_openai_usage(payload: dict[str, Any], fallback_model: str) -> tuple[str, Usage]:
    usage_payload = payload.get("usage") or {}
    details = usage_payload.get("prompt_tokens_details") or {}
    return (
        str(payload.get("model") or fallback_model),
        Usage(
            prompt_tokens=int(usage_payload.get("prompt_tokens") or 0),
            completion_tokens=int(usage_payload.get("completion_tokens") or 0),
            cached_tokens=int(details.get("cached_tokens") or 0),
        ),
    )


class ProxyConfig:
    def __init__(self, upstream: str, db_path: str, project: str, user: str) -> None:
        self.upstream = upstream.rstrip("/")
        self.ledger = Ledger(db_path)
        self.project = project
        self.user = user


def make_handler(config: ProxyConfig):
    class OpenAICompatProxyHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            started = time.time()
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            request_payload = json.loads(body.decode("utf-8")) if body else {}
            requested_model = str(request_payload.get("model") or "unknown")
            upstream_url = f"{config.upstream}{self.path}"
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "content-length"}
            }
            req = urllib.request.Request(
                upstream_url,
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                response_body = resp.read()
                status_code = resp.status
                response_headers = dict(resp.headers.items())

            self.send_response(status_code)
            for key, value in response_headers.items():
                if key.lower() not in {"transfer-encoding", "content-encoding"}:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response_body)

            try:
                response_payload = json.loads(response_body.decode("utf-8"))
                actual_model, usage = extract_openai_usage(response_payload, requested_model)
                record_success(
                    ledger=config.ledger,
                    project=config.project,
                    user=config.user,
                    provider="openai-compatible-proxy",
                    model=actual_model,
                    usage=usage,
                    latency_ms=(time.time() - started) * 1000,
                    timestamp=time.time(),
                )
            except Exception:
                return

    return OpenAICompatProxyHandler


def run_proxy(*, listen: str, upstream: str, db_path: str, project: str, user: str) -> None:
    host, raw_port = listen.rsplit(":", 1)
    server = ThreadingHTTPServer(
        (host, int(raw_port)),
        make_handler(ProxyConfig(upstream=upstream, db_path=db_path, project=project, user=user)),
    )
    server.serve_forever()
```

- [ ] **Step 5: Add CLI command**

Add `tokenkeeper proxy` subcommand in `tokenkeeper/cli.py`:

```python
proxy_parser = subparsers.add_parser("proxy", help="start OpenAI-compatible accounting proxy")
proxy_parser.add_argument("--listen", default="127.0.0.1:8787")
proxy_parser.add_argument("--upstream", required=True)
proxy_parser.add_argument("--db", default="./tokenkeeper.db")
proxy_parser.add_argument("--project", default="default")
proxy_parser.add_argument("--user", default="default")
```

Implement command dispatch:

```python
elif args.command == "proxy":
    from tokenkeeper.proxy.openai_compat import run_proxy

    run_proxy(
        listen=args.listen,
        upstream=args.upstream,
        db_path=args.db,
        project=args.project,
        user=args.user,
    )
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_proxy.py -v
python -m compileall -q tokenkeeper/proxy tokenkeeper/cli.py
```

Expected: proxy extraction test passes and proxy modules compile.

- [ ] **Step 7: Commit**

```powershell
git add tokenkeeper/proxy tests/test_proxy.py tokenkeeper/cli.py
git commit -m "feat: add proxy accounting core"
```

---

### Task 8: Make Dashboard A Real Release Feature

**Files:**
- Modify: `tokenkeeper/dashboard/app.py`
- Modify: `tokenkeeper/cli.py`
- Test: `tests/test_dashboard_smoke.py`

- [ ] **Step 1: Write dashboard import test**

Create `tests/test_dashboard_smoke.py`:

```python
from __future__ import annotations

import importlib


def test_dashboard_module_imports() -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    assert callable(module._get_db_path)
```

- [ ] **Step 2: Run test to verify current failure**

Run:

```powershell
python -m pytest tests/test_dashboard_smoke.py -v
```

Expected: FAIL if Streamlit import side effects or missing `Any` cause import problems.

- [ ] **Step 3: Fix dashboard imports**

Add:

```python
from typing import Any
```

Remove runtime deletion of `tokenkeeper` modules from `sys.modules`. Keep dashboard import stable and deterministic.

- [ ] **Step 4: Verify dashboard package smoke**

Run:

```powershell
python -m pytest tests/test_dashboard_smoke.py -v
python -m build --wheel
```

Expected: tests pass and wheel includes dashboard files.

- [ ] **Step 5: Commit**

```powershell
git add tokenkeeper/dashboard/app.py tokenkeeper/cli.py tests/test_dashboard_smoke.py
git commit -m "fix: make dashboard import and packaging stable"
```

---

### Task 9: Restore Quality Gates

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/tests.yml`
- Modify: `scripts/validate_pricing.py`

- [ ] **Step 1: Update mypy Python target**

Change:

```toml
python_version = "3.9"
```

to:

```toml
python_version = "3.10"
```

- [ ] **Step 2: Fix Windows pricing validator output**

In `scripts/validate_pricing.py`, replace emoji-only status with ASCII-safe prefixes:

```python
print("[OK] no errors")
print("[OK] no warnings")
```

- [ ] **Step 3: Run quality commands**

Run:

```powershell
python -m compileall -q tokenkeeper tests scripts
python -m pytest tests/ -v --tb=short --cov=tokenkeeper --cov-report=term-missing
python scripts/validate_pricing.py
python -m mypy tokenkeeper
python -m build --wheel
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit**

```powershell
git add pyproject.toml .github/workflows/tests.yml scripts/validate_pricing.py
git commit -m "ci: restore release quality gates"
```

---

### Task 10: Final Documentation And Release Audit

**Files:**
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update SECURITY network claim**

Replace:

```markdown
tokenkeeper core accounting does not upload call records
```

with:

```markdown
tokenkeeper core accounting does not upload call records. If webhook alerting or the proxy is configured, tokenkeeper makes the network requests required by those explicitly enabled features.
```

- [ ] **Step 2: Update README final scope**

Add:

```markdown
## Capture scope

tokenkeeper supports automatic accounting for supported SDKs and adapters. Universal capture across every possible agent is not technically possible without an integration point. For unsupported runtimes, use the OpenAI-compatible proxy or manual `guard.record()`.
```

- [ ] **Step 3: Run final audit commands**

Run:

```powershell
git status --short --branch
python -m compileall -q tokenkeeper tests scripts
python -m pytest tests/ -v --tb=short --cov=tokenkeeper --cov-report=term-missing
python scripts/validate_pricing.py
python -m mypy tokenkeeper
python -m build --wheel
```

Expected: clean branch except intentional docs/code changes before commit, then all verification commands exit 0.

- [ ] **Step 4: Commit**

```powershell
git add README.md SECURITY.md docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: align release claims with verified capture scope"
```

---

## Self-Review

- Spec coverage: The plan covers package truth, SDK interception, domestic and international OpenAI-compatible providers, Anthropic, agent framework adapters, unsupported runtime proxy/manual fallback, dashboard, CI, and docs.
- Placeholder scan: No task contains deferred implementation language as an acceptance substitute; the proxy task includes a minimal forwarding server and accounting extraction path.
- Type consistency: `Usage`, `record_success`, provider names, ledger fields, and CLI commands are named consistently across tasks.
