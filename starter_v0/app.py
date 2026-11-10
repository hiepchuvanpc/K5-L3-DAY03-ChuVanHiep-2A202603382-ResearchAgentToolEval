"""Research Agent · Eval Studio (Streamlit).

MECE navigation: Giới thiệu | Đánh giá offline (runs/*.json) | Trải nghiệm live (model thật).
Every number comes from runs/*.json, artifacts/version_log.csv or transcripts/: new versions
(v3, ...) appear automatically once their run file exists, with no code change.

Run:  streamlit run app.py
"""
from __future__ import annotations

import difflib
import html
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from chat import now_iso, run_model_tool_loop, safe_slug, trim_history, write_transcript
from env_loader import load_lab_env
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from ui import data as D
from ui import provenance
from versioning import artifact_version_dict, build_artifact_version

ROOT = Path(__file__).parent
ARTIFACTS_DIR = ROOT / "artifacts"
load_lab_env(ROOT)

st.set_page_config(page_title="Research Agent · Eval Studio", page_icon="🔎", layout="wide")

# --------------------------------------------------------------------------- provider
PROVIDERS = {  # name -> env var holding its key (None = no key needed)
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": None,
}


def detect_provider() -> str:
    """Pick the provider whose key is present, so chat works out of the box on any teammate's .env."""
    for name in ("openrouter", "openai", "anthropic", "gemini"):
        if os.getenv(PROVIDERS[name] or ""):
            return name
    return "ollama"


def key_ok(name: str) -> bool:
    env = PROVIDERS[name]
    return env is None or bool(os.getenv(env))


# --------------------------------------------------------------------------- palette (dataviz skill)
def tokens() -> dict:
    dark = st.context.theme.type == "dark"
    return {
        "good": "#0ca30c", "bad": "#d03b3b", "neutral": "#383835" if dark else "#c3c2b7",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500"] if dark else ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
        "label_on_series": ["#ffffff", "#ffffff", "#ffffff", "#0b0b0b"],
    }


st.html("""<style>
.tc{display:inline-block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82rem;
    padding:.18rem .5rem;margin:.12rem .2rem .12rem 0;border-radius:.45rem;
    background:rgba(127,127,127,.12);border:1px solid rgba(127,127,127,.22);line-height:1.5}
.tc b{font-weight:650}
.arg-ok{border-bottom:2px solid #0ca30c}
.arg-bad{border-bottom:2px solid #d03b3b}
.muted{opacity:.65;font-size:.85rem}
.hero{font-size:3.4rem;font-weight:700;line-height:1;letter-spacing:-.02em}
</style>""")


# --------------------------------------------------------------------------- cached data
def _fingerprint(folder: Path, pattern: str) -> tuple:
    return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in folder.glob(pattern))) if folder.exists() else ()


@st.cache_data(show_spinner=False)
def _runs(_fp: tuple):
    return D.load_runs()


def runs():
    return _runs(_fingerprint(D.RUNS_DIR, "*.json"))


@st.cache_data(show_spinner=False)
def artifact(rel_path: str, target_hash: str, _head: str):
    return provenance.resolve(rel_path, target_hash)


def git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


# --------------------------------------------------------------------------- shared components
def call_chip(call: dict, arg_flags: dict[str, tuple[bool, object]] | None = None) -> str:
    arg_flags = arg_flags or {}
    parts = []
    for key, value in (call.get("args") or {}).items():
        text = f"{html.escape(key)}={html.escape(json.dumps(value, ensure_ascii=False))}"
        if key in arg_flags:
            ok, expected = arg_flags[key]
            tip = "khớp kỳ vọng" if ok else f"kỳ vọng: {json.dumps(expected, ensure_ascii=False)}"
            text = f'<span class="{"arg-ok" if ok else "arg-bad"}" title="{html.escape(tip)}">{text}</span>'
        parts.append(text)
    return f'<span class="tc"><b>{html.escape(str(call.get("name")))}</b>({", ".join(parts)})</span>'


def outcome_badge(outcome: str) -> None:
    meta = D.OUTCOMES[outcome]
    if outcome == "pass":
        st.badge(meta["label"], icon=":material/check:", color="green")
    elif outcome == "provider_error":
        st.badge(meta["label"], icon=":material/cloud_off:", color="gray")
    else:
        st.badge(meta["label"], icon=":material/close:", color="red", help=meta["hint"])


def render_tool_events(events: list[dict]) -> None:
    for event in events:
        result = event.get("result") or {}
        label = call_chip({"name": event.get("tool"), "args": event.get("args")})
        with st.expander(f"🔧 {event.get('tool')}", expanded=False):
            st.html(label)
            items = result.get("items") if isinstance(result, dict) else None
            if isinstance(result, dict) and result.get("error"):
                st.error(f"{result.get('error')}: {result.get('message', '')}")
            elif items:
                for item in items[:8]:
                    title = item.get("title") or item.get("url") or "(không tiêu đề)"
                    url = item.get("url")
                    st.markdown(f"- [{title}]({url}) · {item.get('source', '')}" if url else f"- {title}")
            else:
                st.json(result, expanded=False)


# =========================================================================== pages
def page_overview() -> None:
    all_runs, _ = runs()
    base = D.latest_by_version(all_runs, "base")
    st.title("Research Agent")
    st.markdown("Agent nghiên cứu chạy tool thật: **tìm tin theo chủ đề hoặc theo tài khoản, đọc URL, tổng hợp digest, "
                "tính toán, và chỉ đăng Telegram khi người dùng đã xác nhận.**")

    if base:
        versions = list(base)
        first, last = base[versions[0]], base[versions[-1]]
        left, right = st.columns([1, 1.6], gap="large")
        with left.container(border=True):
            st.caption(f"CASE ACCURACY · {versions[-1]} · base suite ({last.total} case)")
            st.html(f'<div class="hero">{pct(last.summary.get("case_accuracy"))}</div>')
            gain = (last.summary.get("case_accuracy") or 0) - (first.summary.get("case_accuracy") or 0)
            st.markdown(f":green[**{gain * 100:+.0f} điểm %**] so với {versions[0]} ({pct(first.summary.get('case_accuracy'))}) "
                        f"qua {len(versions) - 1} vòng tối ưu.")
            st.page_link(PAGES["compare"], label="Xem so sánh từng phiên bản", icon=":material/arrow_forward:")
        with right.container(border=True):
            st.caption("HÀNH TRÌNH PHIÊN BẢN (mỗi bản đúng 1 giả thuyết)")
            log = {row["version"]: row for row in D.load_version_log()}
            cols = st.columns(len(versions))
            for col, version in zip(cols, versions):
                with col:
                    st.metric(version, pct(base[version].summary.get("case_accuracy")))
                    changed = log.get(version, {}).get("changed_artifact", "") or "—"
                    st.caption(changed.replace("artifacts/", ""))

    st.subheader("Agent có những tool gì")
    cards = D.load_tool_cards(ARTIFACTS_DIR / "tools.yaml")
    groups = [g for g in D.TOOL_GROUP_ORDER if any(c["group"] == g for c in cards)]
    for group, col in zip(groups, st.columns(len(groups))):
        with col.container(border=True):
            st.markdown(f"**{group}**")
            for card in [c for c in cards if c["group"] == group]:
                flags = []
                if card["is_new"]:
                    flags.append(":blue-badge[tool mới của nhóm]")
                if card["side_effect"]:
                    flags.append(":orange-badge[cần xác nhận]")
                if card["missing_env"]:
                    flags.append(f":red-badge[thiếu {', '.join(card['missing_env'])}]")
                st.markdown(f"`{card['name']}` {' '.join(flags)}")
                st.caption(card["summary"][:140])

    st.subheader("Thử ngay")
    samples = [
        "Tin tức AI hôm nay có gì nổi bật?",
        "Lấy 3 tweet mới nhất của Andrej Karpathy",
        "Tìm giúp mình tweet mới nhất của họ",
        "Tính giúp mình 27 * 14",
        "Đăng bản tin AI hôm nay lên Telegram giúp mình",
    ]
    for sample, col in zip(samples, st.columns(len(samples))):
        if col.button(sample, use_container_width=True):
            st.session_state.pending_prompt = sample
            st.switch_page(PAGES["chat"])


def version_filter(key: str):
    all_runs, problems = runs()
    for problem in problems:
        st.warning(f"Bỏ qua run lỗi: {problem}")
    suites = D.suites_in(all_runs)
    if not suites:
        st.info("Chưa có run nào trong runs/. Chạy eval ở trang **Chạy eval**.")
        st.stop()
    c1, c2 = st.columns([1, 3])
    suite = c1.segmented_control("Bộ eval", suites, default="base" if "base" in suites else suites[0], key=f"{key}_suite") or suites[0]
    available = list(D.latest_by_version(all_runs, suite))
    picked = c2.pills("Phiên bản", available, selection_mode="multi", default=available, key=f"{key}_versions") or available
    by_version = D.latest_by_version(all_runs, suite)
    return suite, {v: by_version[v] for v in available if v in picked}


def page_compare() -> None:
    st.title("So sánh phiên bản")
    st.caption("Nguyên nhân (artifact nào đổi, giả thuyết gì) → tác động (metric) → bằng chứng (case nào đổi đầu ra).")
    suite, selected = version_filter("cmp")
    versions = list(selected)
    if not versions:
        st.stop()

    # KPI row: latest selected vs the one before it
    last = selected[versions[-1]]
    prev = selected[versions[-2]] if len(versions) > 1 else None
    st.markdown(f"#### {versions[-1]}" + (f" so với {versions[-2]}" if prev else ""))
    for (key, label, help_text), col in zip(D.METRICS, st.columns(len(D.METRICS))):
        value = last.summary.get(key)
        delta = None
        if prev is not None and value is not None and prev.summary.get(key) is not None:
            delta = f"{(value - prev.summary[key]) * 100:+.0f} điểm %"
        col.metric(label, pct(value), delta, help=help_text, border=True,
                   chart_data=[selected[v].summary.get(key) or 0 for v in versions], chart_type="line")

    tabs = st.tabs(["Sổ phiên bản", "Ma trận case × version", "Từng bước", "Phân rã lỗi", "Diff artifact"])

    # ---- ledger
    with tabs[0]:
        head = git_head()
        hashes = {}
        for v, run in selected.items():
            p = artifact("artifacts/system_prompt.md", run.prompt_hash, head)
            t = artifact("artifacts/tools.yaml", run.tools_hash, head)
            norm = lambda res: provenance.hash_variants(res[0].encode())["lf"] if res else None  # noqa: E731
            hashes[v] = {"prompt": norm(p), "tools": norm(t)}
        ledger = D.build_ledger(selected, D.load_version_log(), hashes)
        for row, col in zip(ledger, st.columns(len(ledger))):
            with col.container(border=True):
                run = row["run"]
                st.markdown(f"### {row['version']}")
                changed = ", ".join(row["changed_artifacts"]) or ("baseline" if row is ledger[0] else "không đổi")
                st.markdown(f":blue-badge[{changed}]")
                delta = None if row["delta"] is None else f"{row['delta'] * 100:+.0f} điểm %"
                st.metric("Case accuracy", pct(row["metrics"]["case_accuracy"]), delta)
                if row["hypothesis"]:
                    st.markdown(f"**Giả thuyết:** {row['hypothesis']}")
                for level, message in row["checks"]:
                    icon = {"ok": ":green[✓]", "warn": ":orange[⚠]", "info": ":gray[ℹ]"}[level]
                    st.markdown(f"{icon} {message}")
                st.caption(f"{run.file_label} · {run.provider}/{run.model} · {run.generated_at}")
        st.dataframe(pd.DataFrame([{
            "Phiên bản": r["version"],
            **{label: r["metrics"][key] for key, label, _ in D.METRICS},
            "Đạt": f"{r['run'].passed}/{r['run'].total}",
            "artifact_version": r["run"].artifact_version,
        } for r in ledger]), hide_index=True, width="stretch", column_config={
            label: st.column_config.ProgressColumn(label, format="percent", min_value=0, max_value=1) for _, label, _ in D.METRICS
        })

    # ---- matrix
    with tabs[1]:
        rows = D.case_matrix(selected)
        frame = pd.DataFrame(rows)
        frame["status"] = frame["outcome"].map(lambda o: "Đạt" if o == "pass" else ("Lỗi provider" if o == "provider_error" else "Lỗi"))
        frame["label"] = frame.apply(lambda r: ("✓ " if r.outcome == "pass" else "✗ ") + D.OUTCOMES[r.outcome]["short"]
                                     + (" · Δ" if r.changed_vs_prev else ""), axis=1)
        frame["failures_text"] = frame["failures"].map(lambda f: "; ".join(f) or "—")
        tk = tokens()
        order = D.case_order(list(selected.values()))
        base_chart = alt.Chart(frame).encode(
            x=alt.X("version:N", sort=versions, title=None, axis=alt.Axis(orient="top", labelAngle=0)),
            y=alt.Y("case_id:N", sort=order, title=None, axis=alt.Axis(labelLimit=260)),
        )
        cells = base_chart.mark_rect(cornerRadius=4).encode(
            color=alt.Color("status:N", scale=alt.Scale(domain=["Đạt", "Lỗi", "Lỗi provider"], range=[tk["good"], tk["bad"], tk["neutral"]]),
                            legend=alt.Legend(orient="bottom", title=None)),
            tooltip=[alt.Tooltip("case_id:N", title="Case"), alt.Tooltip("version:N", title="Version"),
                     alt.Tooltip("label:N", title="Kết quả"), alt.Tooltip("calls_text:N", title="Tool đã gọi"),
                     alt.Tooltip("failures_text:N", title="Lỗi"), alt.Tooltip("what_it_tests:N", title="Kiểm tra")],
        )
        text = base_chart.mark_text(fontSize=12, color="white").encode(text="label:N")
        chart = (cells + text).properties(height=max(260, 30 * len(order))).configure_scale(bandPaddingInner=0.08)
        st.caption("Mỗi ô = kết quả của 1 case ở 1 version. **Δ** = tập tool được gọi (tên + tham số) khác bản trước, "
                   "kể cả khi trạng thái đạt/lỗi giữ nguyên. Rê chuột để xem lời gọi tool thật.")
        st.altair_chart(chart, width="stretch")
        st.page_link(PAGES["cases"], label="Soi chi tiết từng case", icon=":material/search:")

    # ---- step changes
    with tabs[2]:
        steps = D.step_changes(selected)
        if not steps:
            st.info("Chọn ít nhất 2 phiên bản để xem thay đổi giữa các bước.")
        for step in steps:
            with st.container(border=True):
                st.markdown(f"#### {step['from']} → {step['to']}  ·  {step['passed_from']} → {step['passed_to']} case đạt")
                c = st.columns(5)
                c[0].metric("Đã sửa (FAIL→PASS)", step["fixed"])
                c[1].metric("Hồi quy (PASS→FAIL)", step["regressed"])
                c[2].metric("Vẫn lỗi", step["still_failing"])
                c[3].metric("Giữ vững", step["stable_pass"])
                c[4].metric("Đổi hành vi", step["behavior_changed"], help="Tập tool gọi khác đi giữa 2 bản")
                interesting = [r for r in step["rows"] if r["transition"] in ("fixed", "regressed", "still_failing") or r["behavior_changed"]]
                if interesting:
                    st.dataframe(pd.DataFrame([{
                        "Case": r["case_id"], "Thay đổi": D.TRANSITIONS[r["transition"]]["label"],
                        f"Đầu ra {step['from']}": r["a_calls"], f"Đầu ra {step['to']}": r["b_calls"],
                    } for r in interesting]), hide_index=True, width="stretch")

    # ---- failure modes
    with tabs[3]:
        tk = tokens()
        counts = pd.DataFrame([{"version": v, "outcome": D.OUTCOMES[o]["label"], "n": n}
                               for v, run in selected.items() for o, n in D.outcome_counts(run).items()
                               if o in D.FAILURE_OUTCOMES and n])
        st.caption("Chỉ các case lỗi, mỗi case thuộc đúng 1 nhóm (ưu tiên: lẽ ra không gọi tool > sai tool > sai tham số > gọi thừa).")
        if counts.empty:
            st.success("Không có case lỗi trong các phiên bản đã chọn.")
        else:
            domain = [D.OUTCOMES[o]["label"] for o in D.FAILURE_OUTCOMES]
            bars = alt.Chart(counts).mark_bar(cornerRadiusEnd=4, height=22, stroke=None).encode(
                y=alt.Y("version:N", sort=versions, title=None),
                x=alt.X("sum(n):Q", title="Số case lỗi", axis=alt.Axis(tickMinStep=1)),
                color=alt.Color("outcome:N", scale=alt.Scale(domain=domain, range=tk["series"]), legend=alt.Legend(orient="top", title=None)),
                order=alt.Order("outcome:N"),
                tooltip=["version", "outcome", "n"],
            )
            st.altair_chart(bars.properties(height=60 * len(versions)), width="stretch")
            st.dataframe(counts.pivot_table(index="version", columns="outcome", values="n", fill_value=0), width="stretch")

    # ---- artifact diff
    with tabs[4]:
        if len(versions) < 2:
            st.info("Chọn ít nhất 2 phiên bản.")
        else:
            c1, c2 = st.columns(2)
            a = c1.selectbox("Từ", versions, index=len(versions) - 2)
            b = c2.selectbox("Đến", versions, index=len(versions) - 1)
            head = git_head()
            log = {row["version"]: row for row in D.load_version_log()}
            if log.get(b, {}).get("hypothesis"):
                st.info(f"**Giả thuyết {b}:** {log[b]['hypothesis']}")
            for rel, attr in (("artifacts/system_prompt.md", "prompt_hash"), ("artifacts/tools.yaml", "tools_hash")):
                ra = artifact(rel, getattr(selected[a], attr), head)
                rb = artifact(rel, getattr(selected[b], attr), head)
                st.markdown(f"##### `{rel.split('/')[-1]}`")
                if not ra or not rb:
                    st.warning("Không tìm thấy nội dung khớp hash trong working tree / lịch sử git (file chưa commit?).")
                    continue
                diff = list(difflib.unified_diff(ra[0].splitlines(), rb[0].splitlines(), f"{a}", f"{b}", lineterm=""))
                if not diff:
                    st.caption(f"Không đổi · nguồn: {rb[1]}")
                else:
                    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
                    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
                    st.caption(f"+{added} / −{removed} dòng · {a}: {ra[1]} → {b}: {rb[1]}")
                    st.code("\n".join(diff), language="diff")


def page_cases() -> None:
    st.title("Soi từng case")
    st.caption("Cùng một input, mỗi version gọi tool gì, tham số nào khớp / lệch kỳ vọng.")
    suite, selected = version_filter("case")
    versions = list(selected)
    if not versions:
        st.stop()
    order = D.case_order(list(selected.values()))
    maps = {v: run.case_map() for v, run in selected.items()}

    def label(case_id: str) -> str:
        marks = "".join("✓" if (maps[v].get(case_id) or {}).get("result", {}).get("passed") else "✗" for v in versions if case_id in maps[v])
        return f"{case_id}   {marks}"

    only_changed = st.toggle("Chỉ hiện case có thay đổi giữa các version")
    if only_changed:
        order = [c for c in order if len({D.case_cell(maps[v][c])["signature"] for v in versions if c in maps[v]}) > 1
                 or len({D.case_cell(maps[v][c])["outcome"] for v in versions if c in maps[v]}) > 1] or order
    case_id = st.selectbox("Case", order, format_func=label)
    sample = next(maps[v][case_id] for v in versions if case_id in maps[v])
    meta = sample.get("metadata") or {}

    with st.container(border=True):
        st.markdown(f"**{meta.get('what_it_tests', '')}**")
        st.caption(f"skill: {meta.get('skill', '')} · nhóm lỗi case nhắm tới: {sample['result'].get('case_failure_type')} · "
                   f"{'multi-turn' if sample.get('is_multiturn') else 'single-turn'}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Input**")
            inp = sample.get("input")
            if isinstance(inp, list):
                for turn in inp:
                    st.markdown(f"- *{turn['role']}*: {turn['content']}")
            else:
                st.markdown(f"> {inp}")
        with c2:
            st.markdown("**Kỳ vọng**")
            expect = sample.get("expect") or {}
            if expect.get("no_tool"):
                st.markdown("Không gọi tool, trả lời trực tiếp.")
            else:
                st.html(" ".join(call_chip(c) for c in expect.get("tool_calls", [])))

    for version, col in zip(versions, st.columns(len(versions))):
        item = maps[version].get(case_id)
        with col.container(border=True):
            st.markdown(f"### {version}")
            if item is None:
                st.caption("Version này không chạy case này.")
                continue
            cell = D.case_cell(item)
            outcome_badge(cell["outcome"])
            pairs, extras = D.annotate_calls((item.get("expect") or {}).get("tool_calls", []), cell["calls"])
            chips = []
            for pair in pairs:
                if pair["actual"] is None:
                    chips.append(f'<span class="tc" style="opacity:.6">thiếu <b>{html.escape(pair["expected"]["name"])}</b></span>')
                else:
                    flags = {r["key"]: (r["ok"], r["expected"]) for r in pair["args"]}
                    chips.append(call_chip(pair["actual"], flags))
            chips += [call_chip(c) + ' <span class="muted">(thừa)</span>' for c in extras]
            st.html(" ".join(chips) or '<span class="muted">(không gọi tool)</span>')
            for failure in cell["failures"]:
                st.markdown(f":red[✗] `{failure}`")
            if cell["text"]:
                with st.expander("Câu trả lời text"):
                    st.markdown(cell["text"])
            if item.get("tool_results"):
                with st.expander("Kết quả tool thật"):
                    render_tool_events([r for r in item["tool_results"] if "result" in r])


def sidebar_live_settings() -> dict:
    with st.sidebar:
        st.markdown("**Cấu hình model**")
        names = list(PROVIDERS)
        provider_name = st.selectbox("Provider", names, index=names.index(detect_provider()), key="provider",
                                     format_func=lambda n: f"{n} {'✓' if key_ok(n) else '· thiếu key'}")
        default_model = getattr(make_provider(provider_name), "default_model", "")
        model = st.text_input("Model", placeholder=f"mặc định: {default_model}", key="model").strip() or None
        if not key_ok(provider_name):
            st.error(f"Thiếu `{PROVIDERS[provider_name]}` trong `.env`: model sẽ không trả lời.")
        if st.button("Kiểm tra kết nối", use_container_width=True):
            try:
                reply = make_provider(provider_name).complete(
                    [{"role": "user", "content": "Reply with the single word: OK"}], None, model=model, temperature=0.0)
                st.success(f"Model trả lời: {(reply.text or '').strip()[:40]}")
            except Exception as exc:  # show the real reason instead of failing silently
                st.error(f"{type(exc).__name__}: {exc}")
        rounds = st.number_input("Max tool rounds", 1, 10, 4, key="rounds")
        window = st.number_input("History window", 0, 20, 5, key="window")
    return {"provider": provider_name, "model": model, "rounds": int(rounds), "window": int(window),
            "model_label": model or default_model}


def page_chat() -> None:
    settings = sidebar_live_settings()
    prompt_path, tools_path = ARTIFACTS_DIR / "system_prompt.md", ARTIFACTS_DIR / "tools.yaml"
    version = st.session_state.setdefault("chat_version", D.latest_by_version(runs()[0], "base") and
                                          list(D.latest_by_version(runs()[0], "base"))[-1] or "v0")
    av = build_artifact_version(version, prompt_path, tools_path)

    head, btn = st.columns([4, 1])
    head.title("Chat với agent")
    head.caption(f"Model thật: **{settings['provider']} / {settings['model_label']}** · artifact `{av.artifact_version}` · "
                 "mỗi lượt được ghi vào transcripts/.")
    if btn.button("Phiên mới", icon=":material/refresh:", use_container_width=True):
        for key in ("messages", "history", "transcript"):
            st.session_state.pop(key, None)
        st.rerun()

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("history", [])

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"] or "_(không có nội dung)_")
            render_tool_events(message.get("events") or [])

    if not st.session_state.messages:
        st.caption("Gợi ý:")
        for sample, col in zip(["Tin tức AI hôm nay có gì nổi bật?", "Tìm giúp mình tweet mới nhất của họ",
                                "Đăng bản tin AI hôm nay lên Telegram giúp mình"], st.columns(3)):
            if col.button(sample, use_container_width=True):
                st.session_state.pending_prompt = sample
                st.rerun()

    # Quick replies when the agent is waiting on a yes/no or choice question.
    last = st.session_state.messages[-1] if st.session_state.messages else None
    if last and last.get("awaiting"):
        options = last["awaiting"].get("options") or (["Có", "Không"] if last["awaiting"].get("response_type") == "yes_no" else [])
        if options:
            for option, col in zip(options, st.columns(len(options) + 3)):
                if col.button(option, key=f"quick_{option}_{len(st.session_state.messages)}"):
                    st.session_state.pending_prompt = option
                    st.rerun()

    typed = st.chat_input("Nhập yêu cầu cho agent...", disabled=not key_ok(settings["provider"]))
    user_text = typed or st.session_state.pop("pending_prompt", None)
    if not user_text:
        return

    st.session_state.messages.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    messages = [{"role": "system", "content": prompt_path.read_text(encoding="utf-8")},
                *trim_history(st.session_state.history, settings["window"]),
                {"role": "user", "content": user_text}]
    events, rounds, awaiting = [], [], None
    with st.chat_message("assistant"):
        with st.status("Agent đang chọn tool và gọi model...", expanded=False) as status:
            try:
                result = run_model_tool_loop(provider=make_provider(settings["provider"]), messages=messages,
                                             tools=to_openai_tools(load_tool_declarations(tools_path)),
                                             model=settings["model"], max_tool_rounds=settings["rounds"])
                state, answer = result["status"], result["assistant_text"] or "_(model không trả về text)_"
                events, rounds = result.get("tool_events", []), result.get("rounds", [])
                if state == "waiting_for_user" and events:
                    awaiting = events[-1].get("result")
                status.update(label=f"Xong · {len(events)} lời gọi tool · {state}", state="complete")
            except Exception as exc:
                state, answer = "provider_error", f"**Lỗi gọi model** `{type(exc).__name__}`: {exc}"
                status.update(label="Lỗi gọi model", state="error")
        st.markdown(answer)
        render_tool_events(events)

    st.session_state.messages.append({"role": "assistant", "content": answer, "events": events, "awaiting": awaiting})
    if state != "provider_error":
        st.session_state.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]

    if st.session_state.get("transcript") is None:
        st.session_state.transcript = {
            "transcript_id": "_".join([safe_slug(version), safe_slug(settings["provider"]), datetime.now().strftime("%Y%m%dT%H%M%S%f")]),
            **artifact_version_dict(av), "provider": settings["provider"], "model": settings["model_label"],
            "system_prompt": str(prompt_path), "tools": str(tools_path), "source": "streamlit_chat",
            "history_window": settings["window"], "max_tool_rounds": settings["rounds"],
            "created_at": now_iso(), "updated_at": now_iso(), "turns": [],
        }
    transcript = st.session_state.transcript
    transcript["turns"].append({"turn_index": len(transcript["turns"]) + 1, "started_at": now_iso(), "user": user_text,
                                "status": state, "assistant_text": answer, "rounds": rounds, "tool_events": events,
                                "ended_at": now_iso()})
    write_transcript(D.TRANSCRIPTS_DIR / f"{transcript['transcript_id']}.transcript.json", transcript)
    st.rerun()


def page_run_eval() -> None:
    settings = sidebar_live_settings()
    st.title("Chạy eval")
    st.caption("Chạy run_eval.py với provider thật, kết quả ghi vào runs/ và xuất hiện ngay ở trang So sánh phiên bản.")
    all_runs, _ = runs()
    datasets = sorted(p.name for p in D.DATA_DIR.glob("eval_*.json"))
    c1, c2, c3 = st.columns(3)
    version = c1.text_input("Version label", value=D.next_version_label([r.version for r in all_runs]))
    dataset = c2.selectbox("Bộ case", datasets, index=datasets.index("eval_base.json") if "eval_base.json" in datasets else 0)
    suite = c3.selectbox("Suite label", ["base", "group", "extension", "cross"],
                         index={"eval_base.json": 0, "eval_group.json": 1, "eval_research_extension.json": 2}.get(dataset, 0))
    st.warning("Tốn credit API. Quy ước nhóm: chỉ người phụ trách version chạy eval chính thức và ghi version_log.csv.")
    if not st.button("Chạy eval", type="primary", disabled=not key_ok(settings["provider"])):
        return
    n_cases = len(json.loads((D.DATA_DIR / dataset).read_text(encoding="utf-8"))["cases"])
    command = [sys.executable, "run_eval.py", "--provider", settings["provider"], "--version", version,
               "--suite", suite, "--eval-cases", f"data/{dataset}"] + (["--model", settings["model"]] if settings["model"] else [])
    progress = st.progress(0.0, text="Bắt đầu...")
    lines = []
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
    done = 0
    for line in process.stdout:
        lines.append(line.rstrip())
        if line.startswith("Running "):
            done += 1
            progress.progress(min(done / max(n_cases, 1), 1.0), text=line.strip())
    process.wait()
    progress.progress(1.0, text="Hoàn tất" if process.returncode == 0 else "Lỗi")
    st.code("\n".join(lines[-40:]), language="text")
    if process.returncode == 0:
        st.success("Đã lưu run mới.")
        st.page_link(PAGES["compare"], label="Xem so sánh phiên bản", icon=":material/arrow_forward:")


PAGES = {
    "overview": st.Page(page_overview, title="Tổng quan", icon=":material/home:", url_path="overview", default=True),
    "compare": st.Page(page_compare, title="So sánh phiên bản", icon=":material/compare_arrows:", url_path="compare"),
    "cases": st.Page(page_cases, title="Soi từng case", icon=":material/search:", url_path="cases"),
    "run_eval": st.Page(page_run_eval, title="Chạy eval", icon=":material/play_circle:", url_path="run-eval"),
    "chat": st.Page(page_chat, title="Chat với agent", icon=":material/chat:", url_path="chat"),
}
st.navigation({
    "Giới thiệu": [PAGES["overview"]],
    "Đánh giá offline": [PAGES["compare"], PAGES["cases"], PAGES["run_eval"]],
    "Trải nghiệm live": [PAGES["chat"]],
}, expanded=True).run()
