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

## Target Automatic Capture

| Entry point | Runtime requirement | Status |
| --- | --- | --- |
| OpenAI Python SDK sync calls | Same Python process, `guard.install()` called | Planned for Phase 2 verification |
| OpenAI Python SDK async calls | Same Python process, `guard.install()` called | Planned for Phase 2 verification |
| OpenAI Python SDK stream calls | Same Python process, provider returns final `usage` | Planned for Phase 2 verification |
| OpenAI-compatible providers | Called through OpenAI Python SDK and returns OpenAI-style `usage` | Planned for Phase 2 verification |
| Anthropic Python SDK sync/async/stream | Same Python process, class-level patch works | Planned for Phase 2 verification |
| LangChain callback | Callback explicitly attached to the model/agent | Planned for Phase 2 verification |

## Fallback Capture Paths

| Scenario | Required integration |
| --- | --- |
| Non-Python agent, Node/Rust/Go app, desktop app, or separate process | Route requests through a tokenkeeper proxy or call `guard.record()` explicitly |
| Provider does not return token usage | Add provider-specific usage extraction or register usage manually |
| Hermes-style local app with a readable state database | Use a tested state DB sync connector |

## Explicit Boundary

tokenkeeper cannot silently observe arbitrary traffic from another process, another language runtime, a SaaS-hosted agent, encrypted traffic, or a private binary that does not route through tokenkeeper. Those cases need a proxy, callback, manual record call, provider export, or local state sync.
