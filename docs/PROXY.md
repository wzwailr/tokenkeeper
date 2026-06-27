# tokenkeeper Proxy

The proxy is the verified Phase 3 fallback for agents that cannot be monkey-patched in the current Python process but can configure a `base_url` or explicitly report usage.

## CLI

```bash
tokenkeeper proxy --upstream https://api.deepseek.com/v1 --listen 127.0.0.1:8787 --db ./tokenkeeper.db --project default --user default
```

Optional budget flags:

```bash
--daily-limit-usd 10 --monthly-limit-usd 200 --per-call-limit-usd 1 --budget-action warn
```

Use `--budget-action block` to reject requests with HTTP 429 before calling upstream. Blocked requests write a `status="blocked"` ledger record.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| `POST /v1/chat/completions` | Forwards OpenAI-compatible chat completions and records JSON or final SSE `usage` |
| `POST /chat/completions` | Same as OpenAI-compatible chat completions without `/v1` |
| `POST /v1/messages` | Forwards Anthropic messages and records input/output/cache-read usage |
| `GET /tokenkeeper/health` | Health check, no ledger write |
| `POST /tokenkeeper/record` | Manual record endpoint for any runtime that can report usage |

## Manual Record Payload

```json
{
  "provider": "manual",
  "model": "custom-model",
  "prompt_tokens": 100,
  "completion_tokens": 40,
  "cached_tokens": 0,
  "latency_ms": 1200,
  "status": "success"
}
```

`status` can be `success`, `error`, or `blocked`. Error and blocked payloads can include an `error` string.

## Auth

By default, the proxy forwards client auth headers. Use `--upstream-auth-env` and `--upstream-auth-header` to inject upstream credentials from an environment variable. API keys are not printed or persisted by tokenkeeper.

## Boundary

The proxy does not make universal silent capture possible. External agents are trackable only when they route supported HTTP traffic through this proxy, attach a callback/adapter, or actively report usage. SaaS/private/desktop agents that cannot route or report cannot be silently counted.
