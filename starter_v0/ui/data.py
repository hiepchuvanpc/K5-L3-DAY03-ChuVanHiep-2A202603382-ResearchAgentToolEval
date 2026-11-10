"""Pure data layer for the UI. No Streamlit import, so every function is unit-testable.

Evidence files it reads (all produced by the lab harness, never edited here):
  runs/*.json                -> RunRecord: one eval run of one version on one suite
  artifacts/version_log.csv  -> ledger rows: hypothesis, metric_before/after per version
  transcripts/*.json         -> live chat sessions (chat.py or the UI)
  artifacts/tools.yaml + tools/*/TOOL.md -> tool cards for the overview page

Two MECE partitions drive the comparison views:
  * OUTCOMES: every case in a run lands in exactly one outcome (precedence documented
    in classify_outcome).
  * TRANSITIONS: every case lands in exactly one change category between version A and B.
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
TRANSCRIPTS_DIR = ROOT / "transcripts"
ARTIFACTS_DIR = ROOT / "artifacts"
DATA_DIR = ROOT / "data"
TOOLS_DIR = ROOT / "tools"
VERSION_LOG = ARTIFACTS_DIR / "version_log.csv"

# Tools that ship with the starter. Anything else declared in tools.yaml is a team-built tool.
STARTER_TOOLS = {
    "clarify", "timeline", "social_search", "lookup", "fetch", "format",
    "send", "policy", "papers", "paper_text",
}

# ----------------------------------------------------------------------------
# Outcome taxonomy (MECE): each case result is exactly one of these.
# ----------------------------------------------------------------------------
OUTCOMES: dict[str, dict[str, str]] = {
    "pass": {"label": "Đạt", "short": "Đạt", "hint": "Đúng tool, đúng tham số, không gọi thừa."},
    "wrong_tool": {
        "label": "Sai tool", "short": "Sai tool",
        "hint": "Không gọi tool kỳ vọng: gọi tool khác hoặc không gọi gì.",
    },
    "wrong_args": {
        "label": "Sai tham số", "short": "Sai tham số",
        "hint": "Gọi đúng tool nhưng có tham số lệch so với kỳ vọng.",
    },
    "extra_tool": {
        "label": "Gọi thừa tool", "short": "Gọi thừa",
        "hint": "Tool và tham số kỳ vọng đều đúng, nhưng gọi thêm tool không cần.",
    },
    "unexpected_tool": {
        "label": "Lẽ ra không gọi tool", "short": "Không được gọi",
        "hint": "Case yêu cầu trả lời trực tiếp (ngoài phạm vi / câu meta) nhưng agent gọi tool.",
    },
    "provider_error": {
        "label": "Lỗi provider", "short": "Lỗi API",
        "hint": "Lỗi API/mạng: không tính vào accuracy.",
    },
}
OUTCOME_ORDER = list(OUTCOMES)
FAILURE_OUTCOMES = ["wrong_tool", "wrong_args", "extra_tool", "unexpected_tool"]

_ARG_FAILURE = re.compile(r"^[^:]+: expected .*, got ", re.DOTALL)


def classify_outcome(result: dict[str, Any]) -> str:
    """Map one run_eval result to exactly one outcome.

    Precedence when a case has several problems (the first match wins):
    provider_error > pass > unexpected_tool > wrong_tool > wrong_args > extra_tool.
    The order runs from the most basic mistake (calling a tool at all, picking the
    tool) to the finest (an argument value, one extra call).
    """
    mismatch = result.get("observed_mismatch")
    if result.get("failure_type") == "provider_error" or mismatch == "provider_error":
        return "provider_error"
    if result.get("passed"):
        return "pass"
    failures = [str(item) for item in result.get("failures") or []]
    if mismatch == "unexpected_tool_call" or "expected no tool call" in failures:
        return "unexpected_tool"
    if mismatch == "missing_tool_call" or any(item.startswith("missing tool call") for item in failures):
        return "wrong_tool"
    if mismatch == "wrong_arg_value" or any(_ARG_FAILURE.match(item) for item in failures):
        return "wrong_args"
    if mismatch == "extra_tool_call" or any(item.startswith("extra tool call") for item in failures):
        return "extra_tool"
    # A failing result always carries failures; an unknown shape is treated as a routing miss.
    return "wrong_tool"


# ----------------------------------------------------------------------------
# Transition taxonomy (MECE) between version A and version B for one case.
# ----------------------------------------------------------------------------
TRANSITIONS: dict[str, dict[str, str]] = {
    "fixed": {"label": "Đã sửa", "desc": "FAIL → PASS"},
    "regressed": {"label": "Hồi quy", "desc": "PASS → FAIL"},
    "still_failing": {"label": "Vẫn lỗi", "desc": "FAIL → FAIL"},
    "stable_pass": {"label": "Giữ vững", "desc": "PASS → PASS"},
    "unmeasured": {"label": "Không đo được", "desc": "Lỗi provider ở một trong hai bản"},
    "added": {"label": "Case mới", "desc": "Chỉ có ở bản sau"},
    "removed": {"label": "Không còn", "desc": "Chỉ có ở bản trước"},
}
TRANSITION_ORDER = list(TRANSITIONS)


def transition(a_outcome: str | None, b_outcome: str | None) -> str:
    if a_outcome is None and b_outcome is None:
        raise ValueError("a case must exist in at least one of the two runs")
    if a_outcome is None:
        return "added"
    if b_outcome is None:
        return "removed"
    if "provider_error" in (a_outcome, b_outcome):
        return "unmeasured"
    a_ok, b_ok = a_outcome == "pass", b_outcome == "pass"
    if a_ok and b_ok:
        return "stable_pass"
    if a_ok:
        return "regressed"
    if b_ok:
        return "fixed"
    return "still_failing"


# ----------------------------------------------------------------------------
# Versions and runs
# ----------------------------------------------------------------------------
_VERSION_RE = re.compile(r"^v?(\d+)(.*)$", re.IGNORECASE)


def version_key(label: str) -> tuple:
    """Natural order: v0 < v1 < v2 < v3 < v3-qwen7b < v10; odd labels go last."""
    match = _VERSION_RE.match(str(label).strip())
    if not match:
        return (1, 0, str(label).lower())
    return (0, int(match.group(1)), match.group(2).lower())


@dataclass
class RunRecord:
    path: Path
    run_id: str
    version: str
    suite: str
    provider: str
    model: str | None
    generated_at: str
    artifact_version: str
    prompt_hash: str
    tools_hash: str
    dataset_id: str
    eval_cases: str
    summary: dict[str, Any]
    results: list[dict[str, Any]]

    @property
    def file_label(self) -> str:
        return f"runs/{self.path.name}"

    @property
    def passed(self) -> int:
        return int(self.summary.get("passed_cases") or 0)

    @property
    def total(self) -> int:
        return int(self.summary.get("total_cases") or len(self.results))

    def case_map(self) -> dict[str, dict[str, Any]]:
        return {item["id"]: item for item in self.results}


def run_from_payload(path: Path, payload: dict[str, Any]) -> RunRecord:
    return RunRecord(
        path=path,
        run_id=payload.get("run_id") or path.stem,
        version=str(payload["version"]),
        suite=str(payload.get("suite") or "base"),
        provider=str(payload.get("provider") or ""),
        model=payload.get("model"),
        generated_at=str(payload.get("generated_at") or ""),
        artifact_version=str(payload.get("artifact_version") or ""),
        prompt_hash=str(payload.get("prompt_hash") or ""),
        tools_hash=str(payload.get("tools_hash") or ""),
        dataset_id=str(payload.get("dataset_id") or ""),
        eval_cases=str(payload.get("eval_cases") or ""),
        summary=dict(payload.get("summary") or {}),
        results=list(payload["results"]),
    )


def load_runs(runs_dir: Path = RUNS_DIR) -> tuple[list[RunRecord], list[str]]:
    """Load every run JSON. Broken files are reported, never fatal."""
    runs: list[RunRecord] = []
    problems: list[str] = []
    if not runs_dir.exists():
        return runs, problems
    for path in sorted(runs_dir.glob("*.json")):
        try:
            runs.append(run_from_payload(path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"{path.name}: {type(exc).__name__}: {exc}")
    runs.sort(key=lambda run: (version_key(run.version), run.generated_at, run.path.name))
    return runs, problems


def suites_in(runs: list[RunRecord]) -> list[str]:
    preferred = ["base", "group", "extension", "cross"]
    found = {run.suite for run in runs}
    return [s for s in preferred if s in found] + sorted(found - set(preferred))


def latest_by_version(runs: list[RunRecord], suite: str) -> dict[str, RunRecord]:
    """Latest run per version label within one suite, ordered v0 -> vN."""
    chosen: dict[str, RunRecord] = {}
    for run in runs:
        if run.suite != suite:
            continue
        current = chosen.get(run.version)
        if current is None or (run.generated_at, run.path.name) > (current.generated_at, current.path.name):
            chosen[run.version] = run
    return {version: chosen[version] for version in sorted(chosen, key=version_key)}


def next_version_label(labels: list[str]) -> str:
    numbers = [version_key(label)[1] for label in labels if version_key(label)[0] == 0]
    return f"v{max(numbers) + 1}" if numbers else "v0"


# ----------------------------------------------------------------------------
# Tool calls
# ----------------------------------------------------------------------------
def format_call(call: dict[str, Any]) -> str:
    args = call.get("args") or {}
    inner = ", ".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in args.items())
    return f"{call.get('name')}({inner})"


def format_calls(calls: list[dict[str, Any]]) -> str:
    return " + ".join(format_call(call) for call in calls) if calls else "(không gọi tool)"


def call_signature(calls: list[dict[str, Any]]) -> str:
    """Order-insensitive fingerprint of tool behaviour (names + args). Text is ignored."""
    normalized = [
        json.dumps({"name": call.get("name"), "args": call.get("args") or {}}, sort_keys=True, ensure_ascii=False)
        for call in calls
    ]
    return "|".join(sorted(normalized))


def _normalize(value: Any) -> Any:
    # Mirrors run_eval.normalize_value so highlighted args agree with the grader.
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return sorted(_normalize(item) for item in value)
    return value


def arg_matches(key: str, expected: Any, actual: Any) -> bool:
    # Mirrors run_eval.compare_subset for a single key.
    if key == "missing_fields":
        return set(expected).issubset(set(actual or []))
    if key == "constraints":
        return set(_normalize(expected)).issubset(set(_normalize(actual or [])))
    return _normalize(actual) == _normalize(expected)


def annotate_calls(
    expected_calls: list[dict[str, Any]], actual_calls: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pair each expected call with the actual call the grader matches; flag every graded arg.

    Returns (pairs, extras). pairs[i] = {"expected", "actual" (or None), "args": [...]},
    extras = actual calls that matched no expected call.
    """
    unmatched = dict(enumerate(actual_calls))
    pairs: list[dict[str, Any]] = []
    for expected in expected_calls:
        expected_args = expected.get("args") or {}
        same_name = [(i, call) for i, call in unmatched.items() if call.get("name") == expected.get("name")]
        if not same_name:
            pairs.append({"expected": expected, "actual": None, "args": []})
            continue
        best_index, best_call, best_correct = None, None, -1
        for index, call in same_name:
            correct = sum(
                arg_matches(key, value, (call.get("args") or {}).get(key)) for key, value in expected_args.items()
            )
            if correct > best_correct:
                best_index, best_call, best_correct = index, call, correct
        unmatched.pop(best_index)
        actual_args = best_call.get("args") or {}
        rows = [
            {"key": key, "expected": value, "actual": actual_args.get(key), "ok": arg_matches(key, value, actual_args.get(key))}
            for key, value in expected_args.items()
        ]
        pairs.append({"expected": expected, "actual": best_call, "args": rows})
    return pairs, list(unmatched.values())


# ----------------------------------------------------------------------------
# Cross-version views
# ----------------------------------------------------------------------------
def case_order(runs: list[RunRecord]) -> list[str]:
    """Case ids in dataset order (first run first), new ids appended as they appear."""
    seen: dict[str, None] = {}
    for run in runs:
        for item in run.results:
            seen.setdefault(item["id"], None)
    return list(seen)


def case_cell(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get("result") or {}
    calls = result.get("actual_tool_calls") or []
    return {
        "outcome": classify_outcome(result),
        "passed": bool(result.get("passed")),
        "calls": calls,
        "calls_text": format_calls(calls),
        "signature": call_signature(calls),
        "failures": list(result.get("failures") or []),
        "text": result.get("actual_text") or "",
    }


def case_matrix(runs_by_version: dict[str, RunRecord]) -> list[dict[str, Any]]:
    """Long-format rows: one per (case, version), plus whether behaviour changed vs the previous version."""
    versions = list(runs_by_version)
    order = case_order(list(runs_by_version.values()))
    maps = {version: runs_by_version[version].case_map() for version in versions}
    rows: list[dict[str, Any]] = []
    for case_id in order:
        previous: dict[str, Any] | None = None
        for version in versions:
            item = maps[version].get(case_id)
            if item is None:
                previous = None
                continue
            cell = case_cell(item)
            metadata = item.get("metadata") or {}
            rows.append({
                "case_id": case_id,
                "version": version,
                "is_multiturn": bool(item.get("is_multiturn")),
                "skill": metadata.get("skill", ""),
                "what_it_tests": metadata.get("what_it_tests", ""),
                "changed_vs_prev": previous is not None and previous["signature"] != cell["signature"],
                "has_prev": previous is not None,
                **cell,
            })
            previous = cell
    return rows


def compare_pair(run_a: RunRecord, run_b: RunRecord) -> list[dict[str, Any]]:
    """Per-case transition between two runs (A = before, B = after)."""
    map_a, map_b = run_a.case_map(), run_b.case_map()
    rows: list[dict[str, Any]] = []
    for case_id in case_order([run_a, run_b]):
        a = case_cell(map_a[case_id]) if case_id in map_a else None
        b = case_cell(map_b[case_id]) if case_id in map_b else None
        meta = ((map_b.get(case_id) or map_a.get(case_id) or {}).get("metadata")) or {}
        rows.append({
            "case_id": case_id,
            "what_it_tests": meta.get("what_it_tests", ""),
            "a_outcome": a["outcome"] if a else None,
            "b_outcome": b["outcome"] if b else None,
            "transition": transition(a["outcome"] if a else None, b["outcome"] if b else None),
            "behavior_changed": bool(a and b and a["signature"] != b["signature"]),
            "a_calls": a["calls_text"] if a else "",
            "b_calls": b["calls_text"] if b else "",
        })
    return rows


def step_changes(runs_by_version: dict[str, RunRecord]) -> list[dict[str, Any]]:
    """Transition counts for each consecutive pair: what each version step bought or broke."""
    versions = list(runs_by_version)
    steps: list[dict[str, Any]] = []
    for before, after in zip(versions, versions[1:]):
        rows = compare_pair(runs_by_version[before], runs_by_version[after])
        counts = Counter(row["transition"] for row in rows)
        passed_from, passed_to = runs_by_version[before].passed, runs_by_version[after].passed
        fixed, regressed = counts.get("fixed", 0), counts.get("regressed", 0)
        steps.append({
            "from": before,
            "to": after,
            "passed_from": passed_from,
            "passed_to": passed_to,
            **{name: counts.get(name, 0) for name in TRANSITION_ORDER},
            # Net change not explained by fixed/regressed (new cases, provider errors).
            "other": passed_to - passed_from - fixed + regressed,
            "behavior_changed": sum(1 for row in rows if row["behavior_changed"]),
            "rows": rows,
        })
    return steps


def outcome_counts(run: RunRecord) -> dict[str, int]:
    counts = Counter(case_cell(item)["outcome"] for item in run.results)
    return {name: counts.get(name, 0) for name in OUTCOME_ORDER}


# ----------------------------------------------------------------------------
# Version ledger: runs + version_log.csv + integrity checks
# ----------------------------------------------------------------------------
METRICS = [
    ("case_accuracy", "Case accuracy", "Tỉ lệ case đạt toàn bộ (tool + tham số + không thừa)."),
    ("tool_routing_accuracy", "Chọn đúng tool", "Tỉ lệ case gọi đúng tập tool kỳ vọng."),
    ("argument_accuracy", "Đúng tham số", "Tỉ lệ case có mọi tham số được chấm đều đúng."),
    ("multiturn_accuracy", "Multi-turn", "Tỉ lệ case nhiều lượt đạt (giữ ngữ cảnh, sửa đổi giữa chừng)."),
]


def load_version_log(path: Path = VERSION_LOG) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(file)]


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_ledger(
    runs_by_version: dict[str, RunRecord],
    version_log: list[dict[str, str]],
    content_hashes: dict[str, dict[str, str | None]] | None = None,
) -> list[dict[str, Any]]:
    """One row per version: metrics, the logged hypothesis, and evidence-integrity checks.

    content_hashes[version] = {"prompt": <LF-normalized sha256 or None>, "tools": ...}. With it,
    "which artifact changed" ignores CRLF/LF differences between teammates' machines.
    """
    log_by_version: dict[str, dict[str, str]] = {}
    for row in version_log:
        if row.get("version"):
            log_by_version[row["version"]] = row  # later rows win
    content_hashes = content_hashes or {}
    rows: list[dict[str, Any]] = []
    previous: RunRecord | None = None
    for version, run in runs_by_version.items():
        log = log_by_version.get(version, {})
        accuracy = _as_float(run.summary.get("case_accuracy")) or 0.0
        checks: list[tuple[str, str]] = []  # (level, message) level in ok/warn/info

        if not log:
            checks.append(("warn", "Chưa có dòng trong version_log.csv"))
        else:
            logged = _as_float(log.get("metric_after"))
            if logged is None:
                checks.append(("warn", "version_log thiếu metric_after"))
            elif abs(logged - accuracy) > 0.005:
                checks.append(("warn", f"metric_after trong log ({logged:.2f}) khác run ({accuracy:.2f})"))
            else:
                checks.append(("ok", "version_log khớp run"))
            logged_file = Path(log.get("run_file", "").replace("\\", "/")).name
            if logged_file and logged_file != run.path.name:
                checks.append(("info", f"Log trỏ tới {logged_file}, đang hiển thị run mới nhất"))

        changed: list[str] = []
        if previous is not None:
            for kind, label, attr in (("prompt", "system_prompt.md", "prompt_hash"), ("tools", "tools.yaml", "tools_hash")):
                now_hash = (content_hashes.get(version) or {}).get(kind)
                before_hash = (content_hashes.get(previous.version) or {}).get(kind)
                if now_hash and before_hash:
                    differs = now_hash != before_hash
                else:  # fall back to raw hashes (may differ only because of CRLF)
                    differs = getattr(run, attr) != getattr(previous, attr)
                if differs:
                    changed.append(label)
            if len(changed) > 1:
                checks.append(("warn", "Đổi cả 2 artifact trong 1 version: khó quy kết nguyên nhân"))
            elif not changed:
                checks.append(("info", "Không đổi artifact so với bản trước (chạy lại?)"))
            else:
                checks.append(("ok", f"Một thay đổi: {changed[0]}"))

        prev_accuracy = _as_float(previous.summary.get("case_accuracy")) if previous else None
        rows.append({
            "version": version,
            "run": run,
            "changed_artifacts": changed,
            "changed_artifact_logged": log.get("changed_artifact", ""),
            "hypothesis": log.get("hypothesis", ""),
            "reason": log.get("reason", ""),
            "author": log.get("author", ""),
            "metrics": {key: _as_float(run.summary.get(key)) for key, _, _ in METRICS},
            "delta": None if prev_accuracy is None else accuracy - prev_accuracy,
            "checks": checks,
        })
        previous = run
    return rows


# ----------------------------------------------------------------------------
# Tool cards (overview page)
# ----------------------------------------------------------------------------
TOOL_GROUPS = {
    "control": "Hỏi lại người dùng",
    "live_api": "Thu thập dữ liệu",
    "local_knowledge": "Thu thập dữ liệu",
    "local_formatter": "Trình bày kết quả",
    "action": "Hành động ra bên ngoài",
}
TOOL_GROUP_ORDER = ["Thu thập dữ liệu", "Trình bày kết quả", "Hỏi lại người dùng", "Hành động ra bên ngoài", "Khác"]


def _tool_md_index(tools_dir: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for tool_md in sorted(tools_dir.glob("*/TOOL.md")):
        parts = tool_md.read_text(encoding="utf-8").split("---", 2)
        if len(parts) < 3:
            continue
        front = yaml.safe_load(parts[1]) or {}
        body = [line.strip() for line in parts[2].splitlines() if line.strip() and not line.startswith("#")]
        if front.get("name"):
            index[front["name"]] = {**front, "body": " ".join(body)}
    return index


def load_tool_cards(tools_yaml: Path, tools_dir: Path = TOOLS_DIR, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    env = dict(os.environ) if env is None else env
    declared = (yaml.safe_load(tools_yaml.read_text(encoding="utf-8")) or {}).get("tools") or []
    meta = _tool_md_index(tools_dir)
    cards: list[dict[str, Any]] = []
    for item in declared:
        name = item.get("name", "")
        info = meta.get(name, {})
        requires = list(info.get("requires_env") or [])
        missing = [key for key in requires if not env.get(key)]
        cards.append({
            "name": name,
            "summary": info.get("body") or item.get("description", ""),
            "kind": info.get("kind", ""),
            "group": TOOL_GROUPS.get(info.get("kind", ""), "Khác"),
            "provider": info.get("provider", ""),
            "side_effect": bool(info.get("side_effect")),
            "requires_env": requires,
            "missing_env": missing,
            "is_new": name not in STARTER_TOOLS,
            "params": list(((item.get("parameters") or {}).get("properties") or {}).keys()),
        })
    return cards


# ----------------------------------------------------------------------------
# Transcripts (live evidence)
# ----------------------------------------------------------------------------
def load_transcripts(transcripts_dir: Path = TRANSCRIPTS_DIR) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not transcripts_dir.exists():
        return items
    for path in transcripts_dir.glob("*.transcript.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payload["_path"] = str(path)
        payload["_file"] = path.name
        items.append(payload)
    items.sort(key=lambda t: (t.get("created_at") or "", t.get("_file") or ""), reverse=True)
    return items


def turn_tool_calls(turn: dict[str, Any]) -> list[dict[str, Any]]:
    return [call for round_ in turn.get("rounds") or [] for call in round_.get("tool_calls") or []]


def b4_rows(transcript: dict[str, Any]) -> list[dict[str, str]]:
    """Rows for REPORT.md B4 (Turn | User Request | Tool Calls | Version Evidence | Outcome)."""
    rows = []
    for turn in transcript.get("turns") or []:
        rows.append({
            "turn": str(turn.get("turn_index", "")),
            "user": str(turn.get("user", "")),
            "tool_calls": format_calls(turn_tool_calls(turn)),
            "version": str(transcript.get("artifact_version", "")),
            "outcome": str(turn.get("status", "")),
        })
    return rows


def b4_markdown(transcripts: list[dict[str, Any]]) -> str:
    def cell(text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ")

    lines = ["| Turn | User Request | Tool Calls | Version Evidence | Outcome |", "|---|---|---|---|---|"]
    for transcript in transcripts:
        for row in b4_rows(transcript):
            lines.append(
                f"| {cell(row['turn'])} | {cell(row['user'])} | `{cell(row['tool_calls'])}` | "
                f"`{cell(row['version'])}` | {cell(row['outcome'])} |"
            )
    return "\n".join(lines)
