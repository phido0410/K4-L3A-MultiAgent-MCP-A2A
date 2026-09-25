from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import OUTPUT_SCHEMA_VERSION, VARIANT_ID
from .cases import CaseSet
from .contracts import Contracts

SECRET_PATTERN = re.compile(r"sk-team-[A-Za-z0-9_-]{8,}")
MAX_FILE_BYTES = 1024 * 1024
MAX_SUBMISSION_BYTES = 12 * 1024 * 1024


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def build_manifest(case_set: CaseSet) -> dict[str, Any]:
    return {
        "schema_version": "day09-submission-manifest-v2",
        "competition_id": "day09-multiagent-mcp-a2a",
        "variant_id": VARIANT_ID,
        "case_set_version": case_set.version,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "trace_schema_version": "day09-trace-event-v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "client": {"name": "day09-student-starter", "version": "0.1.0"},
    }


def validate_artifacts(
    root: Path, case_set: CaseSet, contracts: Contracts
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    outputs_root = root / "outputs"
    actual = {path.stem: path for path in outputs_root.glob("*.json") if path.is_file()}
    expected = set(case_set.case_ids)
    if set(actual) != expected:
        missing = sorted(expected - set(actual))
        extra = sorted(set(actual) - expected)
        raise ValueError(f"outputs do not match case-set; missing={missing}, extra={extra}")

    outputs: dict[str, dict[str, Any]] = {}
    for case_id in case_set.case_ids:
        output = _json_object(actual[case_id])
        contracts.validate_output(output, f"outputs/{case_id}.json")
        if output.get("case_id") != case_id:
            raise ValueError(f"outputs/{case_id}.json has a mismatched case_id")
        outputs[case_id] = output

    trace_path = root / "traces" / "trace.jsonl"
    try:
        trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("traces/trace.jsonl is missing or not UTF-8") from exc
    normalized_lines: list[str] = []
    seen_events: set[str] = set()
    for number, line in enumerate(trace_lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"traces/trace.jsonl:{number}: invalid JSON") from exc
        contracts.validate_trace(event, f"traces/trace.jsonl:{number}")
        if event["case_id"] not in expected:
            raise ValueError(f"traces/trace.jsonl:{number}: case is outside this case-set")
        if event["event_id"] in seen_events:
            raise ValueError(f"traces/trace.jsonl:{number}: duplicate event_id")
        seen_events.add(event["event_id"])
        normalized_lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))

    serialized = [json.dumps(value, ensure_ascii=False) for value in outputs.values()]
    if SECRET_PATTERN.search("\n".join([*serialized, *normalized_lines])):
        raise ValueError("a Team API Key appears in output or trace")
    return outputs, normalized_lines


#: Tỉ lệ case được phép không có evidence trước khi coi là hỏng kết nối.
MAX_EMPTY_EVIDENCE_RATIO = 0.15

#: Tỉ lệ case được phép dùng chung một luồng trace y hệt nhau.
#: Một điều tra thật sinh ra luồng khác nhau theo từng case; nhiều case trùng
#: luồng tuyệt đối là dấu hiệu agent chạy rỗng, và server gắn cờ spam.
MAX_IDENTICAL_TRACE_RATIO = 0.40


def _skip_health_checks() -> bool:
    return os.getenv("DAY09_SKIP_HEALTH_CHECKS", "").strip() == "1" or (
        os.getenv("DAY09_ALLOW_EMPTY_EVIDENCE", "").strip() == "1"
    )


def check_trace_health(trace_lines: list[str]) -> None:
    """Chặn đóng gói khi quá nhiều case có luồng trace giống hệt nhau.

    Bỏ `event_id` và `occurred_at` rồi so chữ ký luồng của từng case. Khi MCP
    chết, mọi case chạy đúng một kịch bản rỗng giống nhau; server coi đó là
    trace lặp/spam và cho 0 điểm cả bài.
    """
    if _skip_health_checks():
        return
    shapes: dict[str, list[tuple[Any, ...]]] = {}
    for line in trace_lines:
        event = json.loads(line)
        shapes.setdefault(event["case_id"], []).append(
            (
                event["event_type"],
                event["actor"],
                event.get("target"),
                event.get("decision_code"),
                len(event.get("evidence_refs") or []),
            )
        )
    if not shapes:
        return
    counts: dict[tuple[Any, ...], int] = {}
    for flow in shapes.values():
        key = tuple(flow)
        counts[key] = counts.get(key, 0) + 1
    worst = max(counts.values())
    ratio = worst / len(shapes)
    if ratio <= MAX_IDENTICAL_TRACE_RATIO:
        return
    raise ValueError(
        f"{worst}/{len(shapes)} case có luồng trace giống hệt nhau ({ratio:.0%}), "
        f"chỉ {len(counts)} luồng khác nhau cho toàn bộ case. "
        f"Server coi đây là trace lặp/spam và cho 0 điểm cả bài nộp.\n"
        f"Nguyên nhân thường gặp: kết nối MCP chết nên mọi case chạy cùng một "
        f"kịch bản rỗng. Chạy lại day09 run và kiểm tra evidence trước khi nộp."
    )


def check_evidence_health(outputs: dict[str, Any]) -> None:
    """Chặn đóng gói khi phần lớn case không có evidence.

    Agent nuốt lỗi MCP (`except Exception`) nên hỏng kết nối giữa chừng không
    hiện ra ở đâu cả: output vẫn đủ 100 file, vẫn hợp schema, `day09 validate`
    vẫn pass. Nhưng case không có evidence sẽ dính hard gate
    `missing_required_evidence` và cả bài nộp về 0 điểm.

    Đây là cửa cuối trước khi tạo ZIP. Đặt DAY09_ALLOW_EMPTY_EVIDENCE=1 để bỏ
    qua nếu thật sự có ý định nộp như vậy.
    """
    if _skip_health_checks():
        return
    empty = [case_id for case_id, out in outputs.items() if not out.get("evidence_refs")]
    ratio = len(empty) / max(len(outputs), 1)
    if ratio <= MAX_EMPTY_EVIDENCE_RATIO:
        return
    raise ValueError(
        f"{len(empty)}/{len(outputs)} case không có evidence_ref nào "
        f"({ratio:.0%}). Gần như chắc chắn kết nối MCP đã chết giữa chừng — "
        f"nộp bản này sẽ bị hard gate missing_required_evidence và ăn 0 điểm.\n"
        f"Case rỗng đầu tiên: {empty[:5]}\n"
        f"Kiểm tra: pip install -e \".[dev]\" rồi chạy lại day09 run."
    )


def package_submission(root: Path, destination: Path) -> Path:
    from .cases import load_case_set

    root = root.resolve()
    case_set = load_case_set(root)
    contracts = Contracts(root / "contracts" / "schemas")
    outputs, trace_lines = validate_artifacts(root, case_set, contracts)
    check_evidence_health(outputs)
    check_trace_health(trace_lines)
    manifest = build_manifest(case_set)
    contracts.validate_manifest(manifest)

    payloads = {
        "manifest.json": json.dumps(manifest, separators=(",", ":")).encode(),
        "trace.jsonl": ("\n".join(trace_lines) + ("\n" if trace_lines else "")).encode(),
        **{
            f"outputs/{case_id}.json": json.dumps(
                outputs[case_id], ensure_ascii=False, separators=(",", ":")
            ).encode()
            for case_id in case_set.case_ids
        },
    }
    oversized = [name for name, payload in payloads.items() if len(payload) > MAX_FILE_BYTES]
    if oversized:
        raise ValueError(f"submission files exceed 1 MB: {oversized}")
    if sum(map(len, payloads.values())) > MAX_SUBMISSION_BYTES:
        raise ValueError("submission exceeds the 12 MB uncompressed limit")

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    return destination
