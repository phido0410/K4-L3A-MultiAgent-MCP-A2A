# Cấu trúc dữ liệu MCP Evidence Gateway

Khảo sát trên `L3A_CASE_001` ngày 2026-09-25 (order `e2a03ccf5ea816036608b2d8c3ab8e60`).
Đây là quan sát trên **một case**; Bảo và Quốc cần kiểm chứng thêm trên case thuộc
phạm vi của mình (task B1 / Q1) trước khi code cứng.

Tái tạo: `python scripts/mcp_probe.py L3A_CASE_001`

---

## ⚠️ Ba điều phải biết trước khi viết luật

**1. Mọi số tiền và số lượng trả về dạng CHUỖI, không phải số.**

```json
{"price": "79.00", "freight_value": "10.00", "payment_value": "79.00",
 "payment_installments": "1", "payment_sequential": "1"}
```

Phải `Decimal(str(...))` hoặc `float(...)` trước khi tính. So sánh chuỗi sẽ sai.
Ngoại lệ: `get_policy` trả `refund_brl` dạng số thật (`79.0`).

**2. `get_policy` trả về bảng quy tắc cho TỪNG loại issue.**

Đây là phát hiện quan trọng nhất. Tool này không chỉ trả điều khoản chung mà cho
sẵn `case_status`, `recommended_action`, `refund_brl` và `responsible_parties`
ứng với mỗi `primary_issue`. Nghĩa là **bài toán quy về: xác định đúng
`primary_issue`, phần còn lại của output đọc từ policy** thay vì tự suy ra.

**3. Tool có thể trả lỗi thay vì trả rỗng.**

`get_refund_timeline` trên case 001 trả `Error executing tool get_refund_timeline`.
Nhiều khả năng vì case này không có refund nào. Agent phải bắt lỗi và phát tín
hiệu `REFUND_NONE`, **không được coi lỗi là crash**.

---

## get_order — domain `order`

```json
{
  "order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
  "customer_id": "customer-row-e2a03ccf5ea8",
  "order_status": "canceled",
  "order_purchase_timestamp":     "2017-12-20T09:00:00-03:00",
  "order_approved_at":            "2017-12-20T10:00:00-03:00",
  "order_delivered_carrier_date": "2017-12-22T09:00:00-03:00",
  "order_delivered_customer_date": null,
  "order_estimated_delivery_date": "2017-12-30T09:00:00-03:00"
}
```

Tên field khớp dataset Olist gốc. Timestamp có offset `-03:00`, phải parse thành
datetime có timezone rồi mới so sánh.

## get_order_items — domain `item`

Trả về **mảng** dòng item:

```json
[
  {"order_id": "...", "order_item_id": "item-e2a03ccf5ea8",
   "product_id": "product-e2a03ccf5ea8", "seller_id": "seller-e2a03ccf5ea8",
   "shipping_limit_date": "2017-12-23T09:00:00-03:00",
   "price": "79.00", "freight_value": "10.00"},
  {"order_id": "...", "order_item_id": "item-e2a03ccf5ea8",
   "product_id": "product-e2a03ccf5ea8", "seller_id": "seller-e2a03ccf5ea8",
   "shipping_limit_date": "2018-05-14T09:00:00-03:00",
   "price": "79.00", "freight_value": "18.00"}
]
```

> **Chú ý (Bảo):** case 001 có **2 dòng cùng `order_item_id`** nhưng khác
> `shipping_limit_date` và `freight_value`. Đây rất có thể là tình huống
> `data_conflicts` được cài sẵn. Đừng cộng mù tổng tiền — kiểm tra trùng
> `order_item_id` trước, và cân nhắc ghi conflict cho field `freight_value`.

## get_shipment_summary — domain `shipment`

```json
{
  "order_id": "...",
  "order_status": "canceled",
  "delivered_carrier_at":  "2017-12-22T09:00:00-03:00",
  "delivered_customer_at": null,
  "estimated_delivery_at": "2017-12-30T09:00:00-03:00",
  "shipping_limits": [
    {"order_item_id": "item-...", "seller_id": "seller-...",
     "shipping_limit_at": "2017-12-23T09:00:00-03:00"},
    {"order_item_id": "item-...", "seller_id": "seller-...",
     "shipping_limit_at": "2018-05-14T09:00:00-03:00"}
  ],
  "events": [
    {"order_id": "...", "event_at": "2018-05-25T09:00:00-03:00",
     "event_type": "delivered_late", "actor": "seller", "status": "confirmed"}
  ]
}
```

> **Chú ý (Bảo):** tên field ở đây **khác** `get_order` (`delivered_carrier_at`
> vs `order_delivered_carrier_date`). Hai tool cùng mô tả một sự kiện — nếu giá
> trị lệch nhau thì đó là `data_conflicts` với `sources: ["order", "shipment"]`.
>
> `events[]` có `event_type` và `actor` — `actor: "seller"` kèm
> `event_type: "delivered_late"` là tín hiệu quy trách nhiệm **trực tiếp**, mạnh
> hơn suy ra từ timestamp. Ưu tiên dùng nếu có.

## get_sellers — domain `seller`

```json
{"seller_id": "seller-e2a03ccf5ea8", "seller_zip_code_prefix": "01001",
 "seller_city": "sao_paulo", "seller_state": "SP"}
```

## get_product_context — domain `product`

Mảng, mỗi phần tử: `order_item_id`, `product_id`, `seller_id`,
`product{product_id, product_category_name}`, `category_name_english`.

Không chứa thông tin tài chính hay timeline — ít khả năng cần cho L3A.

## get_order_payments — domain `payment`

Mảng dòng thanh toán:

```json
[
  {"order_id": "...", "payment_sequential": "1", "payment_type": "credit_card",
   "payment_installments": "1", "payment_value": "79.00"},
  {"order_id": "...", "payment_sequential": "1", "payment_type": "credit_card",
   "payment_installments": "1", "payment_value": "18.00"}
]
```

> **Chú ý (Quốc):** case 001 có 2 dòng **cùng `payment_sequential = "1"`**, cùng
> `payment_type`, khác số tiền. `payment_sequential` trùng nghĩa là **không dùng
> được nó làm khoá phân biệt**. Tổng thu = 79 + 18 = 97.00, trong khi tổng đơn
> theo item = 79 + 10 = 89.00 hoặc 79 + 18 = 97.00 tuỳ chọn dòng item nào.
> Quan hệ giữa hai bảng này chính là chỗ phân biệt `payment_mismatch` với
> `duplicate_charge` — khảo sát kỹ.

## get_payment_timeline — domain `payment`

```json
{
  "order_id": "...",
  "payments": [ ... giống get_order_payments ... ],
  "events": [
    {"order_id": "...", "event_at": "2017-12-20T10:00:00-03:00",
     "event_type": "captured", "amount_brl": "79.00", "status": "confirmed"},
    {"order_id": "...", "event_at": "2018-05-11T10:00:00-03:00",
     "event_type": "captured", "amount_brl": "18.00", "status": "confirmed"}
  ]
}
```

`events[]` có `event_type` và `status` — đây là nguồn có thẩm quyền để phân biệt
đã thu / thu trùng / thất bại, tốt hơn là suy từ bảng `payments`.

Lưu ý: tool này bao trùm `get_order_payments` (có sẵn mảng `payments`). Nếu chỉ
cần đối soát thì gọi **một** tool này là đủ — server khuyến nghị "use the
smallest evidence tool needed".

## get_refund_timeline — domain `refund`

Case 001: **lỗi** `Error executing tool get_refund_timeline`.

Chưa biết cấu trúc khi có refund. Quốc khảo sát trên case có claim
`refund_pending` / `refund_failed` (ví dụ `L3A_CASE_008`, `L3A_CASE_009`).

## get_policy — domain `policy`

```json
{
  "currency": "BRL",
  "policy_version": "EC_POLICY_V1",
  "rules": {
    "canceled_order_paid": {
      "case_status": "action_required",
      "recommended_action": "issue_refund",
      "refund_brl": 79.0,
      "responsible_parties": [{"party_type": "platform", "party_id": null}]
    },
    "duplicate_charge": {
      "case_status": "action_required",
      "recommended_action": "refund_duplicate_charge",
      "refund_brl": 64.0,
      "responsible_parties": [{"party_type": "payment_provider", "party_id": null}]
    },
    "late_delivery_seller": {
      "case_status": "action_required",
      "recommended_action": "refund_freight",
      "refund_brl": 18.0,
      "responsible_parties": [{"party_type": "seller", "party_id": "seller-e58fb7bfd033"}]
    },
    "late_delivery_logistics": {
      "case_status": "action_required",
      "recommended_action": "refund_freight",
      "refund_brl": 16.0,
      "responsible_parties": [{"party_type": "logistics_provider", "party_id": null}]
    },
    "payment_mismatch": {
      "case_status": "action_required",
      "recommended_action": "reconcile_payment",
      "refund_brl": 35.0,
      "responsible_parties": [...]
    }
    // ... còn các issue khác, chưa dump hết
  }
}
```

**Cách dùng:** sau khi `rules.py` chốt `primary_issue`, tra
`policy["rules"][primary_issue]` để lấy `case_status`, `refund_brl` và
`responsible_parties` thay vì tự suy. Giá trị từ policy có thẩm quyền cao hơn
hằng số hard-code trong `domain/rules.py`.

> **Cần kiểm chứng:** `late_delivery_seller.responsible_parties[0].party_id` là
> `seller-e58fb7bfd033`, **không phải** seller của order này
> (`seller-e2a03ccf5ea8`). Chưa rõ policy là per-case hay dùng chung một mẫu.
> Quốc xác minh bằng cách gọi `get_policy` trên 2–3 case khác và so sánh: nếu
> `refund_brl` đổi theo case thì policy là per-case; nếu giống hệt thì là bảng
> tĩnh và `party_id` phải tự điền từ `get_order_items`.

---

## Vận hành gateway — đã gặp thật

**Gateway giới hạn session đồng thời và có throttle.** Triệu chứng: `POST initialize`
treo tới hết timeout trong khi `GET` vẫn trả nhanh. Nguyên nhân: session mở mà
không `DELETE` sẽ giữ slot.

Hệ quả thực tế:

- Đóng session sau khi dùng (`scripts/mcp_probe.py` đã làm trong `finally`).
- Không chạy hai tiến trình gọi MCP cùng lúc — ba người không nên chạy `day09 run`
  đồng thời trên cùng một Team API Key.
- Bị timeout thì **chờ vài phút**, đừng thử lại liên tục: mỗi lần thử lại mở thêm
  một session và làm tình hình xấu hơn.
