---
name: summarize
track: core
kind: local_formatter
provider: Python standard library
requires_env: []
inputs: [text, max_chars]
outputs: [summary, original_chars]
side_effect: false
---

# summarize

Rút gọn một đoạn văn bản đã có bằng cách giữ phần đầu trong giới hạn ký tự.

Dùng khi người dùng muốn tóm tắt nội dung đã cung cấp hoặc nội dung đã được tool khác lấy về. Không dùng để tìm dữ liệu mới.