# L3A Architecture Record

Team phải cập nhật tài liệu này cùng source. Mục tiêu là mô tả quyết định có thể kiểm chứng, không ghi prompt bí mật hoặc chain-of-thought.

## 1. System overview

```text
inputs/<case_id>.json
        │
        ▼
   cli.py::_run ──► emit case_received (actor=coordinator)
        │
        ▼
   workflow.py::solve_case  ─── Coordinator, không tự gọi MCP
        │
        ├─► order-agent     ──┐
        ├─► shipment-agent  ──┤  mỗi agent nhận một AgentContext
        ├─► payment-agent   ──┤  (allowlist tool + case_id cố định)
        └─► policy-agent    ──┘        │
                                       ▼
                              MCP Evidence Gateway
                                       │
                          data + evidence_ref  ──► emit tool_result_consumed
                                       │
        ┌──────────────────────────────┘
        ▼
   domain/rules.py::decide  ──► emit policy_decided
        │   (nơi DUY NHẤT quyết định primary_issue)
        ▼
   domain/money.py::compute_refund
        ▼
   agents/verifier.py::verify ──► emit verification_completed
        │   pass → outputs/<case_id>.json
        │   fail → raise, không ghi output sai
        ▼
   cli.py ──► emit case_finalized
```

Specialist agent không kết luận `primary_issue`. Mỗi agent chỉ phát **tín hiệu** chuẩn hoá (`domain/findings.py`) và **số liệu** (`facts`). Coordinator ghép tín hiệu từ cả bốn agent rồi mới ra kết luận. Tách như vậy để: một agent hỏng không kéo theo kết luận sai, và toàn bộ luật quyết định nằm ở một chỗ duy nhất để review.

## 2. Agent ownership

| Actor | Input | Trách nhiệm | Tool được cấp | Output/handoff |
| --- | --- | --- | --- | --- |
| Coordinator | `case` | Giao việc tuần tự, ghép tín hiệu, dựng output, chạy verifier | *không được gọi tool* | → order-agent |
| Order/item | `claimed_order_id` | Trạng thái đơn, item, seller, tổng tiền đơn | `get_order`, `get_order_items`, `get_sellers`, `get_product_context` | `Finding` → shipment-agent |
| Shipment | `claimed_order_id` | Timeline giao hàng, quy trách nhiệm trễ | `get_shipment_summary` | `Finding` → payment-agent |
| Payment | `claimed_order_id` + `order_total_brl`, `order_purchase_timestamp` từ order-agent | Lọc event theo cửa sổ `[purchase, opened_at]` để loại dòng nhiễu; phân loại `PAY_*` và `REFUND_*` | `get_payment_timeline`, `get_refund_timeline` | `Finding` (facts: `captured_total_brl`, `refunded_total_brl`, `duplicate_amount_brl`, `payment_reason`) → policy-agent |
| Policy | `policy_version` + `primary_issue` + `seller_ids` | Áp rule của issue: `case_status`, `resolution_actions`, `refund_brl`, `responsible_parties` (gắn seller thật của case). Gọi riêng từng case, không cache | `get_policy` | `Finding` `POLICY_*` → `money.compute_refund()` và verifier |
| Verifier | output nháp | 8 bất biến trước finalize | *không được gọi tool* | pass/fail |

Allowlist được cưỡng chế trong code tại `a2a.py::TOOL_SCOPES`; gọi tool ngoài phạm vi ném `ToolScopeError`. Coordinator và verifier không có scope nào — mọi truy vấn evidence phải đi qua specialist, để trace luôn quy được evidence về đúng actor.

`get_customer_history` tồn tại trên gateway nhưng không cấp cho actor nào: L3A chỉ điều tra một đơn theo `claimed_order_id`, không cần mở rộng sang lịch sử khách.

## 3. A2A protocol

**Envelope.** `a2a.py::Task` gồm `case_id`, `actor`, `order_id`, `policy_version`. Mỗi task sinh ra đúng một `AgentContext`; context giữ `case_id` bất biến và tự nhét vào mọi call, nên agent không có đường truyền sai case.

**Correlation.** Mọi trace event mang `case_id` của task. `cli.py` chạy tuần tự từng case và ghi trace theo thứ tự thời gian, nên `case_received` luôn đứng trước và `case_finalized` luôn đứng sau các event của case đó.

**Handoff.** Chuỗi cố định, một chiều, không nhánh:

```text
coordinator → order-agent → shipment-agent → payment-agent → policy-agent → verifier
```

Mỗi bước emit `task_assigned` (actor=coordinator, target=agent) trước khi chạy và `handoff` (actor=agent, target=agent kế tiếp) sau khi xong, kèm `decision_code` và danh sách signal trong `attributes`.

**Timeout.** `AGENT_TIMEOUT_SECONDS = 120` cho một lượt agent. Quá hạn thì `decision_code=AGENT_TIMEOUT`, agent trả `Finding` rỗng, pipeline đi tiếp.

**Chống vòng lặp.** Hai lớp: chuỗi handoff là tuyến tính không quay lui, và mỗi `AgentContext` có trần `MAX_CALLS_PER_AGENT = 8` call cho một case. Vượt trần ném `RuntimeError`, bị bắt và ghi thành `AGENT_ERROR_RuntimeError`.

Trace chỉ ghi sự kiện và decision code quan sát được. Không ghi prompt, không ghi nội dung suy luận.

## 4. Evidence lifecycle

1. **Validate.** `EvidenceGateway.call()` kiểm tra mọi response theo `mcp-evidence-response-v1`. Agent kiểm tra thêm scope: `data.order_id` phải bằng `claimed_order_id` và policy phải đúng `policy_version` của case. Sai scope thì bỏ response, không cite.
2. **Lọc nhiễu.** Response trộn dòng thật với dòng của kịch bản khác. Chỉ giữ event có `order_purchase_timestamp <= event_at <= opened_at` (so `datetime` có timezone, không so chuỗi). `get_order_payments` không có timestamp nên không dùng; dùng `get_payment_timeline`.
3. **Lưu ref.** `evidence_ref` được lấy nguyên văn vào `EvidenceItem(evidence_ref, domain, tool_name)`. Không sửa, không tự tạo, không cache qua case: mỗi case gọi lại tool của chính nó.
4. **Chỉ cite cái dẫn tới kết luận.** Điểm evidence là F1, cite thừa bị phạt như cite thiếu.
   - Payment timeline: cite khi đọc được, vì mọi tín hiệu `PAY_*` dựa trên nó.
   - Refund timeline: cite chỉ khi có event refund **trong cửa sổ**. Nếu chỉ có dòng nhiễu hoặc tool báo lỗi (đơn không có refund), kết luận `REFUND_NONE` và không cite.
   - Policy: cite khi áp được rule cho `primary_issue` (`insufficient_evidence` không có rule nên không cite).
5. **Trace.** Mỗi ref được cite có đúng một `tool_result_consumed` (actor, `tool_name`, `decision_code` = tín hiệu chính, `evidence_refs`). Policy agent emit thêm `policy_decided` với `decision_code` = `recommended_action`.
6. **Map vào output.** `evidence_refs` của output = hợp các ref đã cite. `claim_assessments[].evidence_refs` = ref của agent hỗ trợ claim đó (claim thanh toán lấy payment/refund; `requested_full_refund` lấy thêm policy).

## 5. Failure policy

| Failure | Retry? | Fallback | Trace event/code |
| --- | --- | --- | --- |
| MCP timeout / lỗi transport | Có: tối đa 2 lần (`MAX_ATTEMPTS`), tool chỉ đọc nên idempotent | Payment: `PAY_NONE`, confidence 0.2. Policy: không áp rule, `request_more_evidence`. Không cite gì | `facts.errors[<tool>]`; rules đưa về `insufficient_evidence` / `needs_investigation` |
| Not found | Có, 1 lần (gateway không phân biệt not-found với lỗi khác) | `get_refund_timeline` lỗi ổn định = đơn không có refund → `REFUND_NONE`, không cite | `tool_result_consumed` không được emit cho tool đó |
| Source conflict | Không | Tổng thu (payment) ≠ tổng đơn (order) kèm event `reconciliation_mismatch` mở → chọn nguồn `payment` | `data_conflicts`: `{"field": "payment_total_brl", "sources": ["order","payment"], "selected_source": "payment", "resolution_code": "PAYMENT_RECONCILIATION_OPEN"}` |
| Evidence sai scope (order/policy version khác) | Không | Bỏ response, coi như không có evidence | `facts.errors` / `policy_error` |
| Invalid specialist result | Không | Verifier chạy `money.check_money_invariants()`; vi phạm → không finalize bản đó, hạ về `needs_investigation` với refund 0 | `verification_completed` với `decision_code` báo lỗi |

Retry phải có giới hạn và idempotent. Không chuyển missing evidence thành dữ liệu phỏng đoán.

## 6. Verification invariants

`agents/verifier.py::verify` chạy trước khi ghi output. Fail thì `solve_case` ném lỗi và **không** ghi file — thà thiếu output còn hơn nộp output sai.

| Mã | Bất biến |
| --- | --- |
| V1 | `output.case_id` khớp `case.case_id` |
| V2 | Mọi `evidence_refs` đến từ call MCP của chính case này |
| V3 | `claim_id` tồn tại trong input; ref trong claim cũng thuộc case này |
| V4 | Mỗi mảng entity không trùng lặp và không vượt 20 phần tử |
| V5 | Bất biến tài chính M1–M6 (`domain/money.py`) |
| V6 | `resolution_actions` nằm trong danh sách đóng; `action_required` phải có hành động; `no_action` không được đề xuất hành động |
| V7 | `confidence` nằm trong [0, 1] |
| V8 | Mỗi `data_conflicts` có ít nhất 2 `sources` |

| Mã | Bất biến tài chính |
| --- | --- |
| M1 | `sum(refund_lines.amount_brl)` == `recommended_refund_brl` (dung sai 0.01 BRL) |
| M2 | `case_status == no_action` ⇒ `recommended_refund_brl == 0` |
| M3 | Không có số tiền âm |
| M4 | `reason_code` nằm trong danh sách đóng |
| M5 | `currency == "BRL"` |
| M6 | Không hoàn nhiều hơn số đã thu |

Schema công khai được kiểm riêng ở `cli.py` sau khi `solve_case` trả về, nên một output sai schema không bao giờ chạm tới đĩa.

## 7. Reproducibility

**Môi trường**

| Mục | Giá trị |
| --- | --- |
| Python | 3.11.4 (`pyproject.toml` yêu cầu >= 3.11) |
| Cài đặt | `python3.11 -m venv .venv && pip install -e ".[dev]"` |
| Dependency chính | `mcp` 2.2.0, `httpx2` 2.13.1, `jsonschema` 4.26.0, `python-dotenv` 1.2.3 |
| Dev | `pytest` 8.4.2, `ruff` 0.16.9 |
| CI | `.github/workflows/quality.yml` — `ruff check .` + `pytest -q` trên Python 3.11 |

**Lệnh chạy**

```bash
day09 validate-inputs
day09 run
day09 validate
day09 package --output dist/submission.zip
```

**Tính tất định.** Không dùng LLM, không dùng random seed. Toàn bộ luật là hàm thuần trên dữ liệu MCP trả về, nên cùng input và cùng evidence sẽ cho cùng output. Hai nguồn không tất định còn lại là `event_id` (`secrets.token_urlsafe`) và `occurred_at`, cả hai đều không tham gia vào kết luận.

**Giới hạn tài nguyên.** Case chạy tuần tự, không song song. Mỗi agent tối đa 8 call MCP cho một case, timeout 120 giây một lượt agent; trần lý thuyết 32 call cho một case.

**Bí mật.** `COMPETITION_TEAM_API_KEY` chỉ đọc từ `.env` (đã gitignore). `.env.example` luôn giữ placeholder `sk-team-replace_me`, có test tự động canh (`tests/test_release_safety.py`). `submission.py` quét secret trong output và trace trước khi đóng gói.
