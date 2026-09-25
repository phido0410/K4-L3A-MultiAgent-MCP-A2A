"""Bảo vệ repo khỏi việc commit nhầm payload cuộc thi hoặc API key.

Bản gốc assert `inputs/` phải rỗng trên đĩa, nên luôn FAIL sau khi học viên
giải nén input. Bất biến thật sự cần giữ không phải là "không có file trên đĩa"
mà là "file không được git theo dõi" — đó mới là thứ chặn rò rỉ khi push.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tracked_files() -> set[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("không chạy được git trong môi trường này")
    return set(result.stdout.split())


def test_competition_payload_is_not_tracked_by_git() -> None:
    tracked = tracked_files()
    assert "case-set.json" not in tracked
    assert not [name for name in tracked if name.startswith("inputs/") and name.endswith(".json")]
    assert not [name for name in tracked if name.startswith("outputs/") and name.endswith(".json")]
    assert not [name for name in tracked if name.startswith("traces/") and name.endswith(".jsonl")]


def test_no_private_scoring_material_in_repository() -> None:
    forbidden = {"oracles", "reference-outputs", "private-partitions.json", "mcp-access.json"}
    assert not any(path.name in forbidden for path in ROOT.rglob("*"))


def test_environment_files_carry_no_real_key() -> None:
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "sk-team-replace_me" in content
    assert content.count("sk-team-") == 1
    assert ".env" not in tracked_files()
