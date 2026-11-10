"""Offline tests for the UI data layer (ui/data.py): outcome taxonomy, transitions, ledger."""
from __future__ import annotations

import pytest

from ui import data as D


def result(passed, mismatch=None, failures=(), ftype=None):
    return {"passed": passed, "observed_mismatch": mismatch, "failures": list(failures), "failure_type": ftype}


@pytest.mark.parametrize("res,expected", [
    (result(True), "pass"),
    (result(False, "unexpected_tool_call", ["expected no tool call"]), "unexpected_tool"),
    (result(False, "missing_tool_call", ["missing tool call clarify", "extra tool call fetch"]), "wrong_tool"),
    (result(False, "wrong_arg_value", ["query: expected 'AI', got 'AI news'"]), "wrong_args"),
    (result(False, "extra_tool_call", ["extra tool call send"]), "extra_tool"),
    (result(False, "provider_error", ["RuntimeError: x"], "provider_error"), "provider_error"),
])
def test_classify_outcome_is_exactly_one_bucket(res, expected) -> None:
    assert D.classify_outcome(res) == expected
    assert D.classify_outcome(res) in D.OUTCOMES


def test_missing_tool_wins_over_extra_tool() -> None:
    res = result(False, None, ["extra tool call timeline", "missing tool call clarify"])
    assert D.classify_outcome(res) == "wrong_tool"


@pytest.mark.parametrize("a,b,expected", [
    ("wrong_tool", "pass", "fixed"), ("pass", "wrong_args", "regressed"),
    ("wrong_args", "wrong_tool", "still_failing"), ("pass", "pass", "stable_pass"),
    ("provider_error", "pass", "unmeasured"), (None, "pass", "added"), ("pass", None, "removed"),
])
def test_transition_covers_every_pair(a, b, expected) -> None:
    assert D.transition(a, b) == expected


def test_transition_rejects_case_missing_from_both_runs() -> None:
    with pytest.raises(ValueError):
        D.transition(None, None)


def test_version_key_orders_naturally() -> None:
    labels = ["v10", "v2", "v0", "v3-qwen7b", "v3", "final"]
    assert sorted(labels, key=D.version_key) == ["v0", "v2", "v3", "v3-qwen7b", "v10", "final"]
    assert D.next_version_label(["v0", "v1", "v2"]) == "v3"


def test_call_signature_ignores_order_and_text() -> None:
    a = [{"name": "lookup", "args": {"q": 1}}, {"name": "social_search", "args": {}}]
    assert D.call_signature(a) == D.call_signature(list(reversed(a)))


def test_annotate_calls_flags_wrong_arg_and_extra_call() -> None:
    expected = [{"name": "lookup", "args": {"query": "AI", "topic": "news"}}]
    actual = [{"name": "lookup", "args": {"query": "AI news", "topic": "news"}}, {"name": "send", "args": {}}]
    pairs, extras = D.annotate_calls(expected, actual)
    flags = {row["key"]: row["ok"] for row in pairs[0]["args"]}
    assert flags == {"query": False, "topic": True}
    assert [c["name"] for c in extras] == ["send"]


def test_ledger_warns_when_log_disagrees_with_run(tmp_path) -> None:
    def run(version, accuracy, prompt, tools):
        return D.RunRecord(tmp_path / f"{version}.json", version, version, "base", "openai", "m", "t", f"{version}+{prompt}+{tools}",
                           prompt, tools, "d", "e", {"case_accuracy": accuracy, "passed_cases": 1, "total_cases": 1}, [])
    runs = {"v0": run("v0", 0.65, "p0", "t0"), "v1": run("v1", 0.95, "p1", "t0")}
    log = [{"version": "v0", "metric_after": "0.65"}, {"version": "v1", "metric_after": "0.50", "hypothesis": "h"}]
    ledger = D.build_ledger(runs, log)
    assert ledger[1]["changed_artifacts"] == ["system_prompt.md"]
    assert any(level == "warn" and "khác run" in msg for level, msg in ledger[1]["checks"])
    assert ledger[1]["delta"] == pytest.approx(0.30)
