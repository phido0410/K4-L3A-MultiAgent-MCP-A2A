# L3A — Báo cáo công việc nhóm

> File này là tài liệu sống: cập nhật mục 6 (Nhật ký) và mục 8 (Điểm submission) sau mỗi buổi làm việc.

---

## 1. Thông tin chung

| Mục | Giá trị |
| --- | --- |
| Cuộc thi | Day09 — K4 L3A Multi-Agent MCP + A2A (`day09-multiagent-mcp-a2a`) |
| Variant | `l3a` — 100 case (50 public / 50 private) |
| Repo | `K4-L3A-MultiAgent-MCP-A2A` (giữ nguyên tên gốc, không đổi) |
| Team name | _TODO: điền sau khi `/register`_ |
| Thời lượng | **240 phút / 6 pha** (lab tại lớp) |
| Hạn nộp link GitHub | **23:59 hôm nay**, lên VLearn LMS — nhóm trưởng nộp |
| Nộp lại | Được, **mỗi 120 giây**; leaderboard chấm tự động theo thời gian thực |
| Ngày khởi động | 2026-09-25 |

### Thành viên

| Họ tên | Vai trò | Sở hữu chính |
| --- | --- | --- |
| Đỗ Ngọc Phi | Lead / Coordinator / Integration | Orchestration, A2A, Verifier, Submission |
| Nguyễn Trường Bảo | Order & Shipment Analyst | Đơn hàng, item, vận chuyển, entity, trách nhiệm |
| Phạm Cường Quốc | Payment & Policy Analyst | Thanh toán, hoàn tiền, policy, tính tiền |

---

## 2. Tóm tắt bài lab

Xây hệ multi-agent điều tra khiếu nại e-commerce (dữ liệu Olist Brazilian E-Commerce). Mỗi case gồm khiếu nại tiếng Việt + `claimed_order_id` + 2 claim. Agent phải lấy bằng chứng qua **MCP Evidence Gateway**, phối hợp giữa các agent, rồi xuất `outputs/<case_id>.json` và `traces/trace.jsonl` đúng public contract.

**Ràng buộc cốt lõi**

- Customer message **không phải** ground truth — phải verify bằng evidence.
- `claims[0].topic` phân bố đều 10 case cho mỗi giá trị của enum `primary_issue`, và message chỉ có 4 mẫu xoay vòng độc lập với topic → topic là *cáo buộc*, không phải đáp án.
- Không được bịa hoặc sửa `evidence_ref`, không dùng evidence chéo case.

**Trọng số điểm**

| Thành phần | Trọng số | Người chịu trách nhiệm chính |
| --- | ---: | --- |
| `semantic` | 45% | Bảo + Quốc (luật suy luận), Phi (thứ tự ưu tiên) |
| `evidence` | 15% | Cả nhóm — chính sách trích dẫn do Phi chốt |
| `provenance` | 15% | Phi |
| `consistency` | 10% | Phi (verifier) + Quốc (bất biến tiền) |
| `schema` | 5% | Phi |
| `calibration` | 5% | Phi |
| `workflow` | 5% | Phi |
| `efficiency` | 0% | — (không tính điểm ở L3A nhưng vẫn bị audit) |

**Hard gate → case bị 0 điểm:** sai `case_id`; schema không chấm được; thiếu evidence bắt buộc; `evidence_ref` sai định dạng / không tồn tại / thuộc team-run-case khác.

**Leaderboard cuối:** 20% public + 80% private.

---

## 3. Kiến trúc module & phân chia quyền sở hữu file

Chỉ `solve_case()` trong `workflow.py` là TODO, nhưng nhóm sẽ tách thành nhiều module để 3 người code song song mà không conflict. **Mỗi file có đúng một chủ sở hữu** — người khác muốn sửa thì mở PR, không commit thẳng.

```text
src/student_agent/
├── workflow.py              [PHI]   coordinator mỏng, chỉ điều phối
├── a2a.py                   [PHI]   message envelope, handoff, chống lặp
├── domain/
│   ├── findings.py          [PHI]   dataclass hợp đồng giữa các agent (LÀM TRƯỚC — chặn mọi người)
│   ├── rules.py             [PHI]   ma trận quyết định primary_issue (họp chốt cả nhóm)
│   └── money.py             [QUỐC]  tính refund, làm tròn BRL, bất biến tiền
└── agents/
    ├── order_agent.py       [BẢO]   order + item + seller, trích entity
    ├── shipment_agent.py    [BẢO]   timeline giao hàng, quy trách nhiệm trễ
    ├── payment_agent.py     [QUỐC]  payment, installment, refund state
    ├── policy_agent.py      [QUỐC]  EC_POLICY_V1, quyền lợi, reason code
    └── verifier.py          [PHI]   kiểm tra bất biến trước khi finalize
```

Thêm subpackage cần có `__init__.py`; `setuptools` đã cấu hình `packages.find where=["src"]` nên tự nhận.

**Quy tắc chặn/không chặn:** `domain/findings.py` phải xong trước (Phi, Phase 0) vì nó định nghĩa kiểu dữ liệu mà Bảo và Quốc trả về. Sau khi có file đó, hai người làm song song với stub.

---

## 4. Phân công chi tiết

> Bản briefing gửi cho Bảo và Quốc (tự chứa: ngữ cảnh, setup, hợp đồng code, định nghĩa hoàn thành): [`PHAN_CONG.md`](PHAN_CONG.md). Khi đổi phân công, cập nhật cả hai file.

### 4.1 Đỗ Ngọc Phi — Lead / Coordinator / Verifier / Submission

| # | Đầu việc | Deliverable | Điểm liên quan |
| --- | --- | --- | --- |
| P1 | Dựng môi trường: venv 3.11, `pip install -e ".[dev]"`, `.env` | Cả nhóm chạy được `day09 --help` | — |
| P2 | Đăng ký team tại `/register`, lưu `sk-team-...` an toàn | Team API key (KHÔNG commit) | — |
| P3 | Discovery MCP: `day09 mcp-tools`, dump input schema + response mẫu | `docs/mcp-tools.md` | provenance |
| P4 | Định nghĩa `domain/findings.py` (hợp đồng giữa các agent) | Dataclass `OrderFinding`, `ShipmentFinding`, `PaymentFinding`, `PolicyFinding`, `EvidenceItem` | — |
| P5 | `a2a.py`: envelope, correlation theo `case_id`, điều kiện handoff, timeout, chống vòng lặp | Module + test | workflow |
| P6 | `workflow.py`: coordinator điều phối + emit `task_assigned`, `handoff`, `policy_decided`, `verification_completed` | Trace đủ 5 lifecycle event bắt buộc | workflow 5% |
| P7 | `domain/rules.py`: ma trận ưu tiên `primary_issue` khi nhiều tín hiệu cùng bật | Bảng luật có tài liệu | semantic 45% |
| P8 | `agents/verifier.py`: bất biến trước finalize (schema, entity scope, evidence ownership, claim linkage, tổng tiền, status↔action, confidence bound) | Module + test | consistency 10% |
| P9 | Chính sách trích dẫn evidence (F1: đủ coverage, không cite thừa) | Tài liệu + hàm lọc ref | evidence 15% |
| P10 | Công thức `confidence` (calibration = `1 − (đúng − confidence)²`) | Hàm calibrate | calibration 5% |
| P11 | Kỷ luật provenance: không tái dùng ref chéo case, không sửa ref | Assert trong gateway wrapper | provenance 15% |
| P12 | Chạy `day09 run` / `validate` / `package`, nộp và theo dõi điểm public | `dist/submission.zip` | — |
| P13 | `ARCHITECTURE.md` §1 System overview, §3 A2A protocol, §6 Verification invariants, §7 Reproducibility | — | — |
| P14 | Xử lý `tests/test_release_safety.py` đang FAIL + giữ CI xanh | CI xanh | — |
| P15 | Cập nhật `REPORT.md` sau mỗi buổi | File này | — |

### 4.2 Nguyễn Trường Bảo — Order / Item / Shipment / Entity

| # | Đầu việc | Deliverable | Điểm liên quan |
| --- | --- | --- | --- |
| B1 | Khảo sát tool domain `order`, `item`, `seller`, `shipment`, `product` trên 3-5 case mẫu | Ghi chú field thực tế trả về | evidence |
| B2 | `agents/order_agent.py`: lấy order + items + seller, đọc `order_status` | `OrderFinding` | semantic |
| B3 | Trích `affected_entities`: `order_ids`, `item_ids`, `seller_ids`, `shipment_ids` (≤20 mỗi mảng, unique) | Phần entity của output | schema, consistency |
| B4 | Luật nhận diện `canceled_order_paid` và `unavailable_order_paid` (order_status × có payment) | Rule + test | semantic |
| B5 | `agents/shipment_agent.py`: phân tích timeline `approved_at` → `carrier_date` → `delivered_customer_date` so với `estimated_delivery_date` | `ShipmentFinding` | semantic |
| B6 | Phân biệt `late_delivery_seller` (chậm bàn giao cho carrier) vs `late_delivery_logistics` (carrier giao chậm) | Ngưỡng + luật có tài liệu | semantic 45% |
| B7 | `root_cause_analysis`: `ranked_causes` (mã `^[A-Z][A-Z0-9_]{2,79}$`) + `responsible_parties` cho nhóm nguyên nhân giao hàng/đơn hàng | Phần output | semantic, consistency |
| B8 | `data_conflicts` cho xung đột timeline (ví dụ delivered trước shipped) | Mục conflict ≥2 sources | consistency |
| B9 | Emit `tool_result_consumed` với đúng `evidence_ref` cho mọi kết luận của mình | Trace | evidence, workflow |
| B10 | Unit test cho luật order/shipment (dùng fixture, không gọi MCP thật) | `tests/test_order_shipment.py` | — |
| B11 | `ARCHITECTURE.md` §2 dòng Order/Item và Shipment | — | — |

### 4.3 Phạm Cường Quốc — Payment / Refund / Policy / Money

| # | Đầu việc | Deliverable | Điểm liên quan |
| --- | --- | --- | --- |
| Q1 | Khảo sát tool domain `payment`, `refund`, `policy`, `customer` trên 3-5 case mẫu | Ghi chú field thực tế | evidence |
| Q2 | `agents/payment_agent.py`: đọc bản ghi payment, `payment_type`, `payment_installments`, `payment_value` | `PaymentFinding` | semantic |
| Q3 | Phân biệt `valid_split_payment` (nhiều dòng hợp lệ) vs `duplicate_charge` (thu trùng) vs `payment_mismatch` (không khớp tổng đơn) | Rule + test | semantic 45% |
| Q4 | Trạng thái hoàn tiền: `refund_pending` vs `refund_failed` vs đã hoàn | Rule + test | semantic |
| Q5 | Trích `payment_references` cho `affected_entities` | Phần entity | schema |
| Q6 | `domain/money.py`: `recommended_refund_brl`, `refund_lines[{reason_code, amount_brl, entity_id}]`, làm tròn BRL 2 chữ số | Module + test | semantic, consistency |
| Q7 | Bất biến tiền (hàm thuần để verifier gọi): tổng `refund_lines` == `recommended_refund_brl`; `no_action` ⇒ refund = 0; mọi `amount_brl ≥ 0` | Hàm invariant | consistency 10% |
| Q8 | `agents/policy_agent.py`: tra `EC_POLICY_V1`, xác định quyền lợi theo từng loại issue | `PolicyFinding` | semantic |
| Q9 | Từ vựng `resolution_actions` (≤8, unique, ≤80 ký tự) và `reason_code` — chốt danh sách cố định, không sinh tự do | Bảng vocabulary | consistency |
| Q10 | Luật `unsupported_claim` vs `insufficient_evidence` (phối hợp với Phi) | Rule có tài liệu | semantic |
| Q11 | `data_conflicts` cho xung đột số tiền giữa các nguồn | Mục conflict | consistency |
| Q12 | Emit `tool_result_consumed` với đúng `evidence_ref` | Trace | evidence, workflow |
| Q13 | Unit test cho luật payment + số học tiền | `tests/test_payment_money.py` | — |
| Q14 | `ARCHITECTURE.md` §2 dòng Payment/Policy, §4 Evidence lifecycle, §5 Failure policy | — | — |

### 4.4 Việc làm chung (họp cả nhóm, không giao riêng)

| # | Nội dung | Vì sao phải họp |
| --- | --- | --- |
| C1 | **Ma trận ưu tiên `primary_issue`** — khi nhiều tín hiệu cùng bật (ví dụ đơn bị hủy *và* thanh toán trùng), chọn cái nào? | Ảnh hưởng trực tiếp 45% điểm, cần thống nhất tuyệt đối |
| C2 | Ranh giới `unsupported_claim` vs `insufficient_evidence` | Hai giá trị dễ nhầm, sai là mất điểm semantic |
| C3 | Ánh xạ `case_status` (`action_required` / `no_action` / `needs_investigation`) theo từng `primary_issue` | Bị chấm ở consistency |
| C4 | Chính sách trích dẫn evidence: cite bao nhiêu là đủ (F1 phạt cả thiếu lẫn thừa) | Ảnh hưởng 15% |
| C5 | Thang `confidence` theo mức chắc chắn | Ảnh hưởng 5% calibration |
| C6 | Review chéo output 10 case mẫu bằng tay trước khi nộp lần đầu | Bắt lỗi logic sớm |

---

## 5. Kế hoạch — Lab 240 phút / 6 pha (theo slide ban tổ chức)

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

## 6. Nhật ký công việc

| Ngày | Người | Việc đã làm | Kết quả / Ghi chú |
| --- | --- | --- | --- |
| 2026-09-25 | Phi | Đọc và phân tích toàn bộ repo starter | Xác định chỉ `solve_case()` là TODO; thống kê 100 input; xác nhận `claims[0].topic` phân bố đều 11 loại × 10 case, message chỉ 4 mẫu xoay vòng độc lập → topic là cáo buộc, không phải đáp án |
| 2026-09-25 | Phi | Lập kế hoạch phân công 3 người + tạo `REPORT.md` | File này |
| 2026-09-25 | Phi | Viết briefing `PHAN_CONG.md` gửi Bảo và Quốc | Tự chứa: ngữ cảnh, setup, hợp đồng code, định nghĩa hoàn thành |
| 2026-09-25 | Phi | **Sự cố bảo mật:** phát hiện Team API Key thật nằm trong `.env.example` (file được git theo dõi) | Chưa commit nên chưa lộ. Đã chuyển key sang `.env`, khôi phục `.env.example` về placeholder. Không cần đổi key |
| 2026-09-25 | Phi | Dựng môi trường: venv Python 3.11.4, `pip install -e ".[dev]"` | `day09 validate-inputs` OK 100 case |
| 2026-09-25 | Phi | **Discovery MCP — gỡ chặn R-03** | Xác nhận **10 tool**. Auth hợp lệ. Ghi vào `PHAN_CONG.md` mục 4.6 |
| 2026-09-25 | Phi | Viết `scripts/mcp_probe.py` khảo sát gateway bằng curl | Dùng được khi MCP SDK lỗi |
| 2026-09-25 | Phi | Dựng khung multi-agent: `domain/findings.py`, `domain/rules.py`, `a2a.py`, `workflow.py`, `agents/verifier.py` + 4 agent stub | Pipeline chạy thông, output hợp lệ schema |
| 2026-09-25 | Phi | Sửa `tests/test_release_safety.py` (R-01) | Đổi từ "không có file trên đĩa" sang "file không được git theo dõi" — bất biến đúng hơn. `pytest -q` xanh 10/10 |
| 2026-09-25 | Phi | Viết `ARCHITECTURE.md` mục 1, 2, 3, 6, 7 | Còn mục 4, 5 chờ Quốc |
| 2026-09-25 | Phi | Xác nhận `day09 mcp-tools` **hoạt động bình thường** — R-07 không phải lỗi SDK mà là giới hạn session | Đã sửa lại cảnh báo sai trong `PHAN_CONG.md` |
| 2026-09-25 | Phi | **Khảo sát dữ liệu thật** trên `L3A_CASE_001`, viết `docs/mcp-evidence-shapes.md` | Gỡ chặn R-08. Phát hiện lớn: `get_policy` trả sẵn `case_status` + `refund_brl` + `responsible_parties` cho từng issue |
| 2026-09-25 | Phi | Nối policy vào `rules.py` và `money.py` (policy có thẩm quyền cao hơn hằng số hard-code) | 10/10 test vẫn xanh |
| 2026-09-25 | Phi | Merge nhánh `Bao` và `cuongquoc_2A202602469`, viết lớp tích hợp `ScopedGateway` | 57 test xanh. Agent của hai bạn chạy nguyên không phải sửa |
| 2026-09-25 | Phi | **Tìm và sửa bug `order_total_brl` nhân đôi** trong `order_agent.py` | `get_order_items` trả lẫn dòng ngoài cửa sổ case; cộng hết làm `PAY_DUPLICATE` và `PAY_SPLIT_VALID` không bao giờ khớp |
| 2026-09-25 | Phi | Đối chiếu slide ban tổ chức, sửa kế hoạch D1–D7 thành 6 pha / 240 phút | Xem mục 5 và R-10 |
| | | _TODO_ | |

---

## 7. Nhật ký quyết định kỹ thuật

Ghi lại mọi quyết định có thể bị hỏi lại khi chấm. Không ghi prompt bí mật hay chain-of-thought.

| # | Ngày | Quyết định | Lý do | Người chốt |
| --- | --- | --- | --- | --- |
| D-001 | 2026-09-25 | Tách `solve_case` thành `agents/` + `domain/`, mỗi file một chủ sở hữu | 3 người code song song không conflict trên một file | Phi |
| D-002 | 2026-09-25 | Không suy ra `primary_issue` từ `claims[0].topic` | Topic phân bố đều 10/loại và độc lập với message → là cáo buộc, không phải ground truth | Phi |
| D-003 | 2026-09-25 | Specialist agent chỉ phát **tín hiệu**, không tự quyết `primary_issue` | Một agent hỏng không kéo theo kết luận sai; toàn bộ luật nằm một chỗ để review | Phi |
| D-004 | 2026-09-25 | Cưỡng chế allowlist tool theo actor (`a2a.py::TOOL_SCOPES`) | ARCHITECTURE mục 2 yêu cầu không cấp mọi tool cho mọi agent; cũng giúp trace quy được evidence về đúng actor | Phi |
| D-005 | 2026-09-25 | Coordinator và verifier **không** được cấp tool nào | Mọi evidence phải đi qua specialist để trace nhất quán | Phi |
| D-006 | 2026-09-25 | Verifier fail ⇒ ném lỗi, **không ghi output** | Thà thiếu output còn hơn nộp output sai bị hard gate | Phi |
| D-007 | 2026-09-25 | Không cấp `get_customer_history` cho agent nào | L3A chỉ điều tra một đơn theo `claimed_order_id`; tool này phục vụ L3B | Phi |
| D-008 | 2026-09-25 | Ma trận ưu tiên `primary_issue` bản v1 (`domain/rules.py`) | Thiệt hại tài chính chưa khắc phục > giao nhận > "không có vấn đề" | Phi — **chốt lại ở D4** |
| D-009 | 2026-09-25 | Giá trị từ `get_policy` có thẩm quyền cao hơn hằng số trong `rules.py` / `money.py` | Policy là nguồn chính thức, hằng số chỉ là fallback khi policy thiếu | Phi |
| D-010 | 2026-09-25 | `scripts/mcp_probe.py` luôn `DELETE` session trong `finally` | Session bỏ quên giữ slot và làm treo mọi kết nối sau | Phi |
| | | _TODO(D4): xác nhận hoặc sửa ma trận D-008_ | | |
| | | _TODO(D4): ngưỡng phân biệt late_delivery_seller vs logistics_ | | |
| | | _TODO(D4): dung sai tiền (đề xuất 0.01 BRL)_ | | |

---

## 8. Theo dõi điểm submission

| Lần | Ngày | semantic | evidence | provenance | consistency | schema | calibration | workflow | Tổng public | Thay đổi so với lần trước |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | | | | | | | | | | |
| 2 | | | | | | | | | | |
| 3 | | | | | | | | | | |

---

## 9. Rủi ro và vấn đề đang mở

| # | Vấn đề | Mức độ | Hướng xử lý | Ai |
| --- | --- | --- | --- | --- |
| R-01 | ~~`test_release_safety.py` FAIL~~ | ✅ **Đã xử lý 2026-09-25** | Đổi sang kiểm tra payload không được git theo dõi; 10/10 test xanh | Phi |
| R-02 | `.env.example` trỏ endpoint production, README hướng dẫn `127.0.0.1` | Thấp | Dùng giá trị trong `.env.example` | Phi |
| R-03 | ~~Chưa biết tool profile `l3a`~~ | ✅ **Đã xử lý 2026-09-25** | Xác nhận 10 tool, ghi ở `PHAN_CONG.md` mục 4.6 và cấu hình vào `a2a.py::TOOL_SCOPES` | Phi |
| R-07 | **Gateway giới hạn session đồng thời trên mỗi Team API Key.** Session không `DELETE` sẽ giữ slot, mọi kết nối sau treo tới hết timeout | Trung bình — tự hồi phục sau 5–10 phút | `day09 mcp-tools` và `day09 run` hoạt động bình thường khi không có session treo. Quy ước: **không ai chạy lệnh gọi MCP khi người khác đang chạy**; bị timeout thì chờ, đừng thử lại liên tục | Cả nhóm |
| R-08 | ~~Chưa biết cấu trúc `data`~~ | ✅ **Đã xử lý 2026-09-25** | Khảo sát `L3A_CASE_001`, ghi vào `docs/mcp-evidence-shapes.md`. Còn `get_refund_timeline` chưa có mẫu (case 001 không có refund) — Quốc khảo sát ở Q1 | Phi |
| R-10 | **Tên tool trong slide ban tổ chức không khớp gateway thật.** Slide ghi `get_payment`, `lookup_tracking`, `lookup_order`, `reconcile_payment` — không tool nào trong số này tồn tại | Thấp với nhóm ta (đã discovery), cao với nhóm khác | Dùng danh sách 10 tool thật ở `PHAN_CONG.md` mục 4.6. Slide chỉ mang tính minh hoạ | Cả nhóm |
| R-11 | Nếu `day09 run` bị throttle giữa chừng khi chạy 100 case thì mất thời gian pha 5 | Trung bình | Chỉ một người chạy, không ai gọi MCP song song. Nộp bản chạy được sớm rồi cải thiện, vì được nộp lại mỗi 120 giây | Phi |
| R-09 | Chưa rõ `get_policy` là per-case hay bảng tĩnh dùng chung. `late_delivery_seller.party_id` trên case 001 trỏ tới seller **không thuộc** order đó | Trung bình — ảnh hưởng cách viết `money.py` | Quốc gọi `get_policy` trên 2–3 case, so `refund_brl`. Đây là việc xác minh đầu tiên của Q1 | Quốc |
| R-04 | Cite thừa evidence làm tụt precision (điểm evidence là F1, không phải recall) | Cao | Chốt chính sách trích dẫn ở C4, verifier lọc ref không dùng để kết luận | Phi |
| R-05 | Mọi MCP call đều bị audit; gọi sai `case_id` gây hard gate `cross_scope_evidence_ref` | Cao | Luôn gọi qua `gateway.call()` (đã tự nhét `case_id`), cấm truyền tay | Cả nhóm |
| R-06 | Lộ `sk-team-...` khi commit | Cao | `.env` đã trong `.gitignore`; `submission.py` có quét secret; không paste key vào chat/issue | Cả nhóm |

---

## 10. Checklist trước khi nộp

- [ ] `day09 validate-inputs` OK (100 case)
- [ ] `day09 run` chạy hết 100 case, không exception
- [ ] `day09 validate` OK — đủ 100 output + trace hợp lệ
- [ ] Trace có đủ 5 lifecycle event bắt buộc: `case_received`, `task_assigned`, `handoff`, `verification_completed`, `case_finalized`
- [ ] Mỗi kết luận đều có `tool_result_consumed` kèm `evidence_ref` tương ứng
- [ ] Không có `evidence_ref` nào bị bịa, sửa, hoặc dùng chéo case
- [ ] `recommended_refund_brl` == tổng `refund_lines`
- [ ] `case_status` nhất quán với `primary_issue` và `resolution_actions`
- [ ] `ARCHITECTURE.md` không còn TODO
- [ ] `REPORT.md` cập nhật đến buổi cuối
- [ ] `day09 package --output dist/submission.zip` OK
- [ ] ZIP chỉ chứa `manifest.json`, `trace.jsonl`, `outputs/*.json` — không source, input, `.env`, log
- [ ] Upload tại workspace `/l3a`
