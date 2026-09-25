# Domain notes: Payment / Refund / Policy

Người viết: Quốc. Nguồn: gọi MCP thật trên 17 case (005–009, 015–020, 025–030), ngày 2026-09-25.
Mọi `evidence_ref` trong file này đã được che thành `ev_…`: **không copy ref từ file này vào output**.

## 0. Tóm tắt cho cả nhóm (đọc cái này trước)

1. **Mỗi response trộn dữ liệu thật với một khối nhiễu (distractor).** Khối nhiễu là bản sao dữ liệu của một kịch bản khác, được gắn đúng `order_id` của case, nhưng có mốc thời gian **nằm ngoài cửa sổ** `[order_purchase_timestamp, opened_at]`. Đúng trên cả 17 case đã thử, và cũng xuất hiện ở `get_order_items` (dòng item trùng `order_item_id` với `shipping_limit_date` lệch) → **Bảo cần lọc giống vậy.**
   - Luật lọc: giữ event nếu `order_purchase_timestamp <= event_at <= opened_at` (so sánh `datetime`, có timezone).
   - `get_order_payments` **không có timestamp** → không lọc được. Dùng `get_payment_timeline` (có cả `payments` lẫn `events`) thay cho `get_order_payments`.
2. **`payment_type` không phân biệt split vs duplicate.** Cả hai đều là `credit_card` + `voucher`. Khác nhau ở tổng tiền trong cửa sổ so với tổng đơn (xem mục 4).
3. **`PAY_MISMATCH` phải dựa vào event `reconciliation_mismatch`, không dựa vào so tổng.** Case `refund_failed` có tổng thu 52.00 ≠ tổng đơn 89.00 nhưng **không** phải mismatch.
4. **`get_refund_timeline` trả lỗi khi đơn không có refund** (`Error executing tool get_refund_timeline`, lỗi ổn định, retry 2 lần vẫn vậy). Gặp ở mọi case `duplicate_charge` và `unsupported_claim` đã thử.
5. **Policy `EC_POLICY_V1` giống hệt nhau ở mọi case** và cho sẵn `case_status`, `recommended_action`, `refund_brl`, `responsible_parties` theo từng `primary_issue` (mục 3).
6. **Bug starter kit (Phi):** [mcp_gateway.py:27](../src/student_agent/mcp_gateway.py#L27) dùng `result.isError`, nhưng `mcp` v2 đổi thành `result.is_error` (tương tự `structuredContent` → `structured_content`). Hiện **mọi** `gateway.call()` đều crash với `AttributeError`, dù server đã ghi audit call đó.
7. Với 17 case đã thử, `claims[0].topic` **khớp** với dữ liệu. Nhưng không dùng topic làm đáp án: phần private có thể khác.

## 1. Danh sách tool (từ `day09 mcp-tools`)

| Tool | Tham số (ngoài `case_id`) | `domain` trả về | Ai dùng |
| --- | --- | --- | --- |
| `get_order` | `order_id` | `order` | Bảo |
| `get_order_items` | `order_id` | `item` | Bảo |
| `get_shipment_summary` | `order_id` | ? | Bảo |
| `get_sellers` | `order_id` | ? | Bảo |
| `get_product_context` | `order_id` | ? | Bảo |
| `get_order_payments` | `order_id` | `payment` | (không dùng, xem mục 0.1) |
| **`get_payment_timeline`** | `order_id` | `payment` | **Quốc: payment agent** |
| **`get_refund_timeline`** | `order_id` | `refund` | **Quốc: payment agent** |
| **`get_policy`** | `policy_version` | `policy` | **Quốc: policy agent** |
| `get_customer_history` | `customer_unique_id` | ? | chưa dùng: `get_order` chỉ trả `customer_id` (`customer-row-…`), không có `customer_unique_id` |

Envelope chung (schema `mcp-evidence-response-v1`):

```json
{
  "schema_version": "day09-mcp-evidence-v1",
  "evidence_ref": "ev_…",
  "result_hash": "sha256:…",
  "domain": "payment",
  "data": { … },
  "warnings": []
}
```

`warnings` rỗng ở mọi call đã thử.

## 2. Field thực tế

Mọi số tiền là **chuỗi** (`"44.50"`) → parse bằng `Decimal`. Mọi thời điểm là ISO-8601 có offset `-03:00`.

### `get_payment_timeline` → `data`

| Field | Kiểu | Ghi chú |
| --- | --- | --- |
| `order_id` | str | |
| `payments[]` | list | Giống hệt `get_order_payments.data` |
| `payments[].payment_sequential` | str | `"1"`, `"2"`. **Bị trùng** giữa dòng thật và dòng nhiễu |
| `payments[].payment_type` | str | `credit_card`, `voucher` |
| `payments[].payment_installments` | str | |
| `payments[].payment_value` | str (tiền) | |
| `events[]` | list | Mỗi payment có ≥ 1 event, theo **cùng thứ tự** |
| `events[].event_at` | str (ISO) | **Dùng để lọc cửa sổ** |
| `events[].event_type` | str | Đã thấy: `captured`, `reconciliation_mismatch` |
| `events[].amount_brl` | str (tiền) | |
| `events[].status` | str | `captured` → `confirmed`; `reconciliation_mismatch` → `open` |

`payment_references` cho `affected_entities`: payment không có id riêng. Đề xuất `"<order_id>:<payment_sequential>"` cho các dòng **trong cửa sổ**. Cần chốt ở D4.

### `get_refund_timeline` → `data`

| Field | Kiểu | Ghi chú |
| --- | --- | --- |
| `order_id` | str | |
| `events[].event_at` | str (ISO) | Lọc cửa sổ như payment |
| `events[].event_type` | str | Đã thấy: `refund_requested` |
| `events[].amount_brl` | str (tiền) | |
| `events[].status` | str | Đã thấy: `pending`, `failed` (chưa thấy `completed`) |

Không có refund → tool trả **lỗi**, không trả `events: []`.

### `get_policy` → `data`

```json
{
  "currency": "BRL",
  "policy_version": "EC_POLICY_V1",
  "rules": {
    "<primary_issue>": {
      "case_status": "action_required | no_action | needs_investigation",
      "recommended_action": "…",
      "refund_brl": 0.0,
      "responsible_parties": [{"party_type": "…", "party_id": null}]
    }
  }
}
```

`refund_brl` là **number** (không phải chuỗi như các domain khác).

## 3. Bảng policy `EC_POLICY_V1` (giống nhau ở mọi case)

| `primary_issue` | `case_status` | `recommended_action` | `refund_brl` | Responsible |
| --- | --- | --- | ---: | --- |
| `canceled_order_paid` | action_required | issue_refund | 79.0 | platform |
| `unavailable_order_paid` | action_required | issue_refund | 89.0 | seller `seller-0c65eb5a1415` ⚠️ |
| `late_delivery_seller` | action_required | refund_freight | 18.0 | seller `seller-e58fb7bfd033` ⚠️ |
| `late_delivery_logistics` | action_required | refund_freight | 16.0 | logistics_provider |
| `duplicate_charge` | action_required | refund_duplicate_charge | 64.0 | payment_provider |
| `payment_mismatch` | action_required | reconcile_payment | 35.0 | payment_provider |
| `refund_failed` | action_required | retry_refund | 52.0 | payment_provider |
| `refund_pending` | needs_investigation | monitor_refund | 0.0 | payment_provider |
| `valid_split_payment` | no_action | document_no_action | 0.0 | customer |
| `unsupported_claim` | no_action | document_no_action | 0.0 | customer |
| `insufficient_evidence` | *(không có trong policy)* | | | |

⚠️ `party_id` seller trong policy là seller **cố định**, không phải seller của case. Nghi là bẫy: `party_id` trong output nên lấy seller thật từ `get_order_items` (sau khi lọc). **Cần Bảo đối chiếu.**

Các giá trị `refund_brl` khớp với số tiền thấy trong dữ liệu (xem mục 4). Chưa rõ nên lấy `refund_brl` từ policy hay tính từ dữ liệu → **câu hỏi mở cho D4** (mục 6).

## 4. Luật payment/refund rút ra từ dữ liệu

Tổng đơn trong mọi case đã thử: 1 item, `price` 79.00 + `freight_value` 10.00 = **89.00**.

Chỉ tính các event **trong cửa sổ**:

| Tình huống | Event trong cửa sổ | Tín hiệu | Policy refund |
| --- | --- | --- | ---: |
| Split hợp lệ | captured 44.50 (cc) + captured 44.50 (voucher) = 89.00 = tổng đơn | `PAY_SPLIT_VALID` | 0 |
| Thu trùng | captured 64.00 (cc) + captured 64.00 (voucher) = 128.00 > 89.00; **hai lần thu cùng số tiền** | `PAY_DUPLICATE` | 64 = **một** lần thu trùng |
| Lệch tiền | captured 35.00 + `reconciliation_mismatch` 35.00 `open` | `PAY_MISMATCH` | 35 |
| Refund pending | captured 89.00 + refund_requested 89.00 `pending` | `PAY_CAPTURED` + `REFUND_PENDING` | 0 |
| Refund failed | captured 52.00 + refund_requested 52.00 `failed` | `PAY_CAPTURED` + `REFUND_FAILED` | 52 |
| Không có vấn đề (`unsupported_claim`) | captured 89.00; refund tool lỗi | `PAY_CAPTURED` + `REFUND_NONE` | 0 |

Hệ quả cho luật của Phi trong bản phân công (mục Q3):
- "Duplicate thì cùng `payment_type`" → **sai** với dữ liệu thật. Dùng: tổng trong cửa sổ > tổng đơn và có ≥ 2 captured cùng `amount_brl`.
- "Duplicate chỉ hoàn phần dư `captured - order_total`" → phần dư là 128 − 89 = 39, nhưng policy nói **64**. Nên theo policy.
- Mismatch dựa vào event `reconciliation_mismatch`, không dựa vào `captured ≠ order_total`.

## 5. Response mẫu (case 005, `valid_split_payment`, rút gọn)

```json
{
  "domain": "payment",
  "evidence_ref": "ev_…",
  "data": {
    "order_id": "9a31fd9d697e9670777501f720773fd9",
    "payments": [
      {"payment_sequential": "1", "payment_type": "credit_card", "payment_installments": "1", "payment_value": "44.50"},
      {"payment_sequential": "2", "payment_type": "voucher",     "payment_installments": "1", "payment_value": "44.50"},
      {"payment_sequential": "1", "payment_type": "credit_card", "payment_installments": "1", "payment_value": "52.00"}
    ],
    "events": [
      {"event_at": "2018-04-23T10:00:00-03:00", "event_type": "captured", "amount_brl": "44.50", "status": "confirmed"},
      {"event_at": "2018-04-23T11:00:00-03:00", "event_type": "captured", "amount_brl": "44.50", "status": "confirmed"},
      {"event_at": "2018-01-07T10:00:00-03:00", "event_type": "captured", "amount_brl": "52.00", "status": "confirmed"}
    ]
  },
  "warnings": []
}
```

Purchase `2018-04-23T09:00`, opened `2018-05-05T09:00` → dòng 52.00 (`2018-01-07`) là nhiễu. Refund timeline của case này cũng có 1 event `failed` 52.00 ngày `2018-01-18` → nhiễu, bỏ qua.

## 6. Câu hỏi mở cho buổi họp D4

1. `recommended_refund_brl`: lấy `rules[issue].refund_brl` từ policy, hay tính từ dữ liệu rồi đối chiếu với policy? Hiện hai cách cho cùng kết quả trên 17 case.
2. `resolution_actions`: dùng nguyên văn `recommended_action` của policy (`issue_refund`, `retry_refund`, …) thay vì tự đặt mã (`ISSUE_FULL_REFUND`, …)? Mình nghiêng về dùng nguyên văn policy vì scorer nhiều khả năng so với policy.
3. Lỗi `get_refund_timeline` = "không có refund" (`REFUND_NONE`), hay = lỗi tạm thời cần retry? Lỗi ổn định qua nhiều lần retry, nên đề xuất: retry 1 lần, vẫn lỗi thì `REFUND_NONE` và không cite evidence refund.
4. Format `payment_references` (mục 2).
5. Có cite evidence của dòng nhiễu không? Đề xuất: vẫn cite ref của tool (ref là theo cả response, không theo dòng), vì kết luận dựa trên response đó sau khi lọc.

## 7. Từ vựng đóng (Q9, đề xuất cho D4)

`resolution_actions`: dùng **nguyên văn** `recommended_action` của policy, cộng một mã cho trường hợp không có rule. Định nghĩa tại `agents/policy_agent.py` (`RESOLUTION_ACTIONS`).

| Mã | Khi nào |
| --- | --- |
| `issue_refund` | canceled_order_paid, unavailable_order_paid |
| `refund_freight` | late_delivery_seller, late_delivery_logistics |
| `refund_duplicate_charge` | duplicate_charge |
| `reconcile_payment` | payment_mismatch |
| `retry_refund` | refund_failed |
| `monitor_refund` | refund_pending |
| `document_no_action` | valid_split_payment, unsupported_claim |
| `request_more_evidence` | insufficient_evidence (không có trong policy) |

`refund_lines[].reason_code`: định nghĩa tại `domain/money.py` (`ISSUE_REASON_CODES`).

| Mã | Issue |
| --- | --- |
| `CANCELED_ORDER_FULL_REFUND` | canceled_order_paid |
| `UNAVAILABLE_ORDER_FULL_REFUND` | unavailable_order_paid |
| `LATE_DELIVERY_FREIGHT_REFUND` | late_delivery_seller, late_delivery_logistics |
| `DUPLICATE_CHARGE_EXCESS` | duplicate_charge |
| `PAYMENT_MISMATCH_ADJUSTMENT` | payment_mismatch |
| `FAILED_REFUND_RETRY` | refund_failed |

Gợi ý `cause_code` (payment agent đặt vào `facts["cause_codes"]`): `DUPLICATE_CAPTURE`, `PAYMENT_RECONCILIATION_MISMATCH`, `VALID_SPLIT_PAYMENT`, `REFUND_PROCESSING_FAILED`, `REFUND_PROCESSING_PENDING`.

## 8. Cách Phi gọi (tích hợp vào coordinator)

```python
from .agents import payment_agent, policy_agent
from .domain.money import compute_refund, check_money_invariants

order = await order_agent.analyze(case, gateway, trace)                 # Bảo
pay = await payment_agent.analyze(case, gateway, trace, order_facts=order.facts)
issue = rules.decide(order, shipment, pay, ...)                         # Phi
pol = await policy_agent.analyze(case, gateway, trace, primary_issue=issue,
                                 seller_ids=order.entities.get("seller_ids", []))
refund, lines = compute_refund(
    order.facts.get("order_total_brl"), pay.facts.get("captured_total_brl"),
    pay.facts.get("refunded_total_brl"), pay.signals + pol.signals,
    policy_rule,                     # = rules[issue] từ policy (pol.facts có sẵn các trường)
    primary_issue=issue, entity_id=order_id,
)
errors = check_money_invariants(output, captured_total_brl=pay.facts.get("captured_total_brl"))
```

- `compute_refund` có thêm tham số keyword `primary_issue` so với chữ ký trong bản phân công: cần nó để chọn `reason_code`.
- `policy` truyền vào `compute_refund` là rule của issue, dạng `{"refund_brl": ...}`; `pol.facts["refund_brl"]` dùng được luôn: `{"refund_brl": pol.facts["refund_brl"]}`.
- `check_money_invariants` kiểm cả tính nhất quán action: không trùng action; refund > 0 phải có action hoàn tiền; `no_action` không được có action hoàn tiền (scorer chấm consistency theo "status/refund/action … duplicate actions").
- `domain/findings.py` hiện là **bản tạm do Quốc viết theo đúng mục 4.2**, Phi thay bằng bản chính thức.
