from __future__ import annotations

from tokenkeeper.ledger import CallRecord


class MemoryLedger:
    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def record(self, call: CallRecord) -> int:
        self.records.append(call)
        return len(self.records)


class FailingLedger:
    def record(self, call: CallRecord) -> int:
        raise RuntimeError("ledger unavailable")


def test_record_success_uses_pricing_provider() -> None:
    from tokenkeeper.capture import Usage, record_success

    ledger = MemoryLedger()

    rowid = record_success(
        ledger=ledger,
        provider="openai",
        model="deepseek-chat",
        usage=Usage(prompt_tokens=1000, completion_tokens=500, cached_tokens=100),
        latency_ms=12.5,
        project="proj",
        user="alice",
    )

    assert rowid == 1
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.provider == "deepseek"
    assert record.model == "deepseek-chat"
    assert record.prompt_tokens == 1000
    assert record.completion_tokens == 500
    assert record.cached_tokens == 100
    assert record.status == "success"
    assert record.error is None
    assert record.cost_usd > 0


def test_record_error_keeps_fallback_provider_and_error_text() -> None:
    from tokenkeeper.capture import record_error

    ledger = MemoryLedger()

    rowid = record_error(
        ledger=ledger,
        provider="openai",
        model="unknown-model",
        prompt_tokens=7,
        latency_ms=2.0,
        project="proj",
        user="alice",
        error=RuntimeError("provider down"),
    )

    assert rowid == 1
    record = ledger.records[0]
    assert record.provider == "openai"
    assert record.model == "unknown-model"
    assert record.prompt_tokens == 7
    assert record.completion_tokens == 0
    assert record.status == "error"
    assert record.error == "provider down"
    assert record.cost_usd == 0
    assert record.cost_cny == 0


def test_ledger_write_failure_is_non_fatal() -> None:
    from tokenkeeper.capture import Usage, record_success

    rowid = record_success(
        ledger=FailingLedger(),
        provider="openai",
        model="gpt-4o-mini",
        usage=Usage(prompt_tokens=10, completion_tokens=5),
        latency_ms=1.0,
        project="proj",
        user="alice",
    )

    assert rowid is None
