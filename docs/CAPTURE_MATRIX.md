# tokenkeeper Capture Matrix

This matrix is the source of truth for what tokenkeeper can honestly claim today and what still needs a tested integration.

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

## Target Automatic Capture

| Entry point | Runtime requirement | Status |
| --- | --- | --- |
| OpenAI Python SDK sync calls | Same Python process, `guard.install()` called | Verified |
| OpenAI Python SDK async calls | Same Python process, `guard.install()` called | Verified |
| OpenAI Python SDK stream calls | Same Python process, provider returns final `usage` | Verified |
| OpenAI-compatible providers | Called through OpenAI Python SDK and returns OpenAI-style `usage` | Verified |
| Anthropic Python SDK sync/async/stream | Same Python process, class-level patch works | Verified |
| LangChain callback | Callback explicitly attached to the model/agent | Verified |

## Fallback Capture Paths

| Scenario | Required integration |
| --- | --- |
| Non-Python agent, Node/Rust/Go app, desktop app, or separate process | Route requests through a tokenkeeper proxy or call `guard.record()` explicitly |
| Provider does not return token usage | Call can be captured, but token/cost fields are recorded as 0 until provider-specific extraction or manual records are added |
| Hermes-style local app with a readable state database | Use a tested state DB sync connector |

## Explicit Boundary

tokenkeeper cannot silently observe arbitrary traffic from another process, another language runtime, a SaaS-hosted agent, encrypted traffic, or a private binary that does not route through tokenkeeper. Those cases need a proxy, callback, manual record call, provider export, or local state sync.
