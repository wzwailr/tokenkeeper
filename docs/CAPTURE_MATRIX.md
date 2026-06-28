# tokenkeeper Capture Matrix

This matrix is the source of truth for what tokenkeeper can honestly claim today and what still needs a tested integration. Proxy usage details live in `docs/PROXY.md`.

## Verified In Phase 1

| Capability | Status | Evidence |
| --- | --- | --- |
| SQLite ledger, pricing, budget checks | Verified | Existing unit tests |
| Package version consistency | Verified | `tests/test_packaging.py` |
| Dashboard included in wheel | Verified | `tests/test_packaging.py` |
| Dashboard import smoke | Verified | `tests/test_dashboard_smoke.py` |
| Pricing table validation | Verified | `scripts/validate_pricing.py` |

## Verified In Phase 2

| Entry point | Runtime requirement | Evidence |
| --- | --- | --- |
| OpenAI Python SDK sync calls | Same Python process, `guard.install()` called | `tests/test_openai_capture.py` |
| OpenAI Python SDK async calls | Same Python process, `guard.install()` called | `tests/test_openai_capture.py` |
| OpenAI Python SDK stream calls | Same Python process, provider returns final `usage` | `tests/test_openai_capture.py` |
| OpenAI-compatible providers | Called through OpenAI Python SDK and returns OpenAI-style `usage` | `tests/test_openai_capture.py` |
| Anthropic Python SDK sync/async/stream | Same Python process, class-level patch works | `tests/test_anthropic_capture.py` |
| LangChain callback | Callback explicitly attached to the model/agent | `tests/test_langchain.py` |

## Verified In Phase 3

| Entry point | Runtime requirement | Evidence |
| --- | --- | --- |
| OpenAI-compatible HTTP proxy, non-stream | Agent can set `base_url` to `tokenkeeper proxy` and upstream returns OpenAI-style JSON | `tests/test_proxy.py` |
| OpenAI-compatible HTTP proxy, SSE stream | Agent can set `base_url` to `tokenkeeper proxy` and upstream stream includes final `usage` | `tests/test_proxy.py` |
| Anthropic HTTP proxy `/v1/messages` | Agent can route Anthropic messages requests through `tokenkeeper proxy` | `tests/test_proxy.py` |
| Manual HTTP record endpoint | Agent can `POST /tokenkeeper/record` with explicit token/cost metadata | `tests/test_proxy.py` |
| Proxy budget block | Proxy is configured with budget limits and `--budget-action block` | `tests/test_proxy.py` |
| One-command proxy connector | User runs `tokenkeeper connect proxy` and configures the printed `base_url` | `tests/test_cli_connect.py` |

## Verified Local State Sync

| Entry point | Runtime requirement | Evidence |
| --- | --- | --- |
| Hermes local state database sync | Hermes has written sessions and token usage into a readable local `state.db` | `tests/test_hermes_connector.py`, `tests/test_cli_connect.py`, `tests/test_dashboard_smoke.py` |
| One-command Hermes connector | User runs `tokenkeeper connect hermes` with the default or explicit Hermes `state.db` path | `tests/test_cli_connect.py` |
| Installation diagnostics | User runs `tokenkeeper doctor` before connecting Hermes or proxy | `tests/test_cli_connect.py` |

## Target Automatic Capture

| Entry point | Runtime requirement | Status |
| --- | --- | --- |
| OpenAI Python SDK sync calls | Same Python process, `guard.install()` called | Verified |
| OpenAI Python SDK async calls | Same Python process, `guard.install()` called | Verified |
| OpenAI Python SDK stream calls | Same Python process, provider returns final `usage` | Verified |
| OpenAI-compatible providers | Called through OpenAI Python SDK and returns OpenAI-style `usage` | Verified |
| Anthropic Python SDK sync/async/stream | Same Python process, class-level patch works | Verified |
| LangChain callback | Callback explicitly attached to the model/agent | Verified |
| External agents through local proxy | Agent can configure `base_url` to `tokenkeeper proxy` | Verified |
| Any runtime through manual HTTP record | Agent can explicitly `POST /tokenkeeper/record` | Verified |
| Hermes Desktop local state sync | Hermes has written session usage to a readable `state.db` | Verified |

## Fallback Capture Paths

| Scenario | Required integration | Status |
| --- | --- | --- |
| Non-Python agent, Node/Rust/Go app, desktop app, or separate process | Route OpenAI-compatible or Anthropic HTTP traffic through `tokenkeeper proxy` | Verified for tested HTTP paths |
| Any runtime that cannot route traffic but can report metadata | `POST /tokenkeeper/record` explicitly | Verified |
| Provider does not return token usage | Call can be captured, but token/cost fields are recorded as 0 until provider-specific extraction or manual records are added | Verified limitation |
| Hermes-style local app with a readable state database | Use `tokenkeeper connect hermes` or dashboard Hermes sync | Verified for tested Hermes `state.db` shape |

## Explicit Boundary

tokenkeeper cannot silently observe arbitrary traffic from another process, another language runtime, a SaaS-hosted agent, encrypted traffic, or a private binary that does not route through tokenkeeper. External agents are trackable only when they route supported HTTP traffic through `tokenkeeper proxy`, use a callback/adapter, or explicitly report records through `POST /tokenkeeper/record` / `guard.record()`.
