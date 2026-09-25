"""Shared specialist result types.

Owner: Phi. Placeholder written from the task-assignment spec (section 4.2) so specialist
agents can be built in parallel; replace with the owner's version when it lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceItem:
    evidence_ref: str
    domain: str
    tool_name: str


@dataclass
class Finding:
    actor: str
    signals: list[str]
    entities: dict[str, list[str]] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
