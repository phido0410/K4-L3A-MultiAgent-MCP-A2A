# L3A Architecture Record

Team phải cập nhật tài liệu này cùng source. Mục tiêu là mô tả quyết định có thể kiểm chứng, không ghi prompt bí mật hoặc chain-of-thought.

## 1. System overview

Vẽ hoặc mô tả luồng từ `inputs/<case_id>.json` đến MCP calls, specialist agents, verifier, output và trace.

```text
Input → Coordinator → Specialists → Verifier → Output
                         │              │
                         └── MCP ───────┴── Trace
```

## 2. Agent ownership

| Actor | Input | Trách nhiệm | Output/handoff |
| --- | --- | --- | --- |
| Coordinator | TODO | TODO | TODO |
| Order/item | TODO | TODO | TODO |
| Payment | `case` + facts của order agent (`order_purchase_timestamp`, `order_total_brl`) | Tools: **chỉ** `get_payment_timeline`, `get_refund_timeline`. Lọc event theo cửa sổ `[purchase, opened_at]` để loại dòng nhiễu; phân loại thanh toán (`PAY_*`) và trạng thái hoàn tiền (`REFUND_*`) | `Finding` gồm signals, `payment_references`, facts (`captured_total_brl`, `refunded_total_brl`, `duplicate_amount_brl`, `payment_reason`, `cause_codes`), conflict lệch tiền → coordinator/rules |
| Shipment | TODO | TODO | TODO |
| Policy | `case` + `primary_issue` do rules quyết + `seller_ids` của order agent | Tool: **chỉ** `get_policy` (gọi riêng cho từng case, không cache). Áp rule của issue: `case_status`, `resolution_actions`, `refund_brl`, `responsible_parties` (seller gắn với seller thật của case); emit `policy_decided` | `Finding` với `POLICY_*` + facts quyết định → `money.compute_refund()` và verifier |
| Verifier | TODO | TODO | TODO |

Nêu rõ actor nào được quyền gọi tool nào. Tránh cho mọi agent quyền truy vấn tất cả tool nếu không cần thiết.

## 3. A2A protocol

Mô tả message envelope, correlation theo `case_id`, điều kiện handoff, timeout và cách tránh vòng lặp. Chỉ trace sự kiện/decision code quan sát được; không trace nội dung suy luận riêng.

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

Liệt kê kiểm tra trước finalize: schema, entity scope, evidence ownership, claim linkage, money totals, responsibility/action consistency và confidence bounds.

## 7. Reproducibility

Ghi model/config, dependency pinning, concurrency limit, random seed (nếu có), lệnh chạy và các giới hạn tài nguyên. Không ghi API key.
