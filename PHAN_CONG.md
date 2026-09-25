# L3A — Phân công công việc

**Gửi:** Nguyễn Trường Bảo, Phạm Cường Quốc
**Từ:** Đỗ Ngọc Phi (lead)
**Repo:** `K4-L3A-MultiAgent-MCP-A2A` — giữ nguyên tên, không đổi khi fork

Đọc hết file này trước khi code. Phần 1–4 là bắt buộc cho cả hai; phần 5 dành cho Bảo, phần 6 dành cho Quốc.

---

## 1. Bài lab là gì (đọc 3 phút)

Xây hệ **multi-agent điều tra khiếu nại thương mại điện tử** trên dữ liệu Olist Brazilian E-Commerce.

Đầu vào: 100 case trong `inputs/`. Mỗi case là một khiếu nại:

```json
{
  "case_id": "L3A_CASE_001",
  "opened_at": "2018-01-01T09:00:00-03:00",
  "policy_version": "EC_POLICY_V1",
  "customer_request": {
    "language": "vi",
    "message": "Đơn hàng có dấu hiệu bất thường sau thanh toán...",
    "claimed_order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
    "claims": [
      { "claim_id": "claim-001-a", "topic": "canceled_order_paid" },
      { "claim_id": "claim-001-b", "topic": "requested_full_refund" }
    ]
  }
}
```

Đầu ra: mỗi case một file `outputs/<case_id>.json` + một dòng trace trong `traces/trace.jsonl`.

### Cảnh báo quan trọng nhất

**`claims[0].topic` KHÔNG phải đáp án.** Đó là *cáo buộc của khách hàng*.

Bằng chứng: tôi đã thống kê cả 100 file. `claims[0].topic` phân bố **đúng 10 case cho mỗi 1 trong 11 giá trị** của enum `primary_issue`, và phần `message` chỉ có **4 mẫu** xoay vòng **độc lập** với topic. Đây là bẫy cố ý. Ai copy `topic` thành `primary_issue` sẽ chỉ đúng ngẫu nhiên và mất phần lớn 45% điểm semantic.

Kết luận phải dựa **hoàn toàn** vào dữ liệu lấy từ MCP Evidence Gateway.

### Điểm được chấm thế nào

| Thành phần | Trọng số | Ai lo |
| --- | ---: | --- |
| `semantic` — kết luận đúng | **45%** | **Bảo + Quốc** |
| `evidence` — trích dẫn bằng chứng (F1) | 15% | Cả nhóm |
| `provenance` — evidence hợp lệ trong audit | 15% | Phi |
| `consistency` — nhất quán giữa các field | 10% | Phi + Quốc |
| `schema` | 5% | Phi |
| `calibration` — confidence hợp lý | 5% | Phi |
| `workflow` — trace multi-agent | 5% | Phi |

Hai bạn cầm phần nặng nhất: **45% điểm semantic**. Mỗi người phụ trách 5 trong 11 giá trị `primary_issue`.

---

## 2. Cài đặt môi trường (làm ngay, ~15 phút)

Cần **Python 3.11+**.

```bash
git clone <url-repo-của-nhóm>
cd K4-L3A-MultiAgent-MCP-A2A

python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"

cp .env.example .env
```

Mở **`.env`** (file vừa `cp` ra, đã được gitignore) và điền **Team API Key** Phi gửi riêng (dạng `sk-team-...`):

```dotenv
COMPETITION_API_URL=https://n7-competition.pages.dev
COMPETITION_TEAM_API_KEY=sk-team-<key-Phi-gửi>
MCP_ENDPOINT=https://day09-competition.34-142-201-239.sslip.io/mcp
```

Kiểm tra:

```bash
day09 --help
day09 validate-inputs      # phải in: OK: l3a / l3a-competition-v1 / 100 cases
day09 mcp-tools            # liệt kê tool MCP — phải ra danh sách, không rỗng
```

> 🚨 **Điền key vào `.env`, TUYỆT ĐỐI KHÔNG điền vào `.env.example`.**
>
> `.env` bị gitignore nên an toàn. Còn `.env.example` **được git theo dõi** (`.gitignore`
> có dòng `!.env.example` cố tình không ignore nó) — điền key thật vào đó rồi commit là
> key lộ công khai trên GitHub. Hai file tên gần giống nhau, rất dễ nhầm.
>
> Kiểm tra trước mỗi lần commit:
>
> ```bash
> git diff --cached | grep 'sk-team-' && echo "DỪNG LẠI — có key trong commit!"
> ```

Thêm một bước nữa — `pytest -q` phải **xanh 10/10**. Nếu đỏ thì môi trường có vấn đề, báo Phi.

> 🔴 **Nếu `day09 mcp-tools` treo rồi báo `ConnectTimeout`: đừng thử lại ngay.**
>
> Gateway **giới hạn số session đồng thời** trên mỗi Team API Key. Session mở mà không
> đóng sẽ giữ slot, và mọi kết nối sau đó treo tới hết timeout. Mỗi lần bạn thử lại là
> mở thêm một session — càng thử càng tắc.
>
> Cách xử lý: **chờ 5–10 phút rồi thử lại một lần.** Đã xác nhận tự hồi phục.
>
> Hệ quả quan trọng: **ba người không được chạy lệnh gọi MCP cùng lúc** trên cùng một
> key. Hẹn nhau trước khi ai đó chạy `day09 run` hoặc `scripts/mcp_probe.py`.

Nếu lỗi auth (401/403) → nhắn Phi, đừng tự sửa key.

---

## 3. Năm điều cấm tuyệt đối

Vi phạm 1 trong 5 điều này thì **case bị 0 điểm** (hard gate), không cứu được:

1. **Không bịa, không sửa `evidence_ref`.** Ref chỉ được lấy nguyên văn từ response MCP. Format `ev_...`.
2. **Không dùng evidence của case này cho case khác.** Không cache ref qua các case. Server audit từng call.
3. **Không chạy lệnh gọi MCP khi người khác đang chạy.** `evidence_ref` phải khớp **team, run VÀ case** (`contracts/scoring/scoring-policy-v2.json`). Hai người chạy chồng làm nhập nhằng phạm vi `run` → hard gate `cross_scope_evidence_ref`. Áp dụng cho cả `day09 run`, `day09 mcp-tools`, `scripts/smoke_cases.py`, `scripts/dump_case.py`.
4. **Không đoán dữ liệu.** Không có evidence thì kết luận là `insufficient_evidence`, không được suy diễn.
5. **Không commit `.env` hoặc paste API key** vào chat, issue, commit message, log.

Thêm: **không đoán tên tool MCP**. Danh sách 10 tool đã xác nhận ở mục 4.6, dùng đúng tên trong đó.

---

## 4. Hợp đồng code — viết agent thế nào

### 4.1 Cấu trúc module

Khung đã được dựng sẵn và commit — **hai bạn không phải tạo file mới**, chỉ điền vào
hàm `analyze()` trong file của mình. Mỗi file có **đúng một chủ**; không sửa file của
người khác, cần đổi thì nhắn chủ file hoặc mở PR.

```text
src/student_agent/
├── workflow.py              [PHI]   ✅ coordinator, đã chạy thông
├── a2a.py                   [PHI]   ✅ AgentContext + Dispatcher + allowlist tool
├── domain/
│   ├── findings.py          [PHI]   ✅ kiểu dữ liệu chung ← code DỰA VÀO file này
│   ├── rules.py             [PHI]   ✅ ghép tín hiệu → primary_issue (v1, chốt lại D4)
│   └── money.py             [QUỐC]  ⬜ compute_refund() còn TODO
└── agents/
    ├── order_agent.py       [BẢO]   ⬜ analyze() còn TODO
    ├── shipment_agent.py    [BẢO]   ⬜ analyze() còn TODO
    ├── payment_agent.py     [QUỐC]  ⬜ analyze() còn TODO
    ├── policy_agent.py      [QUỐC]  ⬜ analyze() còn TODO
    └── verifier.py          [PHI]   ✅ 8 bất biến trước finalize
```

Chạy `pytest -q` để xác nhận khung còn nguyên: 10 test phải xanh. Trong đó
`tests/test_workflow_wiring.py` chạy cả pipeline bằng gateway giả, không cần mạng.

### 4.2 Kiểu dữ liệu chung (`domain/findings.py`)

Phi commit file này **trong ngày D1**. Hai bạn code dựa vào nó:

```python
@dataclass(frozen=True)
class EvidenceItem:
    evidence_ref: str      # nguyên văn từ MCP, không sửa
    domain: str            # "order" | "payment" | "shipment" | ...
    tool_name: str         # tên tool đã gọi

@dataclass
class Finding:
    actor: str                        # "order-agent", "payment-agent", ...
    signals: list[str]                # mã tín hiệu chuẩn hoá — xem 4.4
    entities: dict[str, list[str]]    # order_ids / item_ids / seller_ids /
                                      # payment_references / shipment_ids
    facts: dict[str, Any]             # số liệu thô để rules.py và money.py dùng
    evidence: list[EvidenceItem]      # CHỈ ref thực sự dùng để kết luận
    conflicts: list[dict]             # xung đột dữ liệu, nếu có
    confidence: float                 # 0.0 – 1.0, mức chắc chắn của riêng agent này
```

Agent của bạn **không** tự quyết `primary_issue`. Bạn chỉ phát ra **tín hiệu** (`signals`) + **số liệu** (`facts`). `rules.py` của Phi ghép tín hiệu từ cả 4 agent lại rồi mới ra kết luận cuối.

### 4.3 Khung một agent

```python
async def analyze(case: dict, context: AgentContext) -> Finding:
    finding = Finding(actor=ACTOR)
    order_id = case["customer_request"]["claimed_order_id"]

    # context.call đã tự: nhét case_id, kiểm tra allowlist tool, kiểm tra
    # định dạng evidence_ref, và emit tool_result_consumed.
    data, item = await context.call("get_order", order_id=order_id)

    # Suy luận từ data -> phát tín hiệu
    finding.add_signal("ORDER_STATUS_CANCELED")
    finding.add_entities("order_ids", [order_id])
    finding.facts["order_status"] = data["order_status"]

    # CHỈ thêm evidence thực sự dẫn tới kết luận (điểm evidence là F1)
    finding.evidence.append(item)
    finding.confidence = 0.9
    return finding
```

`context.call()` trả về `(data, evidence_item)`. Trace đã được ghi tự động —
**không cần tự gọi `trace.emit`**. Việc còn lại là quyết định evidence nào
đáng cite: `finding.evidence.append(item)` chỉ cho những cái dẫn tới kết luận.

**Ba lỗi hay gặp:**

- Gọi tool rồi quên `finding.evidence.append(item)` → evidence không vào output, mất điểm.
- Cite ref không thực sự dùng để kết luận → điểm `evidence` là **F1**, cite thừa bị phạt y như cite thiếu. Gọi 4 tool nhưng chỉ 2 tool dẫn tới kết luận thì chỉ append 2.
- Tự đặt mã tín hiệu ngoài từ vựng → `finding.add_signal()` sẽ ném `ValueError` ngay, khai báo trong `domain/findings.py` trước.

### 4.4 Từ vựng tín hiệu (bản v1 — chốt lại ở buổi họp D4)

Chỉ dùng mã trong danh sách này. Cần mã mới thì báo trước, đừng tự đặt.

**Bảo phát ra:**

```
ORDER_NOT_FOUND          ORDER_STATUS_CANCELED     ORDER_STATUS_UNAVAILABLE
ORDER_STATUS_DELIVERED   ORDER_STATUS_SHIPPED      ORDER_STATUS_OTHER
SHIP_ON_TIME             SHIP_LATE_SELLER          SHIP_LATE_LOGISTICS
SHIP_NOT_DELIVERED       SHIP_TIMELINE_INCOMPLETE  SHIP_TIMELINE_CONFLICT
```

**Quốc phát ra:**

```
PAY_NONE                 PAY_CAPTURED              PAY_SPLIT_VALID
PAY_DUPLICATE            PAY_MISMATCH              PAY_AMOUNT_UNKNOWN
REFUND_NONE              REFUND_PENDING            REFUND_FAILED   REFUND_COMPLETED
POLICY_REFUND_FULL       POLICY_REFUND_PARTIAL     POLICY_NO_REFUND
```

### 4.6 Mười tool MCP (đã xác nhận với gateway ngày 2026-09-25)

Mọi tool đều bắt buộc `case_id`. Không tool nào ngoài danh sách này tồn tại.

| Tool | Tham số | Mô tả | Cấp cho |
| --- | --- | --- | --- |
| `get_order` | `order_id` | Bản ghi order có thẩm quyền | Bảo |
| `get_order_items` | `order_id` | Dòng item và seller của order | Bảo |
| `get_sellers` | `order_id` | Bản ghi seller gắn với item của order | Bảo |
| `get_product_context` | `order_id` | Sản phẩm và danh mục đã dịch | Bảo |
| `get_shipment_summary` | `order_id` | **Mốc giao hàng, hạn bàn giao của seller, sự kiện vận chuyển** | Bảo |
| `get_order_payments` | `order_id` | Dòng thanh toán và evidence vòng đời | Quốc |
| `get_payment_timeline` | `order_id` | Thanh toán gốc + sự kiện vòng đời có thẩm quyền | Quốc |
| `get_refund_timeline` | `order_id` | **Sự kiện vòng đời hoàn tiền có thẩm quyền** | Quốc |
| `get_policy` | `policy_version` | Policy dạng máy đọc được | Quốc |
| `get_customer_history` | `customer_unique_id` | Lịch sử đơn của một khách | — chưa dùng ở L3A |

Allowlist đã được cấu hình sẵn trong `a2a.py::TOOL_SCOPES`. Gọi tool ngoài phạm vi
của mình sẽ ném `ToolScopeError` ngay — đây là chủ ý (nguyên tắc least privilege,
ARCHITECTURE.md mục 2). Cần thêm tool thì nhắn Phi mở rộng scope.

**Hướng dẫn của chính server** (trả về lúc `initialize`):

> "Use the smallest evidence tool needed for the active case. Preserve every
> evidence_ref used by the final answer. Tools are read-only and do not reveal
> scoring oracles."

**Script khảo sát dữ liệu:**

```bash
python scripts/mcp_probe.py L3A_CASE_001                 # xem cấu trúc data mọi tool
python scripts/mcp_probe.py L3A_CASE_001 --tool get_order --raw   # JSON đầy đủ
```

Script này dùng curl thay vì MCP SDK, chỉ phục vụ giai đoạn khảo sát — không
dùng trong workflow chấm điểm.

### 4.5 Quy trình Git

```bash
git checkout -b feat/order-shipment     # Bảo
git checkout -b feat/payment-policy     # Quốc
```

- Commit nhỏ, message tiếng Việt hoặc tiếng Anh đều được, miễn rõ nghĩa.
- Trước khi mở PR: `ruff check .` phải sạch, `pytest -q` không thêm FAIL mới.
- PR vào `main`, tag Phi review.
- **Không** commit `outputs/`, `traces/`, `.env`, `dist/` — đã có trong `.gitignore`.

---

## 5. PHẦN VIỆC CỦA BẢO — Order / Item / Shipment

**Nhánh:** `feat/order-shipment`
**File sở hữu:** `src/student_agent/agents/order_agent.py`, `src/student_agent/agents/shipment_agent.py`, `tests/test_order_shipment.py`
**Chịu trách nhiệm 4 giá trị `primary_issue`:** `canceled_order_paid`, `unavailable_order_paid`, `late_delivery_seller`, `late_delivery_logistics`

### B1 — Khảo sát dữ liệu (làm TRƯỚC, D1–D2)

```bash
python scripts/mcp_probe.py L3A_CASE_001
python scripts/mcp_probe.py L3A_CASE_013   # case có claim late_delivery_seller
python scripts/mcp_probe.py L3A_CASE_004   # case có claim late_delivery_logistics
```

Ghi lại **tên field thực tế** trong `data` của 5 tool thuộc phạm vi của bạn vào `docs/domain-order-shipment.md`, kèm 1 response mẫu mỗi tool.

> Tool của bạn: `get_order`, `get_order_items`, `get_sellers`, `get_product_context`, `get_shipment_summary` (xem mục 4.6).
>
> 📄 **Đọc [`docs/mcp-evidence-shapes.md`](docs/mcp-evidence-shapes.md) trước.** Phi đã khảo sát `L3A_CASE_001` và ghi lại cấu trúc `data` thật của cả 5 tool này. Ba điều bất ngờ đã phát hiện:
>
> - Mọi số tiền trả về dạng **chuỗi** (`"79.00"`), phải convert trước khi tính.
> - `get_shipment_summary` đặt tên field **khác** `get_order` cho cùng một sự kiện (`delivered_carrier_at` vs `order_delivered_carrier_date`) → nguồn của `data_conflicts`.
> - `get_shipment_summary` có `events[]` với `event_type: "delivered_late"` và `actor: "seller"` — **quy trách nhiệm trực tiếp**, mạnh hơn suy từ timestamp. Ưu tiên dùng.

**Định nghĩa hoàn thành:** có file ghi chú liệt kê đủ field của từng domain kèm 1 response mẫu.

### B2 — `order_agent.py`

Lấy order theo `claimed_order_id`, lấy items và seller.

Sinh tín hiệu từ `order_status` (Olist có: `delivered`, `shipped`, `canceled`, `unavailable`, `invoiced`, `processing`, `approved`, `created`):

| `order_status` | Tín hiệu |
| --- | --- |
| `canceled` | `ORDER_STATUS_CANCELED` |
| `unavailable` | `ORDER_STATUS_UNAVAILABLE` |
| `delivered` | `ORDER_STATUS_DELIVERED` |
| `shipped` | `ORDER_STATUS_SHIPPED` |
| khác | `ORDER_STATUS_OTHER` |
| không tìm thấy order | `ORDER_NOT_FOUND` |

`facts` cần có: `order_status`, `order_purchase_timestamp`, `order_total_brl` (tổng `price` + `freight_value` của các item — Quốc cần số này để đối chiếu thanh toán).

### B3 — Trích entity

Điền `entities` trong `Finding`:

- `order_ids` — order đang xét
- `item_ids` — id các item trong order
- `seller_ids` — seller của các item
- `shipment_ids` — nếu domain `shipment` có id riêng

Ràng buộc schema: mỗi mảng **≤ 20 phần tử, không trùng lặp**, mỗi id ≤ 128 ký tự.

### B4 — Luật `canceled_order_paid` / `unavailable_order_paid`

Đây là hai issue "đơn bị hủy/hết hàng nhưng khách đã trả tiền". Bạn phát tín hiệu trạng thái đơn, Quốc phát tín hiệu đã thu tiền, `rules.py` ghép lại:

```
ORDER_STATUS_CANCELED    + PAY_CAPTURED  →  canceled_order_paid
ORDER_STATUS_UNAVAILABLE + PAY_CAPTURED  →  unavailable_order_paid
```

Bạn **không** tự kết luận, chỉ lo phần trạng thái đơn cho chính xác.

### B5 — `shipment_agent.py`: phân biệt trễ do seller hay do logistics

Đây là phần khó nhất và đáng giá nhất của bạn. Mốc thời gian (tên theo Olist gốc, **cần verify**):

```
order_purchase_timestamp
    → order_approved_at
        → shipping_limit_date          (hạn seller phải bàn giao cho carrier)
        → order_delivered_carrier_date (thực tế seller bàn giao)
            → order_delivered_customer_date  (thực tế khách nhận)
              order_estimated_delivery_date  (hạn cam kết giao cho khách)
```

Luật đề xuất:

| Điều kiện | Tín hiệu |
| --- | --- |
| `order_delivered_carrier_date > shipping_limit_date` | `SHIP_LATE_SELLER` — seller bàn giao trễ |
| Seller đúng hạn **nhưng** `order_delivered_customer_date > order_estimated_delivery_date` | `SHIP_LATE_LOGISTICS` — vận chuyển trễ |
| `order_delivered_customer_date <= order_estimated_delivery_date` | `SHIP_ON_TIME` |
| Chưa có `order_delivered_customer_date` | `SHIP_NOT_DELIVERED` |
| Thiếu mốc cần thiết để kết luận | `SHIP_TIMELINE_INCOMPLETE` |
| Mốc vô lý (giao cho khách trước khi bàn giao carrier, v.v.) | `SHIP_TIMELINE_CONFLICT` |

**Ưu tiên khi cả hai cùng trễ:** nếu seller trễ hạn bàn giao *và* giao khách cũng trễ → phát **cả hai** tín hiệu, để `rules.py` quyết theo mức độ đóng góp. Ghi vào `facts` số ngày trễ của từng chặng: `seller_delay_days`, `logistics_delay_days`.

`facts` cần có: đủ 5 mốc thời gian ở dạng chuỗi ISO + 2 số ngày trễ ở trên.

**Cẩn thận múi giờ:** `opened_at` trong input là `-03:00`. So sánh datetime phải cùng timezone, đừng so chuỗi.

### B6 — Nguyên nhân gốc và bên chịu trách nhiệm

Điền vào `facts` để `rules.py` dựng `root_cause_analysis`:

- `ranked_causes` — mã dạng `^[A-Z][A-Z0-9_]{2,79}$`, ví dụ `SELLER_HANDOVER_DELAY`, `CARRIER_TRANSIT_DELAY`, `ORDER_CANCELED_AFTER_PAYMENT`. Rank 1–5, tối đa 5 mục.
- `responsible_parties` — `party_type` ∈ `seller | platform | logistics_provider | payment_provider | customer | unknown`, kèm `party_id` (seller_id thật nếu quy cho seller, `null` nếu không xác định).

### B7 — Xung đột dữ liệu

Nếu hai nguồn nói khác nhau (ví dụ domain `order` và domain `shipment` báo ngày giao khác nhau), thêm vào `conflicts`:

```python
{
  "field": "order_delivered_customer_date",
  "sources": ["order", "shipment"],      # BẮT BUỘC ≥ 2 nguồn
  "selected_source": "shipment",
  "resolution_code": "PREFER_SHIPMENT_TIMELINE",
}
```

### B8 — Test

`tests/test_order_shipment.py` — test **luật thuần**, dùng fixture dict giả lập response MCP, **không gọi mạng thật**. Tối thiểu 8 case: mỗi tín hiệu shipment 1 test + 2 test biên (đúng deadline, thiếu mốc).

### B9 — Tài liệu

Điền `ARCHITECTURE.md` **mục 2**, hai dòng `Order/item` và `Shipment`: input, trách nhiệm, output/handoff, và **tool nào agent của bạn được phép gọi** (không cho agent quyền gọi mọi tool).

### Bảo gửi lại gì cho Phi

- [ ] `docs/domain-order-shipment.md` (D2)
- [ ] `order_agent.py` + `shipment_agent.py` chạy được, trả `Finding` hợp lệ (D4)
- [ ] `tests/test_order_shipment.py` xanh (D4)
- [ ] Bảng luật shipment đã verify với field thật (D4, mang tới buổi họp)
- [ ] `ARCHITECTURE.md` mục 2 phần của mình (D6)

---

## 6. PHẦN VIỆC CỦA QUỐC — Payment / Refund / Policy / Money

**Nhánh:** `feat/payment-policy`
**File sở hữu:** `src/student_agent/agents/payment_agent.py`, `src/student_agent/agents/policy_agent.py`, `src/student_agent/domain/money.py`, `tests/test_payment_money.py`
**Chịu trách nhiệm 5 giá trị `primary_issue`:** `valid_split_payment`, `payment_mismatch`, `duplicate_charge`, `refund_pending`, `refund_failed`

### Q1 — Khảo sát dữ liệu (làm TRƯỚC, D1–D2)

```bash
python scripts/mcp_probe.py L3A_CASE_001
python scripts/mcp_probe.py L3A_CASE_007   # case có claim duplicate_charge
python scripts/mcp_probe.py L3A_CASE_009   # case có claim refund_failed
```

Ghi field thực tế của 4 tool thuộc phạm vi của bạn vào `docs/domain-payment-policy.md`.

> Tool của bạn: `get_order_payments`, `get_payment_timeline`, `get_refund_timeline`, `get_policy` (xem mục 4.6).
>
> 📄 **Đọc [`docs/mcp-evidence-shapes.md`](docs/mcp-evidence-shapes.md) trước.** Bốn phát hiện đổi hẳn cách làm phần của bạn:
>
> - 🔑 **`get_policy` trả sẵn bảng quy tắc theo từng issue**: `case_status`, `recommended_action`, `refund_brl`, `responsible_parties`. Nghĩa là bài toán quy về *xác định đúng `primary_issue`*, phần còn lại **đọc từ policy** thay vì tự suy. Phi đã nối sẵn vào `rules.py` và `money.py` — việc của bạn là đưa `facts["policy_rules"]` vào từ `policy_agent`.
> - Case 001 có 2 dòng payment **cùng `payment_sequential = "1"`** → không dùng field này làm khoá phân biệt được.
> - Mọi số tiền là **chuỗi** (`"79.00"`), riêng `refund_brl` trong policy là số thật.
> - `get_refund_timeline` **trả lỗi** trên case không có refund, không trả rỗng. Phải bắt lỗi → `REFUND_NONE`, không để crash.
>
> ❓ **Việc xác minh đầu tiên của bạn:** gọi `get_policy` trên 2–3 case khác nhau, so `refund_brl`. Nếu đổi theo case thì policy là per-case (dùng thẳng); nếu giống hệt thì là bảng tĩnh và `party_id` phải tự điền từ `get_order_items`. Kết quả quyết định cách viết `money.py`.

**Định nghĩa hoàn thành:** file ghi chú đủ field từng domain + 1 response mẫu, **đặc biệt là schema của domain `refund` và `policy`** — hai domain này không có trong dataset Olist công khai nên chắc chắn là do ban tổ chức tự định nghĩa.

### Q2 — `payment_agent.py`

Lấy các bản ghi thanh toán của order. Olist cho nhiều dòng payment mỗi order, phân biệt bằng `payment_sequential`.

`facts` cần có: `payment_rows` (danh sách), `captured_total_brl` (tổng `payment_value`), `payment_types` (tập `payment_type`), `max_installments`.

### Q3 — Ba luật thanh toán (phần nặng nhất của bạn)

Cần `order_total_brl` từ Finding của Bảo — Phi sẽ truyền sang qua coordinator. Nếu chưa có, tạm tự tính từ domain `item`.

| Tình huống | Dấu hiệu | Tín hiệu |
| --- | --- | --- |
| **Split hợp lệ** | Nhiều dòng payment, `payment_type` khác nhau (ví dụ `voucher` + `credit_card`), **tổng khớp** `order_total_brl` | `PAY_SPLIT_VALID` |
| **Thu trùng** | Hai dòng **cùng** `payment_type`, **cùng hoặc gần bằng** số tiền, tổng **vượt** `order_total_brl` | `PAY_DUPLICATE` |
| **Lệch tiền** | `captured_total_brl` ≠ `order_total_brl` ngoài dung sai, không khớp hai mẫu trên | `PAY_MISMATCH` |
| Khớp bình thường | Tổng khớp trong dung sai | `PAY_CAPTURED` |
| Không có bản ghi payment | — | `PAY_NONE` |

**Dung sai:** đề xuất `abs(diff) <= 0.01` BRL (sai số làm tròn). Chốt con số này ở buổi họp D4 và ghi vào `ARCHITECTURE.md`.

**Phân biệt `PAY_SPLIT_VALID` với `PAY_DUPLICATE` là điểm dễ sai nhất** — cả hai đều "nhiều dòng payment". Khác nhau ở: split thì **tổng khớp** và thường **khác loại**; duplicate thì **tổng vượt** và thường **cùng loại, cùng số tiền**. Ghi rõ lý do phân loại vào `facts["payment_reason"]` để verifier kiểm tra được.

### Q4 — Trạng thái hoàn tiền

Từ domain `refund`: `REFUND_NONE` / `REFUND_PENDING` / `REFUND_FAILED` / `REFUND_COMPLETED`.

`facts` cần có: `refunded_total_brl`, `refund_status`, thời điểm yêu cầu hoàn nếu có.

Nhớ đọc `evidence.get("warnings", [])` — response MCP có field `warnings`, rất có thể chứa tín hiệu như "refund gateway timeout" dẫn tới `REFUND_FAILED`.

### Q5 — Entity

Điền `entities["payment_references"]` — id/tham chiếu của từng giao dịch thanh toán. Tối đa 20, không trùng.

### Q6 — `domain/money.py`: tính tiền hoàn

Đây là module tính toán thuần, **không gọi MCP**, dễ test:

```python
def compute_refund(order_total_brl, captured_total_brl, refunded_total_brl,
                   signals, policy) -> tuple[float, list[dict]]:
    """Trả về (recommended_refund_brl, refund_lines)."""
```

`refund_lines` — mỗi dòng `{"reason_code": str, "amount_brl": float >= 0, "entity_id": str | None}`, tối đa 10 dòng.

Ví dụ mong đợi:

- Đơn bị hủy nhưng đã thu tiền → 1 dòng hoàn toàn bộ `captured_total_brl`, `reason_code` = `CANCELED_ORDER_FULL_REFUND`
- Thu trùng → chỉ hoàn **phần dư**, không hoàn toàn bộ: `captured_total_brl - order_total_brl`, `reason_code` = `DUPLICATE_CHARGE_EXCESS`
- Giao trễ do logistics → theo `EC_POLICY_V1` quy định (tra ở Q8), có thể chỉ hoàn phí ship
- Đã hoàn xong rồi → `recommended_refund_brl = 0`, `refund_lines = []`

**Làm tròn:** 2 chữ số thập phân, dùng `round(x, 2)`. Tránh sai số float bằng cách cộng bằng `Decimal` rồi mới `float()` ở bước cuối.

### Q7 — Bất biến tiền (verifier của Phi sẽ gọi)

Viết thành hàm thuần trong `money.py` để Phi import:

```python
def check_money_invariants(output: dict) -> list[str]:
    """Trả về danh sách lỗi; rỗng nghĩa là hợp lệ."""
```

Bắt buộc kiểm:

1. `sum(line["amount_brl"] for line in refund_lines)` == `recommended_refund_brl` (dung sai 0.01)
2. `case_status == "no_action"` ⇒ `recommended_refund_brl == 0`
3. Mọi `amount_brl >= 0`, `recommended_refund_brl >= 0`
4. `recommended_refund_brl <= captured_total_brl` (không hoàn nhiều hơn số đã thu)
5. `currency == "BRL"`

Đây là phần trực tiếp ăn **10% điểm consistency**.

### Q8 — `policy_agent.py`

Tra policy `EC_POLICY_V1` qua domain `policy`. Xác định với mỗi loại issue thì khách được gì: hoàn toàn bộ, hoàn một phần, hay không hoàn → `POLICY_REFUND_FULL` / `POLICY_REFUND_PARTIAL` / `POLICY_NO_REFUND`.

Ghi vào `facts` điều khoản nào được áp dụng để trích dẫn evidence chính xác.

### Q9 — Từ vựng cố định

Chốt **danh sách đóng** cho hai thứ, không sinh chuỗi tự do (verifier sẽ chặn giá trị lạ):

- `resolution_actions` — tối đa 8 mục, không trùng, mỗi mục ≤ 80 ký tự. Ví dụ: `ISSUE_FULL_REFUND`, `ISSUE_PARTIAL_REFUND`, `ESCALATE_TO_SELLER`, `ESCALATE_TO_LOGISTICS`, `RETRY_REFUND`, `REQUEST_MORE_EVIDENCE`, `NO_ACTION`
- `reason_code` trong `refund_lines` — ví dụ: `CANCELED_ORDER_FULL_REFUND`, `UNAVAILABLE_ORDER_FULL_REFUND`, `DUPLICATE_CHARGE_EXCESS`, `LATE_DELIVERY_FREIGHT_REFUND`, `PAYMENT_MISMATCH_ADJUSTMENT`

Gửi danh sách đề xuất cho cả nhóm trước buổi họp D4.

### Q10 — Xung đột số tiền

Nếu domain `payment` và domain `order` báo số tiền khác nhau, thêm vào `conflicts` (cấu trúc giống mục B7, **bắt buộc ≥ 2 nguồn**).

### Q11 — Test

`tests/test_payment_money.py` — tối thiểu 10 test: mỗi tín hiệu payment 1 test, mỗi bất biến tiền 1 test, cộng 2 test biên (tổng lệch đúng 0.01; thu trùng đúng gấp đôi).

### Q12 — Tài liệu

Điền `ARCHITECTURE.md`:
- **Mục 2**, hai dòng `Payment` và `Policy`
- **Mục 4** Evidence lifecycle — cách validate response MCP, lưu `evidence_ref`, map evidence vào claim/output
- **Mục 5** Failure policy — bảng: MCP timeout / not found / xung đột nguồn / kết quả specialist không hợp lệ → có retry không, fallback gì, trace event/code nào. Retry phải có giới hạn và idempotent; **không được biến missing evidence thành dữ liệu phỏng đoán**.

### Quốc gửi lại gì cho Phi

- [ ] `docs/domain-payment-policy.md` (D2) — ưu tiên schema domain `refund` và `policy`
- [ ] `payment_agent.py` + `policy_agent.py` trả `Finding` hợp lệ (D4)
- [ ] `money.py` với `compute_refund()` + `check_money_invariants()` (D4)
- [ ] `tests/test_payment_money.py` xanh (D4)
- [ ] Danh sách `resolution_actions` + `reason_code` đề xuất (D3, gửi trước buổi họp)
- [ ] `ARCHITECTURE.md` mục 2 (phần mình), 4, 5 (D6)

---

## 7. Việc chung — buổi họp chốt luật (D4, cả nhóm bắt buộc có mặt)

Sáu thứ không ai tự quyết được, phải thống nhất:

| # | Nội dung | Chuẩn bị trước |
| --- | --- | --- |
| C1 | **Ma trận ưu tiên `primary_issue`** khi nhiều tín hiệu cùng bật. Ví dụ đơn vừa `canceled` vừa `PAY_DUPLICATE` → chọn cái nào? | Mỗi người liệt kê case thực tế gặp tổ hợp tín hiệu |
| C2 | Ranh giới `unsupported_claim` (có evidence và evidence bác bỏ khiếu nại) vs `insufficient_evidence` (không đủ evidence để kết luận) | Quốc + Phi |
| C3 | Ánh xạ `case_status` (`action_required` / `no_action` / `needs_investigation`) theo từng `primary_issue` | Cả nhóm |
| C4 | Chính sách trích dẫn evidence — cite bao nhiêu là đủ (F1 phạt cả thiếu lẫn thừa) | Phi trình bày |
| C5 | Thang `confidence` | Phi trình bày |
| C6 | Chốt dung sai tiền (0.01 BRL?) và ngưỡng ngày trễ | Quốc + Bảo |

Sau buổi họp, Phi viết kết quả vào `domain/rules.py` và `REPORT.md` mục 7.

---

## 8. Kế hoạch — Lab 240 phút / 6 pha (theo slide ban tổ chức)

> Đây là lab **4 tiếng tại lớp**, không phải nhiều ngày. Bản kế hoạch D1–D7 trước đó đã sai
> và được thay bằng bảng này.

| Pha | Nội dung theo slide | Phút | Trạng thái nhóm |
| --- | --- | ---: | --- |
| 1 | Đăng ký Team, `.env`, MCP Ping | 30 | ✅ Xong — `day09 mcp-tools` trả 10 tool |
| 2 | Thiết kế Multi-Agent A2A | 35 | ✅ Xong — `a2a.py`, `findings.py`, `ARCHITECTURE.md` |
| 3 | Specialist Agents + MCP Gateway | 45 | ✅ Xong — 4 agent của Bảo và Quốc, đã merge |
| 4 | Policy, Verifier & Calibration | 40 | ✅ Xong — `policy_agent`, `verifier`, `money.py` |
| 5 | **Kích hoạt Workspace, Batch 100** | **60** | ⏳ **Đang ở đây** |
| 6 | **ZIP, Nộp Workspace & GitHub** | **30** | ⬜ Chưa |

**Còn lại khoảng 90 phút.** Thứ tự bắt buộc:

1. Smoke test 5 case xanh → `git checkout main && git merge integrate/bao-quoc`
2. `git push origin main` (Contributors phải đủ 3 tên — đã kiểm, đạt)
3. `day09 run` cho 100 case — **chỉ một người chạy**, gateway throttle theo team key
4. `day09 validate` → `day09 package --output dist/submission.zip`
5. Upload ZIP lên Workspace `/l3a`
6. Nhóm trưởng nộp link GitHub lên VLearn LMS **trước 23:59 hôm nay**

### Chiến thuật nộp bài

Slide ghi **"Re-Submit Sau 120 Giây"** và **"LIVE LEADERBOARD (VM AUTO-SCORER)"**.
Nghĩa là nộp được nhiều lần, mỗi lần cách nhau 2 phút, và thấy điểm public ngay.

Vì vậy: **nộp bản chạy được sớm nhất có thể**, kể cả điểm thấp, rồi đọc breakdown
để biết thành phần nào yếu mà sửa. Đừng dồn tất cả vào một lần nộp cuối — mất
cơ hội dùng feedback.

Slide cũng ghi **"Thưởng Điểm Top 10 Cuối Buổi"**.

## 9. Hỏi đáp nhanh

**Không biết tool tên gì?** → `day09 mcp-tools`. Đừng đoán.

**Tool trả lỗi / không tìm thấy dữ liệu?** → Phát tín hiệu `*_NOT_FOUND` hoặc `*_INCOMPLETE`. **Tuyệt đối không bịa dữ liệu thay thế.**

**Field trong `data` khác với giả định trong file này?** → Báo nhóm ngay, cập nhật lại bảng luật. File này viết dựa trên dataset Olist gốc, gateway có thể đặt tên khác.

**Cần tín hiệu mới ngoài danh sách 4.4?** → Nhắn Phi trước, để Phi cập nhật `rules.py` đồng bộ. Tự đặt mã mới thì `rules.py` sẽ bỏ qua tín hiệu đó.

**Cần sửa file của người khác?** → Nhắn chủ file hoặc mở PR. Không commit thẳng.

**Có nên gọi thật nhiều tool cho chắc?** → Không. Điểm `evidence` là F1, cite thừa bị phạt. Gọi đủ dùng, cite đúng cái dẫn tới kết luận.

---

## 10. Checklist cá nhân trước khi mở PR

- [ ] `ruff check .` sạch
- [ ] `pytest -q` không thêm FAIL mới (ngoài `test_release_safety.py` đã biết)
- [ ] Mỗi `gateway.call()` dẫn tới kết luận đều có `trace.emit(event_type="tool_result_consumed", evidence_refs=[...])` đi kèm
- [ ] Không có `evidence_ref` nào bị sửa, bịa, hoặc hard-code
- [ ] Không cite ref không dùng để kết luận
- [ ] `Finding.signals` chỉ chứa mã trong từ vựng mục 4.4
- [ ] Không commit `.env`, `outputs/`, `traces/`, `dist/`
- [ ] Không đụng file ngoài phạm vi sở hữu của mình
