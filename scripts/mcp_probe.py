"""Khảo sát MCP Evidence Gateway bằng curl (dùng cho giai đoạn discovery).

Dùng curl thay vì mcp SDK vì một số môi trường chặn kết nối của httpx2.
Không dùng trong workflow chấm điểm — chỉ để xem schema dữ liệu thật.

    python scripts/mcp_probe.py L3A_CASE_001
    python scripts/mcp_probe.py L3A_CASE_001 --tool get_order --raw
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ORDER_TOOLS = [
    "get_order",
    "get_order_items",
    "get_order_payments",
    "get_shipment_summary",
    "get_sellers",
    "get_product_context",
    "get_payment_timeline",
    "get_refund_timeline",
]


def curl(endpoint: str, key: str, body: dict, session: str | None, dump: Path | None = None):
    cmd = [
        "curl", "-sS", "-m", "60", "-X", "POST", endpoint,
        "-H", f"Authorization: Bearer {key}",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-H", "MCP-Protocol-Version: 2025-06-18",
    ]
    if session:
        cmd += ["-H", f"Mcp-Session-Id: {session}"]
    if dump:
        cmd += ["-D", str(dump)]
    cmd += ["-d", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return None


def close_session(endpoint: str, key: str, session: str) -> None:
    """Đóng session. BẮT BUỘC gọi: gateway giới hạn số session đồng thời của team,
    session bỏ quên sẽ giữ slot và làm mọi kết nối sau đó bị timeout."""
    subprocess.run(
        ["curl", "-sS", "-m", "15", "-o", "/dev/null", "-X", "DELETE", endpoint,
         "-H", f"Authorization: Bearer {key}", "-H", f"Mcp-Session-Id: {session}"],
        capture_output=True, check=False,
    )


def open_session(endpoint: str, key: str) -> str:
    headers = ROOT / ".mcp-probe-headers.tmp"
    curl(endpoint, key, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "probe", "version": "0.1"}},
    }, None, dump=headers)
    session = ""
    for line in headers.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("mcp-session-id"):
            session = line.split(":", 1)[1].strip()
    headers.unlink(missing_ok=True)
    if not session:
        raise SystemExit("không lấy được mcp-session-id")
    return session


def call_tool(endpoint, key, session, name, arguments):
    reply = curl(endpoint, key, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, session)
    if reply is None:
        return {"error": "không có phản hồi"}
    if "error" in reply:
        return {"error": reply["error"]}
    result = reply["result"]
    if result.get("isError"):
        return {"error": " ".join(b.get("text", "") for b in result.get("content", []))}
    structured = result.get("structuredContent")
    if structured is None:
        blocks = [b["text"] for b in result.get("content", []) if b.get("text")]
        structured = json.loads(blocks[0]) if len(blocks) == 1 else {"raw": blocks}
    return structured


def outline(value, indent=0, max_rows=2):
    """In cấu trúc dữ liệu gọn: key + kiểu + giá trị mẫu."""
    pad = "  " * indent
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                size = f"[{len(v)}]" if isinstance(v, list) else ""
                print(f"{pad}{k}{size}:")
                outline(v, indent + 1, max_rows)
            else:
                print(f"{pad}{k}: {json.dumps(v, ensure_ascii=False)}")
    elif isinstance(value, list):
        for row in value[:max_rows]:
            outline(row, indent, max_rows)
            if len(value) > 1:
                print(f"{pad}--")
        if len(value) > max_rows:
            print(f"{pad}... còn {len(value) - max_rows} phần tử")
    else:
        print(f"{pad}{json.dumps(value, ensure_ascii=False)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Khảo sát MCP gateway")
    ap.add_argument("case_id")
    ap.add_argument("--tool", action="append", help="chỉ gọi tool này (lặp lại được)")
    ap.add_argument("--raw", action="store_true", help="in JSON đầy đủ thay vì outline")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    endpoint = os.environ["MCP_ENDPOINT"].strip()
    key = os.environ["COMPETITION_TEAM_API_KEY"].strip()

    case = json.loads((ROOT / "inputs" / f"{args.case_id}.json").read_text(encoding="utf-8"))
    order_id = case["customer_request"]["claimed_order_id"]
    policy_version = case["policy_version"]

    session = open_session(endpoint, key)
    print(f"case={args.case_id} order={order_id} policy={policy_version}\n")
    try:
        _probe(endpoint, key, session, args, order_id, policy_version)
    finally:
        close_session(endpoint, key, session)


def _probe(endpoint, key, session, args, order_id, policy_version) -> None:
    wanted = args.tool or [*ORDER_TOOLS, "get_policy"]
    for tool in wanted:
        if tool == "get_policy":
            arguments = {"case_id": args.case_id, "policy_version": policy_version}
        elif tool == "get_customer_history":
            print(f"--- {tool}: bỏ qua, cần customer_unique_id ---\n")
            continue
        else:
            arguments = {"case_id": args.case_id, "order_id": order_id}

        print(f"{'=' * 70}\n{tool}\n{'=' * 70}")
        payload = call_tool(endpoint, key, session, tool, arguments)
        if "error" in payload:
            print(f"  LỖI: {payload['error']}\n")
            continue
        print(f"  evidence_ref: {payload.get('evidence_ref')}")
        print(f"  domain      : {payload.get('domain')}")
        if payload.get("warnings"):
            print(f"  warnings    : {payload['warnings']}")
        print("  data:")
        if args.raw:
            print(json.dumps(payload.get("data"), ensure_ascii=False, indent=4))
        else:
            outline(payload.get("data"), indent=2)
        print()


if __name__ == "__main__":
    sys.exit(main())
