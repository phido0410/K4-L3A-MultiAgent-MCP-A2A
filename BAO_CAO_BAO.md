# Báo cáo tiến độ phần việc: Order / Item / Shipment

- **Người thực hiện:** Nguyễn Trường Bảo
- **Người nhận:** Đỗ Ngọc Phi (Lead), Phạm Cường Quốc
- **Nhánh:** `Bao` (hoặc `feat/order-shipment`)
- **Trạng thái:** Đã hoàn thành 100% các hạng mục D1–D4 theo [PHAN_CONG.md](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/PHAN_CONG.md)

---

## 1. Danh mục các đầu việc đã bàn giao

| # | Hạng mục | Mô tả chi tiết | File liên quan |
|---|---|---|---|
| **B1** | Khảo sát MCP Tools | Đã gọi thực tế 5 tool trên MCP Evidence Gateway, ghi chép schema, kiểu dữ liệu, các trường thực tế và 5 response mẫu | [`docs/domain-order-shipment.md`](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/docs/domain-order-shipment.md) |
| **B2–B4** | `order_agent.py` | Lấy order, items, sellers; tính chuẩn `order_total_brl`; trích xuất entities; phát các tín hiệu `ORDER_STATUS_*`; phát hiện gợi ý root cause cho đơn hủy/hết hàng | [`src/student_agent/agents/order_agent.py`](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/src/student_agent/agents/order_agent.py) |
| **B5–B7** | `shipment_agent.py` | Lấy shipment summary; phân định trễ do seller (`SHIP_LATE_SELLER`) vs carrier (`SHIP_LATE_LOGISTICS`); tính số ngày trễ; xếp hạng `ranked_causes` và `responsible_parties`; phát hiện xung đột mốc ngày chéo nguồn | [`src/student_agent/agents/shipment_agent.py`](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/src/student_agent/agents/shipment_agent.py) |
| **B8** | Unit Tests | 12 test cases thuần sử dụng mock gateway (không gọi mạng), bao phủ toàn bộ tín hiệu order/shipment và 2 test biên (đúng deadline, thiếu mốc) | [`tests/test_order_shipment.py`](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/tests/test_order_shipment.py) |
| **B9** | Tài liệu kiến trúc | Cập nhật mục 2 trong tài liệu kiến trúc cho hai vai trò `Order/item` và `Shipment`, quy định rõ quyền gọi tool MCP theo từng actor | [`ARCHITECTURE.md`](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/ARCHITECTURE.md#L17) |
| **Extra** | Data Model chung | Hiện thực hóa lớp `Finding` và `EvidenceItem` theo chuẩn mục 4.2 | [`src/student_agent/domain/findings.py`](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/src/student_agent/domain/findings.py) |
| **Extra** | Hotfix Gateway | Khắc phục lỗi `isError` $\rightarrow$ `is_error` do tương thích MCP SDK v2 Pydantic snake_case | [`src/student_agent/mcp_gateway.py`](file:///d:/Ai%20Thuc%20chien/K4-L3A-MultiAgent-MCP-A2A/src/student_agent/mcp_gateway.py#L27) |

---

## 2. Các phát hiện kỹ thuật quan trọng gửi nhóm

### 2.1 Bug thư viện trong `mcp_gateway.py` (Gửi Phi)
- **Vấn đề:** Khi gọi tool qua `gateway.call()`, chương trình ném exception:  
  `AttributeError: 'CallToolResult' object has no attribute 'isError'`  
  Do gói `mcp>=2` định nghĩa thuộc tính snake_case `result.is_error`.
- **Đã xử lý:** Sửa thành `is_error = getattr(result, "is_error", getattr(result, "isError", False))` để tương thích mọi phiên bản.
- **Hành động cần làm:** Phi hợp nhất đoạn fix này vào nhánh chính (`main`) để coordinator chạy không bị lỗi.

### 2.2 Kiểu dữ liệu tiền tệ trong `get_order_items` (Gửi Quốc)
- **Vấn đề:** Dữ liệu trả về từ MCP cho `price` và `freight_value` là chuỗi `str` (`"79.00"`, `"18.00"`), không phải số `float`.
- **Đã xử lý:** `order_agent` đã cộng chuẩn xác bằng `Decimal` và làm tròn 2 chữ số thập phân, lưu vào `facts["order_total_brl"]`.
- **Hành động cần làm:** Quốc khi viết `domain/money.py` và `payment_agent.py` có thể lấy trực tiếp số liệu `order_finding.facts["order_total_brl"]` để đối chiếu với `captured_total_brl`, hoặc nếu parse từ item thì nhớ ép kiểu chuỗi.

### 2.3 Căn cứ thẩm quyền trong `get_shipment_summary`
- Ngoài các mốc thời gian ISO (`delivered_carrier_at`, `delivered_customer_at`, `estimated_delivery_at`, `shipping_limits`), response của `get_shipment_summary` có trường `events` kiểm toán chứa:
  ```json
  {
    "order_id": "...",
    "event_at": "2018-03-05T09:00:00-03:00",
    "event_type": "delivered_late",
    "actor": "seller",  // hoặc "logistics_provider"
    "status": "confirmed"
  }
  ```
- Đây là căn cứ audit trực tiếp từ hệ thống giúp gán `confidence = 1.0` và phân định bên chịu trách nhiệm (`responsible_parties`) chính xác 100%.

---

## 3. Kết quả kiểm tra chất lượng

### 3.1 Kiểm tra quy chuẩn mã nguồn (Ruff)
```bash
ruff check .
```
- **Kết quả:** `All checks passed!` (0 warning, 0 error).

### 3.2 Bộ kiểm thử tự động (Pytest)
```bash
pytest --basetemp=.pytest_tmp tests/test_order_shipment.py tests/test_starter.py
```
- **Kết quả:** `15 passed in 1.18s` (gồm 12 test agent order/shipment + 3 test starter contract).

### 3.3 Kiểm tra tích hợp trực tiếp với MCP Server
Đã kiểm tra kết nối và gọi thử trực tiếp trên các case thực tế:
- `L3A_CASE_001`: Đơn `canceled`, chưa giao (`SHIP_NOT_DELIVERED`), tính đúng tổng tiền 186.0 BRL.
- `L3A_CASE_003`: Đơn `delivered`, trễ cả seller lẫn carrier, audit event xác nhận seller bàn giao trễ 4 ngày.
- `L3A_CASE_004`: Đơn `delivered`, trễ do carrier 5 ngày, audit event xác nhận `logistics_provider` trễ.
