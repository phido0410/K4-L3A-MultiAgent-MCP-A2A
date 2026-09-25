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
| Order/item | `case: dict` | Truy vấn trạng thái đơn hàng, danh sách item, tính tổng giá trị đơn hàng `order_total_brl`, xác định seller và phát tín hiệu trạng thái đơn (`ORDER_STATUS_*`). **Quyền gọi tool:** `get_order`, `get_order_items`, `get_sellers`. | `Finding` (actor=`order-agent`, signals, entities, facts, evidence) bàn giao cho Coordinator, chia sẻ facts cho Payment Agent và Shipment Agent |
| Payment | TODO | TODO | TODO |
| Shipment | `case: dict`, `order_finding: Finding` (tùy chọn) | Truy vấn tóm tắt tiến trình vận chuyển, kiểm toán các mốc thời gian, xác định nguyên nhân trễ hạn (do seller bàn giao muộn `SHIP_LATE_SELLER` hay do carrier vận chuyển chậm `SHIP_LATE_LOGISTICS`, hoặc đúng hạn `SHIP_ON_TIME`), phát hiện xung đột mốc thời gian với order. **Quyền gọi tool:** `get_shipment_summary`. | `Finding` (actor=`shipment-agent`, signals, facts, ranked_causes, responsible_parties, conflicts, evidence) bàn giao cho Coordinator và Verifier |
| Policy | TODO | TODO | TODO |
| Verifier | TODO | TODO | TODO |

### Phân quyền gọi MCP Tools theo Actor
- **Order/item Agent (`order-agent`):** Được cấp quyền gọi `get_order`, `get_order_items`, `get_sellers`.
- **Shipment Agent (`shipment-agent`):** Được cấp quyền gọi `get_shipment_summary`.
- Tuyệt đối không cho phép agent tự do gọi các tool ngoài domain của mình để tránh lãng phí ngân sách call budget và vi phạm nguyên tắc audit.

## 3. A2A protocol

Mô tả message envelope, correlation theo `case_id`, điều kiện handoff, timeout và cách tránh vòng lặp. Chỉ trace sự kiện/decision code quan sát được; không trace nội dung suy luận riêng.

## 4. Evidence lifecycle

Mô tả cách validate MCP response, lưu `evidence_ref`, map evidence vào claim/output và emit `tool_result_consumed`. Evidence không được tái sử dụng giữa các case.

## 5. Failure policy

| Failure | Retry? | Fallback | Trace event/code |
| --- | --- | --- | --- |
| MCP timeout | TODO | TODO | TODO |
| Not found | TODO | TODO | TODO |
| Source conflict | TODO | TODO | TODO |
| Invalid specialist result | TODO | TODO | TODO |

Retry phải có giới hạn và idempotent. Không chuyển missing evidence thành dữ liệu phỏng đoán.

## 6. Verification invariants

Liệt kê kiểm tra trước finalize: schema, entity scope, evidence ownership, claim linkage, money totals, responsibility/action consistency và confidence bounds.

## 7. Reproducibility

Ghi model/config, dependency pinning, concurrency limit, random seed (nếu có), lệnh chạy và các giới hạn tài nguyên. Không ghi API key.
