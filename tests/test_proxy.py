from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from tokenkeeper.ledger import Ledger


class UpstreamState:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = 200
        self.headers = {"Content-Type": "application/json"}
        self.body: bytes = b"{}"


class ServerHandle:
    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread) -> None:
        self.server = server
        self.thread = thread

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_server(handler: type[BaseHTTPRequestHandler]) -> ServerHandle:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return ServerHandle(server, thread)


def make_upstream_handler(state: UpstreamState) -> type[BaseHTTPRequestHandler]:
    class FakeUpstreamHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            state.calls.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers.items()),
                    "body": body.decode("utf-8"),
                }
            )
            self.send_response(state.status)
            for key, value in state.headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(state.body)))
            self.end_headers()
            self.wfile.write(state.body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return FakeUpstreamHandler


@pytest.fixture
def upstream() -> Iterator[tuple[UpstreamState, ServerHandle]]:
    state = UpstreamState()
    handle = start_server(make_upstream_handler(state))
    try:
        yield state, handle
    finally:
        handle.close()


def start_proxy(
    *,
    upstream_url: str,
    db_path: Path,
    project: str = "proxy-test",
    user: str = "tester",
    per_call_limit_usd: float | None = None,
    budget_action: str = "block",
) -> ServerHandle:
    from tokenkeeper.proxy.openai_compat import ProxyConfig, make_proxy_handler

    config = ProxyConfig(
        upstream=upstream_url,
        db_path=str(db_path),
        project=project,
        user=user,
        per_call_limit_usd=per_call_limit_usd,
        budget_action=budget_action,
    )
    return start_server(make_proxy_handler(config))


def post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer client-token",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def read_records(db_path: Path) -> list[Any]:
    with Ledger(db_path) as ledger:
        return ledger.query(limit=10)


def test_openai_compatible_non_stream_proxy_records_usage(
    tmp_path: Path, upstream: tuple[UpstreamState, ServerHandle]
) -> None:
    upstream_state, upstream_handle = upstream
    upstream_state.body = json.dumps(
        {
            "model": "deepseek-chat",
            "choices": [],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
        }
    ).encode("utf-8")
    db_path = tmp_path / "proxy.db"
    proxy = start_proxy(upstream_url=upstream_handle.url, db_path=db_path)
    try:
        status, _headers, body = post_json(
            f"{proxy.url}/v1/chat/completions",
            {"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        proxy.close()

    assert status == 200
    assert json.loads(body)["model"] == "deepseek-chat"
    assert upstream_state.calls[0]["path"] == "/v1/chat/completions"
    assert upstream_state.calls[0]["headers"]["Authorization"] == "Bearer client-token"
    records = read_records(db_path)
    assert len(records) == 1
    assert records[0].provider == "deepseek"
    assert records[0].prompt_tokens == 100
    assert records[0].completion_tokens == 50
    assert records[0].cached_tokens == 10


def test_openai_compatible_sse_stream_records_final_usage(
    tmp_path: Path, upstream: tuple[UpstreamState, ServerHandle]
) -> None:
    upstream_state, upstream_handle = upstream
    upstream_state.headers = {"Content-Type": "text/event-stream"}
    upstream_state.body = (
        b'data: {"model":"gpt-4o-mini","choices":[{"delta":{"content":"hi"}}]}\n\n'
        b'data: {"model":"gpt-4o-mini","usage":{"prompt_tokens":12,"completion_tokens":8}}\n\n'
        b"data: [DONE]\n\n"
    )
    db_path = tmp_path / "proxy.db"
    proxy = start_proxy(upstream_url=upstream_handle.url, db_path=db_path)
    try:
        status, headers, body = post_json(
            f"{proxy.url}/v1/chat/completions",
            {
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    finally:
        proxy.close()

    assert status == 200
    assert headers["Content-Type"].startswith("text/event-stream")
    assert b"data: [DONE]" in body
    records = read_records(db_path)
    assert len(records) == 1
    assert records[0].model == "gpt-4o-mini"
    assert records[0].prompt_tokens == 12
    assert records[0].completion_tokens == 8


def test_anthropic_messages_proxy_records_usage(
    tmp_path: Path, upstream: tuple[UpstreamState, ServerHandle]
) -> None:
    upstream_state, upstream_handle = upstream
    upstream_state.body = json.dumps(
        {
            "model": "claude-sonnet-4",
            "usage": {
                "input_tokens": 90,
                "output_tokens": 30,
                "cache_read_input_tokens": 5,
            },
        }
    ).encode("utf-8")
    db_path = tmp_path / "proxy.db"
    proxy = start_proxy(upstream_url=upstream_handle.url, db_path=db_path)
    try:
        status, _headers, _body = post_json(
            f"{proxy.url}/v1/messages",
            {
                "model": "claude-sonnet-4",
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    finally:
        proxy.close()

    assert status == 200
    records = read_records(db_path)
    assert len(records) == 1
    assert records[0].provider == "anthropic"
    assert records[0].prompt_tokens == 90
    assert records[0].completion_tokens == 30
    assert records[0].cached_tokens == 5


def test_upstream_error_is_preserved_and_recorded(
    tmp_path: Path, upstream: tuple[UpstreamState, ServerHandle]
) -> None:
    upstream_state, upstream_handle = upstream
    upstream_state.status = 503
    upstream_state.body = b'{"error":"upstream unavailable"}'
    db_path = tmp_path / "proxy.db"
    proxy = start_proxy(upstream_url=upstream_handle.url, db_path=db_path)
    try:
        status, _headers, body = post_json(
            f"{proxy.url}/v1/chat/completions",
            {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        proxy.close()

    assert status == 503
    assert b"upstream unavailable" in body
    records = read_records(db_path)
    assert len(records) == 1
    assert records[0].status == "error"
    assert records[0].error == "HTTP Error 503: Service Unavailable"


def test_budget_block_returns_429_without_hitting_upstream(
    tmp_path: Path, upstream: tuple[UpstreamState, ServerHandle]
) -> None:
    upstream_state, upstream_handle = upstream
    db_path = tmp_path / "proxy.db"
    proxy = start_proxy(
        upstream_url=upstream_handle.url,
        db_path=db_path,
        per_call_limit_usd=0.0,
        budget_action="block",
    )
    try:
        status, _headers, body = post_json(
            f"{proxy.url}/v1/chat/completions",
            {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        proxy.close()

    assert status == 429
    assert b"budget" in body.lower()
    assert upstream_state.calls == []
    records = read_records(db_path)
    assert len(records) == 1
    assert records[0].status == "blocked"
    assert records[0].model == "gpt-4o-mini"


def test_manual_http_record_writes_ledger(tmp_path: Path) -> None:
    db_path = tmp_path / "proxy.db"
    proxy = start_proxy(upstream_url="http://127.0.0.1:1", db_path=db_path)
    try:
        status, _headers, body = post_json(
            f"{proxy.url}/tokenkeeper/record",
            {
                "provider": "manual",
                "model": "custom-model",
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "latency_ms": 3.5,
                "status": "success",
            },
        )
    finally:
        proxy.close()

    assert status == 200
    assert json.loads(body)["recorded"] is True
    records = read_records(db_path)
    assert len(records) == 1
    assert records[0].provider == "manual"
    assert records[0].model == "custom-model"
    assert records[0].prompt_tokens == 11
    assert records[0].completion_tokens == 7


def test_proxy_cli_dispatches_runtime_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tokenkeeper import cli

    captured: dict[str, Any] = {}

    def fake_run_proxy(**kwargs: Any) -> None:
        captured.update(kwargs)

    db_path = tmp_path / "cli.db"
    monkeypatch.setattr("tokenkeeper.proxy.openai_compat.run_proxy", fake_run_proxy)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tokenkeeper",
            "proxy",
            "--upstream",
            "https://api.deepseek.com/v1",
            "--listen",
            "127.0.0.1:9999",
            "--db",
            str(db_path),
            "--project",
            "proj",
            "--user",
            "alice",
            "--upstream-auth-env",
            "DEEPSEEK_API_KEY",
            "--upstream-auth-header",
            "Authorization",
            "--per-call-limit-usd",
            "0.1",
            "--budget-action",
            "warn",
        ],
    )

    cli.main()

    assert captured == {
        "listen": "127.0.0.1:9999",
        "upstream": "https://api.deepseek.com/v1",
        "db_path": str(db_path),
        "project": "proj",
        "user": "alice",
        "upstream_auth_env": "DEEPSEEK_API_KEY",
        "upstream_auth_header": "Authorization",
        "daily_limit_usd": None,
        "monthly_limit_usd": None,
        "per_call_limit_usd": 0.1,
        "budget_action": "warn",
    }


def test_proxy_cli_help_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tokenkeeper.cli", "proxy", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--upstream" in result.stdout
    assert "--listen" in result.stdout
