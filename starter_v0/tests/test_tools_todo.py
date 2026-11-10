"""TODO(student): Tool Unit Test Challenge.

Each test below is a stub. Replace `pytest.skip(...)` with a real test.
Patterns to copy are in test_tools_examples.py. Fixtures are in conftest.py.

Rules:
- Offline only: mock HTTP with `fake_http`, set fake keys with `monkeypatch.setenv`.
- One behaviour per test. Name the test after the behaviour, not the function.
- Done = `pytest tests/ -v` shows 0 skipped, 0 failed.
"""
from __future__ import annotations

from conftest import FakeResponse  # noqa: F401  (you will need it)
from tools import TOOL_FUNCTIONS  # noqa: F401

# ---------------- clarify ----------------

def test_clarify_choice_returns_options_and_awaits_user() -> None:
    result = TOOL_FUNCTIONS["clarify"](
        question="Bạn muốn xem nguồn nào?", response_type="choice", options=["Web", "Twitter"]
    )

    assert result["options"] == ["Web", "Twitter"]
    assert result["response_type"] == "choice"
    assert result["awaiting_user"] is True


# ---------------- format ----------------

def test_format_sections_groups_items_by_section() -> None:
    items = [
        {"title": "a1", "url": "https://a.com/1", "section": "A"},
        {"title": "b1", "url": "https://b.com/1", "section": "B"},
        {"title": "a2", "url": "https://a.com/2", "section": "A"},
    ]
    markdown = TOOL_FUNCTIONS["format"](items=items, template="sections")["markdown"]

    assert markdown.count("## A") == 1
    assert markdown.count("## B") == 1
    assert markdown.index("a2") < markdown.index("## B")  # a2 grouped under A


def test_format_thread_numbers_items() -> None:
    items = [{"title": f"Tin {i}", "url": f"https://x.com/{i}"} for i in range(3)]
    markdown = TOOL_FUNCTIONS["format"](items=items, template="thread")["markdown"]

    assert [part.split(" ")[0] for part in markdown.split("\n\n")] == ["1/", "2/", "3/"]


def test_format_empty_items_does_not_crash() -> None:
    for items in (None, []):
        result = TOOL_FUNCTIONS["format"](items=items, template="sections")
        assert result["item_count"] == 0
        assert result["markdown"] == ""


# ---------------- send (guardrail) ----------------

def test_send_confirmed_posts_to_telegram(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001")
    calls = fake_http(FakeResponse({"ok": True}))

    result = TOOL_FUNCTIONS["send"](text="Bản tin AI", confirmed=True)

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert "bot123:abc/sendMessage" in calls[0]["url"]
    assert calls[0]["json"]["chat_id"] == "-1001"
    assert calls[0]["json"]["text"] == "Bản tin AI"
    assert result["status"] == "sent"


def test_send_confirmed_without_env_returns_error_and_no_request(fake_http) -> None:
    calls = fake_http(FakeResponse({"ok": True}))

    result = TOOL_FUNCTIONS["send"](text="Bản tin AI", confirmed=True)

    assert calls == []
    assert result["error"] == "RuntimeError"
    assert "TELEGRAM_BOT_TOKEN" in result["message"]


# ---------------- lookup ----------------

def test_lookup_without_timeframe_omits_time_range(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    calls = fake_http(FakeResponse({"results": []}))

    result = TOOL_FUNCTIONS["lookup"](query="AI", topic="news", timeframe=None)

    assert "time_range" not in calls[0]["json"]
    assert calls[0]["json"]["topic"] == "news"
    assert result["items"] == []


# ---------------- fetch ----------------

def test_fetch_maps_firecrawl_response(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
    calls = fake_http(FakeResponse({"data": {
        "markdown": "Nội dung bài",
        "metadata": {"title": "T", "sourceURL": "https://www.openai.com/blog/x"},
    }}))

    result = TOOL_FUNCTIONS["fetch"](url="https://www.openai.com/blog/x")

    assert calls[0]["url"] == "https://api.firecrawl.dev/v1/scrape"
    assert calls[0]["json"]["url"] == "https://www.openai.com/blog/x"
    assert calls[0]["headers"]["Authorization"] == "Bearer fc-key"
    assert result["items"][0] == {
        "title": "T", "url": "https://www.openai.com/blog/x",
        "source": "openai.com", "summary": "Nội dung bài",
    }


def test_fetch_truncates_markdown_to_4000_chars(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
    fake_http(FakeResponse({"data": {"markdown": "x" * 5000, "metadata": {}}}))

    summary = TOOL_FUNCTIONS["fetch"](url="https://example.com/a")["items"][0]["summary"]

    assert len(summary) == 4000


# ---------------- timeline / social_search ----------------

def test_timeline_respects_limit_and_skips_items_without_id(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    raw = [{"text": "no id", "screen_name": "sama"}] + [
        {"tweet_id": str(100 + i), "text": f"tweet {i}", "screen_name": "sama"} for i in range(6)
    ]
    calls = fake_http(FakeResponse({"timeline": raw}))

    result = TOOL_FUNCTIONS["timeline"](screenname="sama", limit=3)

    assert calls[0]["params"] == {"screenname": "sama"}
    assert [item["url"] for item in result["items"]] == [
        "https://x.com/sama/status/100", "https://x.com/sama/status/101", "https://x.com/sama/status/102",
    ]


def test_social_search_passes_search_type(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    calls = fake_http(FakeResponse({"timeline": []}))

    TOOL_FUNCTIONS["social_search"](query="OpenAI", search_type="Top")

    assert calls[0]["url"].endswith("/search.php")
    assert calls[0]["params"] == {"query": "OpenAI", "search_type": "Top"}
    assert calls[0]["headers"]["x-rapidapi-key"] == "rk"


# ---------------- policy (local knowledge + trust boundary) ----------------

def test_policy_empty_query_returns_no_results() -> None:
    for query in ("", "   ", "là và của"):  # empty, blank, stopwords only
        assert TOOL_FUNCTIONS["policy"](query=query)["results"] == []


def test_policy_area_filter_only_returns_that_area() -> None:
    results = TOOL_FUNCTIONS["policy"](
        query="API key dữ liệu khách hàng prompt", policy_area="data_privacy", top_k=5
    )["results"]

    assert results
    assert {item["policy_area"] for item in results} == {"data_privacy"}


def test_policy_instruction_like_lines_go_to_untrusted_text() -> None:
    results = TOOL_FUNCTIONS["policy"](
        query="viral tweet verified fact citation", policy_area="source_citation", top_k=10
    )["results"]
    hit = next(item for item in results if any("viral tweet" in line for line in item["untrusted_text"]))

    assert "ignore the citation policy" not in hit["facts"]
    assert any("ignore the citation policy" in line for line in hit["untrusted_text"])


# ---------------- YOUR NEW TOOL(S) ----------------
# Write at least 3 tests per tool your team adds:
#   1. happy path (mocked if it calls an API)
#   2. bad / missing input from the model (empty string, wrong type, out-of-enum value)
#   3. failure path (missing key, HTTP error, timeout) -> returns error dict, does not raise

def test_calculator_happy_path() -> None:
    result = TOOL_FUNCTIONS["calculator"]("27 * 14")

    assert result["result"] == 378
    assert result["tool"] == "calculator"


def test_calculator_empty_input_returns_error() -> None:
    result = TOOL_FUNCTIONS["calculator"]("")

    assert result.get("error") == "ValueError"


def test_calculator_rejects_unsupported_python_code() -> None:
    result = TOOL_FUNCTIONS["calculator"]("__import__('os').getcwd()")

    assert result.get("error") == "ValueError"


def test_my_new_tool_happy_path() -> None:
    result = TOOL_FUNCTIONS["summarize"]("  Tin   tức về AI hôm nay.  ", max_chars=18)

    assert result["tool"] == "summarize"
    assert result["summary"] == "Tin tức về AI hôm..."
    assert result["original_chars"] > len(result["summary"])


def test_my_new_tool_bad_input_from_model() -> None:
    result = TOOL_FUNCTIONS["summarize"]("", max_chars=100)

    assert result["error"] == "ValueError"


def test_my_new_tool_failure_returns_error_dict() -> None:
    result = TOOL_FUNCTIONS["summarize"]("Nội dung", max_chars=0)

    assert result["error"] == "ValueError"


def test_calculator_respects_operator_precedence_and_float_division() -> None:
    assert TOOL_FUNCTIONS["calculator"]("(120 / 5) + 3 * 2")["result"] == 30.0
    assert TOOL_FUNCTIONS["calculator"]("-2 ** 2")["result"] == -4


def test_calculator_accepts_number_sent_as_non_string() -> None:
    # Models sometimes send a bare number instead of a string expression.
    assert TOOL_FUNCTIONS["calculator"](42)["result"] == 42
    assert TOOL_FUNCTIONS["calculator"](None)["error"] == "ValueError"


def test_calculator_division_by_zero_returns_error_dict() -> None:
    result = TOOL_FUNCTIONS["calculator"]("1 / 0")

    assert result["error"] == "ZeroDivisionError"
    assert "result" not in result


def test_calculator_huge_power_is_rejected_quickly() -> None:
    # Regression: "9**9**9" used to hang the agent, and "2**200000" returned a number too
    # large to serialize into the tool-results JSON.
    for expression in ("9**9**9", "2**200000", "10**101"):
        assert TOOL_FUNCTIONS["calculator"](expression)["error"] == "ValueError"
    assert TOOL_FUNCTIONS["calculator"]("2**10")["result"] == 1024
