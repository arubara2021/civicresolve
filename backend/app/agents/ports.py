"""Agent contracts. Every runtime — direct, ADK, LangGraph — implements these.

The two inputs are plain dataclasses rather than Pydantic models, because they are
constructed inside the application and never cross a trust boundary. The outputs
are the Pydantic schemas from app.domain.schemas so that structured-output binding
is a single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.schemas import AssetHistorySnapshot, AuditorResult, GeoPoint, TriageResult


@dataclass(frozen=True, slots=True)
class TriageInput:
    """Everything the intake classifier needs from the complaint."""

    title: str
    description: str
    location: GeoPoint
    category_hint: str | None = None
    reporter_summary: str | None = None
    ward: str = "WARD-DEMO"
    image_bytes: bytes | None = None
    image_mime: str | None = None


@dataclass(frozen=True, slots=True)
class AuditorInput:
    """Everything the closure auditor needs from one closure attempt."""

    defect_claim: str
    closure_remarks: str
    evidence_required: list[str] = field(default_factory=list)
    work_order_reference: str | None = None
    before_image_bytes: bytes | None = None
    before_image_mime: str | None = None
    after_image_bytes: bytes | None = None
    after_image_mime: str | None = None
    asset_snapshot: AssetHistorySnapshot | None = None
    ward: str = "WARD-DEMO"


@dataclass(frozen=True, slots=True)
class AgentCallRecord:
    """Observable metadata about the underlying model invocation.

    Carried alongside the Pydantic result so the caller can log cost, latency and
    fallback without having to re-read configuration.
    """

    model_used: str
    latency_s: float
    fallback_used: bool
    attempts: int
    degraded: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TriageOutcome:
    """Triage result plus invocation metadata."""

    result: TriageResult
    call: AgentCallRecord


@dataclass(frozen=True, slots=True)
class AuditorOutcome:
    """Auditor result plus invocation metadata.

    degraded is set when the model call failed and the agent produced a safe
    default — every visual link INCONCLUSIVE, no claims assessed. The policy
    engine and the service layer decide what to do with a degraded outcome; the
    agent never silently passes a chain it could not assess.
    """

    result: AuditorResult
    call: AgentCallRecord


@runtime_checkable
class TriageAgent(Protocol):
    """Contract for intake classification.

    Implementations may call one model, orchestrate several, or delegate to ADK
    or LangGraph. They must return a TriageOutcome whose result conforms to the
    TriageResult schema.
    """

    async def triage(self, inputs: TriageInput) -> TriageOutcome: ...


@runtime_checkable
class AuditorAgent(Protocol):
    """Contract for closure forensics.

    Implementations must never produce a result that claims closure is sufficient.
    When the model cannot assess, the result must report INCONCLUSIVE verdicts and
    the call record must set degraded=True.
    """

    async def audit(self, inputs: AuditorInput) -> AuditorOutcome: ...
