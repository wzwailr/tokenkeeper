"""OpenAI-compatible HTTP proxy with tokenkeeper accounting."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlsplit

from tokenkeeper.capture import Usage, record_error, record_success
from tokenkeeper.guard import Budget, BudgetExceededError, Guard
from tokenkeeper.ledger import CallRecord, Ledger
from tokenkeeper.pricing import calculate_cost

__all__ = [
    "ProxyConfig",
    "make_proxy_handler",
    "run_proxy",
    "extract_anthropic_usage",
    "extract_openai_usage",
]


@dataclass(frozen=True)
class ProxyConfig:
    upstream: str
    db_path: str
    project: str = "default"
    user: str = "default"
    upstream_auth_env: Optional[str] = None
    upstream_auth_header: str = "Authorization"
    daily_limit_usd: Optional[float] = None
    monthly_limit_usd: Optional[float] = None
    per_call_limit_usd: Optional[float] = None
    budget_action: str = "block"


def extract_openai_usage(
    payload: dict[str, Any], requested_model: str
) -> tuple[str, Usage]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return str(payload.get("model") or requested_model), Usage()

    details = usage.get("prompt_tokens_details")
    cached_tokens = 0
    if isinstance(details, dict):
        cached_tokens = int(details.get("cached_tokens") or 0)
    return (
        str(payload.get("model") or requested_model),
        Usage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cached_tokens=cached_tokens,
        ),
    )


def extract_anthropic_usage(
    payload: dict[str, Any], requested_model: str
) -> tuple[str, Usage]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return str(payload.get("model") or requested_model), Usage()
    return (
        str(payload.get("model") or requested_model),
        Usage(
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
            cached_tokens=int(usage.get("cache_read_input_tokens") or 0),
        ),
    )


def make_proxy_handler(config: ProxyConfig) -> type[BaseHTTPRequestHandler]:
    class TokenKeeperProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            if self.path == "/tokenkeeper/health":
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path == "/tokenkeeper/record":
                self._handle_manual_record()
                return
            if _is_forwarded_path(self.path):
                self._handle_forward()
                return
            self._send_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle_manual_record(self) -> None:
            started = time.time()
            try:
                payload = self._read_json()
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return

            model = str(payload.get("model") or "unknown")
            provider = str(payload.get("provider") or "manual")
            status = str(payload.get("status") or "success")
            prompt_tokens = int(payload.get("prompt_tokens") or 0)
            completion_tokens = int(payload.get("completion_tokens") or 0)
            cached_tokens = int(payload.get("cached_tokens") or 0)
            latency_ms = float(
                payload.get("latency_ms") or ((time.time() - started) * 1000)
            )

            with Ledger(config.db_path) as ledger:
                if status == "error":
                    record_error(
                        ledger=ledger,
                        provider=provider,
                        model=model,
                        prompt_tokens=prompt_tokens,
                        latency_ms=latency_ms,
                        project=config.project,
                        user=config.user,
                        error=str(payload.get("error") or "manual error"),
                    )
                elif status == "blocked":
                    _record_blocked(
                        ledger,
                        provider=provider,
                        model=model,
                        project=config.project,
                        user=config.user,
                        latency_ms=latency_ms,
                        error=str(payload.get("error") or "blocked"),
                    )
                else:
                    record_success(
                        ledger=ledger,
                        provider=provider,
                        model=model,
                        usage=Usage(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            cached_tokens=cached_tokens,
                        ),
                        latency_ms=latency_ms,
                        project=config.project,
                        user=config.user,
                    )
            self._send_json(200, {"recorded": True})

        def _handle_forward(self) -> None:
            started = time.time()
            request_body = self._read_body()
            requested_model, prompt_tokens = _request_metadata(request_body)

            with Ledger(config.db_path) as ledger:
                try:
                    _check_budget(config, ledger, requested_model, prompt_tokens)
                except BudgetExceededError as exc:
                    _record_blocked(
                        ledger,
                        provider=_provider_for_path(self.path),
                        model=requested_model,
                        project=config.project,
                        user=config.user,
                        latency_ms=(time.time() - started) * 1000,
                        error=exc,
                    )
                    self._send_json(429, {"error": "budget exceeded"})
                    return

            upstream_request = urllib.request.Request(
                _upstream_url(config.upstream, self.path),
                data=request_body,
                headers=self._forward_headers(len(request_body)),
                method="POST",
            )

            try:
                with urllib.request.urlopen(upstream_request, timeout=60) as response:
                    response_body = response.read()
                    response_headers = dict(response.headers.items())
                    status = response.status
            except urllib.error.HTTPError as exc:
                response_body = exc.read()
                response_headers = dict(exc.headers.items())
                status = exc.code
                with Ledger(config.db_path) as ledger:
                    record_error(
                        ledger=ledger,
                        provider=_provider_for_path(self.path),
                        model=requested_model,
                        prompt_tokens=prompt_tokens,
                        latency_ms=(time.time() - started) * 1000,
                        project=config.project,
                        user=config.user,
                        error=exc,
                    )
                self._send_bytes(status, response_body, response_headers)
                return

            self._record_forward_success(
                response_body=response_body,
                requested_model=requested_model,
                started=started,
            )
            self._send_bytes(status, response_body, response_headers)

        def _record_forward_success(
            self, *, response_body: bytes, requested_model: str, started: float
        ) -> None:
            model = requested_model
            usage = Usage()
            if _is_openai_path(self.path) and _is_sse_response(response_body):
                model, usage = _extract_openai_sse_usage(response_body, requested_model)
            else:
                try:
                    payload = json.loads(response_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {}
                if _is_anthropic_path(self.path) and isinstance(payload, dict):
                    model, usage = extract_anthropic_usage(payload, requested_model)
                elif isinstance(payload, dict):
                    model, usage = extract_openai_usage(payload, requested_model)

            with Ledger(config.db_path) as ledger:
                record_success(
                    ledger=ledger,
                    provider=_provider_for_path(self.path),
                    model=model,
                    usage=usage,
                    latency_ms=(time.time() - started) * 1000,
                    project=config.project,
                    user=config.user,
                )

        def _forward_headers(self, body_length: int) -> dict[str, str]:
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "content-length", "connection"}
            }
            headers["Content-Length"] = str(body_length)
            override = _upstream_auth_value(config)
            if override is not None:
                headers[config.upstream_auth_header] = override
            return headers

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(length)

        def _read_json(self) -> dict[str, Any]:
            body = self._read_body()
            try:
                payload = json.loads(body.decode("utf-8") if body else "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid JSON body") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._send_bytes(status, body, {"Content-Type": "application/json"})

        def _send_bytes(
            self, status: int, body: bytes, headers: dict[str, str]
        ) -> None:
            self.send_response(status)
            sent_content_type = False
            for key, value in headers.items():
                lower_key = key.lower()
                if lower_key in {
                    "content-length",
                    "connection",
                    "transfer-encoding",
                    "server",
                    "date",
                }:
                    continue
                if lower_key == "content-type":
                    sent_content_type = True
                self.send_header(key, value)
            if not sent_content_type:
                self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return TokenKeeperProxyHandler


def run_proxy(
    *,
    listen: str,
    upstream: str,
    db_path: str,
    project: str,
    user: str,
    upstream_auth_env: Optional[str] = None,
    upstream_auth_header: str = "Authorization",
    daily_limit_usd: Optional[float] = None,
    monthly_limit_usd: Optional[float] = None,
    per_call_limit_usd: Optional[float] = None,
    budget_action: str = "block",
) -> None:
    host, raw_port = listen.rsplit(":", 1)
    config = ProxyConfig(
        upstream=upstream,
        db_path=db_path,
        project=project,
        user=user,
        upstream_auth_env=upstream_auth_env,
        upstream_auth_header=upstream_auth_header,
        daily_limit_usd=daily_limit_usd,
        monthly_limit_usd=monthly_limit_usd,
        per_call_limit_usd=per_call_limit_usd,
        budget_action=budget_action,
    )
    server = ThreadingHTTPServer(
        (host, int(raw_port)),
        make_proxy_handler(config),
    )
    print(f"tokenkeeper proxy listening on http://{listen}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _request_metadata(body: bytes) -> tuple[str, int]:
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "unknown", 0
    if not isinstance(payload, dict):
        return "unknown", 0
    model = str(payload.get("model") or "unknown")
    messages = payload.get("messages")
    return model, _estimate_prompt_tokens(messages)


def _estimate_prompt_tokens(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    total_chars = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total_chars += len(str(part.get("text", "")))
    return total_chars // 3


def _check_budget(
    config: ProxyConfig, ledger: Ledger, model: str, prompt_tokens: int
) -> None:
    if (
        config.daily_limit_usd is None
        and config.monthly_limit_usd is None
        and config.per_call_limit_usd is None
    ):
        return
    guard = Guard(ledger)
    guard.set_budget(
        Budget(
            scope="global",
            scope_key=None,
            daily_limit_usd=config.daily_limit_usd,
            monthly_limit_usd=config.monthly_limit_usd,
            per_call_limit_usd=config.per_call_limit_usd,
            action=config.budget_action,
        )
    )
    estimated_cost = calculate_cost(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=500,
        cached_tokens=0,
    ).cost_usd
    guard.check(
        estimated_cost=estimated_cost,
        project=config.project,
        user=config.user,
    )


def _record_blocked(
    ledger: Ledger,
    *,
    provider: str,
    model: str,
    project: str,
    user: str,
    latency_ms: float,
    error: BaseException | str,
) -> None:
    ledger.record(
        CallRecord(
            timestamp=time.time(),
            project=project,
            user=user,
            provider=provider,
            model=model or "unknown",
            prompt_tokens=0,
            completion_tokens=0,
            cached_tokens=0,
            cost_usd=0.0,
            cost_cny=0.0,
            latency_ms=latency_ms,
            status="blocked",
            error=str(error),
        )
    )


def _extract_openai_sse_usage(body: bytes, requested_model: str) -> tuple[str, Usage]:
    model = requested_model
    usage = Usage()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            continue
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("model"):
            model = str(payload["model"])
        if payload.get("usage"):
            model, usage = extract_openai_usage(payload, model)
    return model, usage


def _is_sse_response(body: bytes) -> bool:
    return any(line.strip().startswith(b"data:") for line in body.splitlines())


def _upstream_url(upstream: str, request_path: str) -> str:
    base = upstream.rstrip("/")
    path = request_path
    base_path = urlsplit(base).path.rstrip("/")
    if base_path.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return f"{base}{path}"


def _upstream_auth_value(config: ProxyConfig) -> Optional[str]:
    if not config.upstream_auth_env:
        return None
    value = os.environ.get(config.upstream_auth_env)
    if not value:
        return None
    if (
        config.upstream_auth_header.lower() == "authorization"
        and not value.lower().startswith("bearer ")
    ):
        return f"Bearer {value}"
    return value


def _is_openai_path(path: str) -> bool:
    return path.endswith("/chat/completions")


def _is_anthropic_path(path: str) -> bool:
    return path.endswith("/v1/messages")


def _is_forwarded_path(path: str) -> bool:
    return _is_openai_path(path) or _is_anthropic_path(path)


def _provider_for_path(path: str) -> str:
    if _is_anthropic_path(path):
        return "anthropic"
    return "openai-compatible-proxy"
