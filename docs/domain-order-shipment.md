# Khảo sát Domain Order & Shipment (MCP Evidence Gateway)

Tài liệu khảo sát thực tế các MCP tool thuộc phạm vi phụ trách của **Nguyễn Trường Bảo** (Order, Item, Seller, Shipment, Product).
Dữ liệu được truy vấn trực tiếp từ MCP Evidence Gateway (`https://day09-competition.34-142-201-239.sslip.io/mcp`).

---

## 1. Danh sách MCP Tools phụ trách

| Tool name | Domain | Arguments | Mục đích |
| --- | --- | --- | --- |
| `get_order` | `order` | `case_id`, `order_id` | Lấy bản ghi order chuẩn: trạng thái đơn, mốc thời gian mua, duyệt, giao hàng |
| `get_order_items` | `item` | `case_id`, `order_id` | Lấy chi tiết các mặt hàng, giá, phí ship, hạn bàn giao của seller |
| `get_sellers` | `seller` | `case_id`, `order_id` | Lấy thông tin người bán liên quan tới các mặt hàng của đơn |
| `get_shipment_summary` | `shipment` | `case_id`, `order_id` | Lấy mốc vận chuyển, hạn chót bàn giao của carrier, và audit events |
| `get_product_context` | `product` | `case_id`, `order_id` | Lấy ngữ cảnh sản phẩm, category tên tiếng Anh/Bồ Đào Nha |

---

## 2. Chi tiết từng Tool & Response mẫu

### 2.1 `get_order` (Domain: `order`)
- **Mô tả:** Trả về thông tin trạng thái và mốc thời gian tổng quan của đơn hàng.
- **Fields trong `data`:**
  - `order_id` (`string`): Mã đơn hàng.
  - `customer_id` (`string`): Mã khách hàng dòng đơn.
  - `order_status` (`string`): Trạng thái đơn (`delivered`, `shipped`, `canceled`, `unavailable`, `invoiced`, `processing`, `approved`, `created`).
  - `order_purchase_timestamp` (`string` ISO-8601): Thời điểm khách đặt đơn.
  - `order_approved_at` (`string` ISO-8601 | `null`): Thời điểm thanh toán được duyệt.
  - `order_delivered_carrier_date` (`string` ISO-8601 | `null`): Thời điểm bàn giao cho carrier.
  - `order_delivered_customer_date` (`string` ISO-8601 | `null`): Thời điểm khách nhận hàng thực tế.
  - `order_estimated_delivery_date` (`string` ISO-8601): Hạn cam kết giao hàng cho khách.

**Response mẫu (`L3A_CASE_001`):**
```json
{
  "schema_version": "day09-mcp-evidence-v1",
  "evidence_ref": "ev_BP4ikfvm6Ox0lmnpe4Os2A78UHT2HHKG",
  "result_hash": "sha256:3ce00e5607e8ea56f947fdfd70f99ae56ce047f3fc549d1c707d07087cdd439a",
  "domain": "order",
  "data": {
    "order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
    "customer_id": "customer-row-e2a03ccf5ea8",
    "order_status": "canceled",
    "order_purchase_timestamp": "2017-12-20T09:00:00-03:00",
    "order_approved_at": "2017-12-20T10:00:00-03:00",
    "order_delivered_carrier_date": "2017-12-22T09:00:00-03:00",
    "order_delivered_customer_date": null,
    "order_estimated_delivery_date": "2017-12-30T09:00:00-03:00"
  },
  "warnings": []
}
```

---

### 2.2 `get_order_items` (Domain: `item`)
- **Mô tả:** Trả về danh sách mặt hàng và người bán thuộc đơn hàng.
- **Fields trong mỗi item của `data`:**
  - `order_id` (`string`): Mã đơn hàng.
  - `order_item_id` (`string`): Mã định danh item trong đơn.
  - `product_id` (`string`): Mã sản phẩm.
  - `seller_id` (`string`): Mã người bán món đồ đó.
  - `shipping_limit_date` (`string` ISO-8601): Hạn chót seller phải bàn giao món đồ cho bên vận chuyển.
  - `price` (`string`): Giá sản phẩm dạng chuỗi (cần parse float, ví dụ `"79.00"`).
  - `freight_value` (`string`): Phí vận chuyển của món hàng (cần parse float, ví dụ `"10.00"`).

**Response mẫu (`L3A_CASE_001`):**
```json
{
  "schema_version": "day09-mcp-evidence-v1",
  "evidence_ref": "ev_l_hterNPSn4CXGreBqa7UlHAShobStpn",
  "result_hash": "sha256:f2a3913c9baf65fd2463e085cee63fa1074456f41b485ba48ae151478517fd9e",
  "domain": "item",
  "data": [
    {
      "order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
      "order_item_id": "item-e2a03ccf5ea8",
      "product_id": "product-e2a03ccf5ea8",
      "seller_id": "seller-e2a03ccf5ea8",
      "shipping_limit_date": "2017-12-23T09:00:00-03:00",
      "price": "79.00",
      "freight_value": "10.00"
    },
    {
      "order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
      "order_item_id": "item-e2a03ccf5ea8",
      "product_id": "product-e2a03ccf5ea8",
      "seller_id": "seller-e2a03ccf5ea8",
      "shipping_limit_date": "2018-05-14T09:00:00-03:00",
      "price": "79.00",
      "freight_value": "18.00"
    }
  ],
  "warnings": []
}
```

---

### 2.3 `get_sellers` (Domain: `seller`)
- **Mô tả:** Trả về danh sách chi tiết các seller liên quan.
- **Fields trong mỗi seller của `data`:**
  - `seller_id` (`string`): Định danh seller.
  - `seller_zip_code_prefix` (`string`): Mã bưu chính người bán.
  - `seller_city` (`string`): Thành phố người bán.
  - `seller_state` (`string`): Bang của người bán.

**Response mẫu (`L3A_CASE_001`):**
```json
{
  "schema_version": "day09-mcp-evidence-v1",
  "evidence_ref": "ev_2bQ8Pza8yC1TboTWpIQ_PozlB7NlBBs6",
  "result_hash": "sha256:3ea229c8cd27bb5f2f72d1e421e953f49e846c0b2317fd2797e927ecabd45f64",
  "domain": "seller",
  "data": [
    {
      "seller_id": "seller-e2a03ccf5ea8",
      "seller_zip_code_prefix": "01001",
      "seller_city": "sao_paulo",
      "seller_state": "SP"
    }
  ],
  "warnings": []
}
```

---

### 2.4 `get_shipment_summary` (Domain: `shipment`)
- **Mô tả:** Trả về các mốc giao nhận vận chuyển tổng hợp và sự kiện kiểm toán vận chuyển.
- **Fields trong `data`:**
  - `order_id` (`string`): Mã đơn hàng.
  - `order_status` (`string`): Trạng thái đơn hàng dưới góc độ vận chuyển.
  - `delivered_carrier_at` (`string` ISO-8601 | `null`): Thời điểm carrier nhận hàng từ seller.
  - `delivered_customer_at` (`string` ISO-8601 | `null`): Thời điểm khách nhận hàng.
  - `estimated_delivery_at` (`string` ISO-8601): Hạn dự kiến giao cho khách.
  - `shipping_limits` (`list[dict]`): Hạn bàn giao theo từng item (`order_item_id`, `seller_id`, `shipping_limit_at`).
  - `events` (`list[dict]`): Các sự kiện vận chuyển được xác nhận, gồm:
    - `event_type`: ví dụ `"delivered_late"`.
    - `actor`: bên gây ra sự cố (`"seller"` hoặc `"logistics_provider"`).
    - `status`: ví dụ `"confirmed"`.
    - `event_at`: thời điểm ghi nhận sự kiện.

**Response mẫu (`L3A_CASE_003` - Trễ do seller):**
```json
{
  "schema_version": "day09-mcp-evidence-v1",
  "evidence_ref": "ev_s6T8zF1uW...",
  "domain": "shipment",
  "data": {
    "order_id": "71303d7e93b399f5bcd537d124c0bcfa",
    "order_status": "delivered",
    "delivered_carrier_at": "2018-02-26T09:00:00-03:00",
    "delivered_customer_at": "2018-03-05T09:00:00-03:00",
    "estimated_delivery_at": "2018-03-01T09:00:00-03:00",
    "shipping_limits": [
      {
        "order_item_id": "item-71303d7e93b3",
        "seller_id": "seller-71303d7e93b3",
        "shipping_limit_at": "2018-02-22T09:00:00-03:00"
      },
      {
        "order_item_id": "item-71303d7e93b3",
        "seller_id": "seller-71303d7e93b3",
        "shipping_limit_at": "2018-03-12T09:00:00-03:00"
      }
    ],
    "events": [
      {
        "order_id": "71303d7e93b399f5bcd537d124c0bcfa",
        "event_at": "2018-03-05T09:00:00-03:00",
        "event_type": "delivered_late",
        "actor": "seller",
        "status": "confirmed"
      }
    ]
  },
  "warnings": []
}
```

**Response mẫu (`L3A_CASE_004` - Trễ do logistics):**
```json
{
  "schema_version": "day09-mcp-evidence-v1",
  "evidence_ref": "ev_...",
  "domain": "shipment",
  "data": {
    "order_id": "fd28a6dfe413804d0b89b7c9abf5b1f3",
    "order_status": "delivered",
    "delivered_carrier_at": "2018-03-25T09:00:00-03:00",
    "delivered_customer_at": "2018-04-07T09:00:00-03:00",
    "estimated_delivery_at": "2018-04-02T09:00:00-03:00",
    "shipping_limits": [
      {
        "order_item_id": "item-fd28a6dfe413",
        "seller_id": "seller-fd28a6dfe413",
        "shipping_limit_at": "2018-03-26T09:00:00-03:00"
      }
    ],
    "events": [
      {
        "order_id": "fd28a6dfe413804d0b89b7c9abf5b1f3",
        "event_at": "2018-04-07T09:00:00-03:00",
        "event_type": "delivered_late",
        "actor": "logistics_provider",
        "status": "confirmed"
      }
    ]
  },
  "warnings": []
}
```

---

### 2.5 `get_product_context` (Domain: `product`)
- **Mô tả:** Trả về danh mục và thông tin sản phẩm dịch sang tiếng Anh.
- **Fields trong mỗi item:** `order_item_id`, `product_id`, `seller_id`, `product`, `category_name_english`.

---

## 3. Các lưu ý kỹ thuật quan trọng khi code Agent

1. **Kiểu dữ liệu tiền tệ:**
   Trong `get_order_items`, `price` và `freight_value` trả về dạng chuỗi `"79.00"` chứ không phải số thực `float`. Khi tính `order_total_brl`, bắt buộc phải chuyển sang `float` (hoặc `Decimal`) và làm tròn 2 chữ số thập phân (`round(..., 2)`).
2. **Múi giờ ISO-8601:**
   Tất cả các mốc thời gian đều có múi giờ `-03:00` (America/Sao_Paulo). Khi so sánh datetime, dùng `datetime.fromisoformat()` để so sánh đối tượng `datetime` có timezone, tuyệt đối không so sánh chuỗi ký tự.
3. **Phân biệt trễ Seller vs Logistics:**
   - So sánh mốc:
     - Seller trễ khi: `delivered_carrier_at > min(shipping_limit_at)` (seller bàn giao carrier trễ hạn).
     - Logistics trễ khi: Seller bàn giao đúng hạn nhưng `delivered_customer_at > estimated_delivery_at`.
   - Đối chiếu chéo: Trong `get_shipment_summary["data"]["events"]` có sự kiện `delivered_late` với trường `actor` ghi rõ `"seller"` hoặc `"logistics_provider"`. Đây là căn cứ thẩm quyền giúp tăng confidence lên 1.0!
4. **Đối chiếu mốc giữa domain `order` và `shipment`:**
   Nếu `order_delivered_customer_date` trong `order` khác `delivered_customer_at` trong `shipment`, agent phải phát hiện và ghi vào `conflicts`:
   ```python
   {
       "field": "order_delivered_customer_date",
       "sources": ["order", "shipment"],
       "selected_source": "shipment",
       "resolution_code": "PREFER_SHIPMENT_TIMELINE",
   }
   ```
5. **Tránh cite thừa evidence:**
   Chỉ đưa vào `evidence_refs` những tool thực sự dùng để đưa ra kết luận (F1 score). Nếu chỉ tra order và shipment để kết luận trễ hạn, không nhất thiết phải cite cả product nếu không phân tích sản phẩm.
