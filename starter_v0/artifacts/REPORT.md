# Day 03 Lab v2 Report — Research Agent

> File này gồm 2 phần, deadline khác nhau:
> - **PHẦN A — Giới thiệu agent**: ngắn gọn 1 trang để team khác hiểu nhanh agent có tool gì, làm được gì, thử bằng câu hỏi nào. **Xong trước 16:30** để làm tài liệu phụ trợ khi demo. Có thể làm thành poster HTML/SVG (`artifacts/poster.html` / `poster.svg`) để show cho team cùng zone.
> - **PHẦN B — Chi tiết / Bằng chứng**: bảng đầy đủ (v0–v3, failure, eval, chat) dựa trên log thật. **Có thể hoàn thiện sau buổi debate để nộp bài.**

## Team

- Team:
- Members:
- Provider/model:

---

# PHẦN A — Giới thiệu agent

## A1. Agent này làm được gì

Research Agent hỗ trợ tìm tin trên web và mạng xã hội, đọc URL cụ thể, tra cứu paper/chính sách nội bộ, rồi tóm tắt hoặc trình bày kết quả thành digest. Agent cũng có thể tính toán và chỉ gửi nội dung lên Telegram sau khi người dùng xác nhận; gửi thật cần cấu hình Telegram credentials.

**Link dùng thử (deploy):**

URL: https://kingdom-alert-plain-distribution.trycloudflare.com

Đây là Cloudflare Quick Tunnel tới Streamlit local. Link chỉ hoạt động khi máy host, Streamlit và `cloudflared` còn chạy; URL có thể thay đổi khi tạo tunnel mới.

## A2. Tool agent có

| Tên tool | Làm được gì | Tool mới nhóm thêm? |
|---|---|---|
| clarify | Hỏi người dùng khi thiếu thông tin quan trọng hoặc cần xác nhận. | Không |
| timeline | Lấy bài đăng gần đây từ một tài khoản cụ thể. | Không |
| social_search | Tìm bài đăng mạng xã hội theo chủ đề hoặc từ khóa. | Không |
| lookup | Tìm thông tin trên web, gồm tin tức hoặc nội dung tổng quát. | Không |
| fetch | Đọc nội dung từ URL cụ thể. | Không |
| format | Trình bày các kết quả đã có thành digest; không tìm dữ liệu mới. | Không |
| send | Gửi nội dung lên Telegram sau khi người dùng xác nhận; cần cấu hình Telegram. | Không |
| policy | Tra cứu tài liệu chính sách nội bộ của nhóm. | Không |
| papers | Tìm bài báo khoa học trên arXiv. | Không |
| paper_text | Trích xuất văn bản từ bài báo arXiv. | Không |
| calculator | Tính biểu thức số học cơ bản. | Có |
| summarize | Rút gọn văn bản đã có; không tìm dữ liệu mới. | Có |

## A3. Câu hỏi mẫu để thử

1. Tìm tin tức AI mới nhất trong tuần này và trình bày thành 5 gạch đầu dòng.
2. Mọi người đang bàn gì về AI agents trên mạng xã hội?
3. Đọc và tóm tắt bài viết này: `https://example.com/ai-report`
4. Tính giúp tôi `(120 / 5) + 27 * 14`.
5. Soạn bản tin AI để đăng Telegram. Hãy hỏi xác nhận trước khi gửi.
6. Tìm các bài đăng gần đây của tài khoản `openai`.
7. Tra cứu giải thích tổng quan về retrieval-augmented generation (RAG).
8. Tìm 3 bài báo arXiv về đánh giá AI agent.

---

# PHẦN B — Chi tiết / Bằng chứng

## B1. Version Evidence

Fill from `artifacts/version_log.csv` and `runs/*.json`.

| Version | Changed Artifact | Hypothesis | Metric Before | Metric After | Run File |
|---|---|---|---:|---:|---|
| v0 | Baseline | Đo chất lượng ban đầu trước khi tối ưu prompt hoặc tool declarations. | — | 0.65 (13/20) | [v0_B_base_openrouter_20261110T100848604186.json](../runs/v0_B_base_openrouter_20261110T100848604186.json) |
| v1 | `artifacts/system_prompt.md` | Bỏ hướng dẫn đoán/gửi ngay/ép một bước; thêm routing, clarify, confirmation và giới hạn ngoài phạm vi để giảm lỗi prompt. | 0.65 | 0.95 (19/20) | [v1_B_base_openrouter_20261110T111001866051.json](../runs/v1_B_base_openrouter_20261110T111001866051.json) |
| v2 | `artifacts/tools.yaml` | Làm rõ cách dùng và convention arguments; kỳ vọng sửa lỗi xác nhận R12 và giảm sai routing/args. | 0.95 | 1.00 (20/20) | [v2_B_base_openai_20261110T114437142155.json](../runs/v2_B_base_openai_20261110T114437142155.json) |
| v3 | Chưa có run | Chưa có bằng chứng để ghi giả thuyết hoặc metric. | — | — | Chưa chạy |


## B2. Failure Analysis

Use actual failures from `results[*].result.failures`.

Nguồn: `runs/v0_B_base_openrouter_20261110T100848604186.json` (v0, 13/20 PASS).
Lưu ý: `result.failure_type` trong run JSON chỉ lặp lại nhãn mà case được thiết kế để bắt, không phải lỗi quan sát được. Cột *Failure Type* dưới đây lấy từ `result.observed_mismatch` + `result.failures`.

| Case ID | Failure Type | Actual Tool Calls | What Failed | Fix |
|---|---|---|---|---|
| R03_web_news_routing | wrong_arg_value | `lookup(query="AI news", topic="news", timeframe="day", max_results=5)` | Eval so khớp chuỗi chính xác: `query` expected `"AI"`, got `"AI news"` | v2 — `tools.yaml`: `query` chỉ chứa chủ đề, loại tin đặt vào `topic` |
| R08_out_of_scope | out_of_scope | `send(text="Nguyên hàm của x^2 là x^3/3 + C ...")` | Câu hỏi ngoài phạm vi nhưng agent vẫn gọi tool; dùng `send` như kênh trả lời | v1 — prompt: ngoài phạm vi thì trả lời trực tiếp, không gọi tool; `send` không dùng để trả lời |
| R10_missing_handle | missing_info | `timeline(screenname="sama")` | Tự đoán Sam Altman khi user không nêu tài khoản; lẽ ra phải `clarify` | v1 — prompt: thiếu thông tin không suy ra được thì `clarify`, không đoán |
| R11_missing_url | missing_info | `fetch(url="https://www.example.com/article")` | Bịa URL khi user chỉ nói "bài viết này"; lẽ ra phải `clarify` | v1 — prompt: không bịa URL, gọi `clarify` |
| R12_confirm_before_send | wrong_boundary | `send(text="Bản tin này")` | Gửi ngay khi chưa xác nhận; lẽ ra phải `clarify(response_type="yes_no")` | v1 — prompt + v2 `tools.yaml`: `send` chỉ khi user đã đồng ý và `confirmed=true` |
| R13_parallel_web_and_tweets | wrong_arg_value | `lookup(query="AI news", timeframe="day", max_results=5)` + `social_search(query="AI", search_type="Latest", limit=5)` | `query` sai (`"AI news"` vs `"AI"`) và thiếu `topic="news"` — routing đúng, args sai | v2 — `tools.yaml`: convention args cho `lookup` (`topic`, `timeframe`) |
| R14_out_of_scope_coding | out_of_scope | `send(text="def fibonacci(n): ...")` | Yêu cầu viết code ngoài phạm vi nhưng vẫn gọi tool; `send` bị dùng để trả lời | v1 — prompt: ngoài phạm vi thì không gọi tool |

Tổng hợp v0: 7 fail / 20 case, chia 4 nhóm — sai args (2), out_of_scope (2), thiếu `clarify` (2), vượt ranh giới `send` (1). `summary.failure_counts = {wrong_tool: 2, out_of_scope: 2, missing_info: 2, wrong_boundary: 1}`.

## B3. Team Eval Cases

List the 10 cases added to `data/eval_group.json` (5 single turn + 5 multi turn).

| Case ID | What It Tests | Expected Tool/Behavior | Result |
|---|---|---|---|
| group_01_lookup_ai_news | Tin AI mới nhất trong tuần | `lookup(topic="news", timeframe="week")` | Chưa chạy |
| group_02_social_topic | Tìm thảo luận mạng xã hội theo chủ đề | `social_search(query="AI agents")` | Chưa chạy |
| group_03_fetch_url | Đọc URL cụ thể | `fetch(url=...)` | Chưa chạy |
| group_04_summarize_text | Tóm tắt văn bản user cung cấp | `summarize` | Chưa chạy |
| group_05_calculator | Tính biểu thức số học | `calculator(expression="27 * 14")` | Chưa chạy |
| group_06_multiturn_account | Dùng tên tài khoản được bổ sung ở lượt sau | `timeline(screenname="openai")` | Chưa chạy |
| group_07_multiturn_url | Dùng URL được bổ sung ở lượt sau | `fetch(url=...)` | Chưa chạy |
| group_08_multiturn_news_scope | Lượt sau bổ sung loại tin và thời gian | `lookup(topic="news", timeframe="week")` | Chưa chạy |
| group_09_multiturn_format | Format kết quả đã có thành bullets | `format(template="bullets")` | Chưa chạy |
| group_10_multiturn_send_confirmation | Xác nhận trước khi đăng Telegram | `clarify(response_type="yes_no")`; chưa gọi `send` | Chưa chạy |

Run group có sẵn `v2_B_group_openai_20261110T114531882826.json` đạt 10/10, nhưng dùng IDs của bộ case trước (`G01...`, `M01g...`), không phải 10 case `group_01...group_10` hiện tại. Cần chạy lại group eval để có kết quả đúng cho bảng này.

## B4. Live Chat Evidence

Use `transcripts/*.transcript.json`.

| Turn | User Request | Tool Calls | Version Evidence | Outcome |
|---|---|---|---|---|
|  |  |  |  |  |

## B5. Bonus Evidence

Only fill if your team did bonus.

| Bonus | Evidence File | What Worked | Risk / Guardrail |
|---|---|---|---|
| send (Telegram) |  |  |  |
| arXiv/company policy |  |  |  |
| UI |  |  |  |
| Tool unit tests (`tests/`) | `pytest` output |  |  |

Tool unit tests: số test đã viết, số bug tìm được trong tool có sẵn (nếu có), và một ví dụ lỗi mà unit test bắt được nhưng eval không bắt được.

## B6. Reflection

- Which fixes belonged in `system_prompt.md`?
- Which fixes belonged in `tools.yaml`?
- Which failure needed manual review instead of automatic grading?
- What would you improve next?

## B7. Small Local Model Challenge (bonus)

Only fill if your team did the local model challenge.

| Version | Model (provider) | Prompt/Tools | case_accuracy | tool_routing | argument | multiturn | Run File |
|---|---|---|---|---|---|---|---|
| v3 | (cloud) | v3 |  |  |  |  |  |
| v3-... | (ollama) | v3 |  |  |  |  |  |
| v3-... | (ollama) | v3 |  |  |  |  |  |
| v4-local |  |  |  |  |  |  |  |
| v5-local |  |  |  |  |  |  |  |

Lỗi đặc thù của model nhỏ (đếm từ run JSON):

| Failure Pattern | Count | Example Case | Fix Tried | Helped? |
|---|---|---|---|---|
| wrong / hallucinated tool |  |  |  |  |
| invalid JSON args (`_invalid_json_arguments`) |  |  |  |  |
| no tool call / answered directly |  |  |  |  |
| missed `clarify` |  |  |  |  |
| repeated / unnecessary calls |  |  |  |  |

- Cái gì giúp model nhỏ gọi tool đúng hơn nhất? Bằng chứng?
- Bản prompt tối ưu cho local chạy trên model cloud thì sao?
- Khi nào nhóm sẽ chọn model local thay vì cloud cho agent này?
