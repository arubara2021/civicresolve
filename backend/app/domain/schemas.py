"""Typed contracts for model output, internal value objects, and API payloads.

Three groups with different trust assumptions:

Model output contracts are bound directly to the Gemini response schema. They use
only JSON-schema-friendly types and ignore unknown keys, because a provider may
additively extend a response.

Internal value objects are frozen. They are produced by pure functions and passed
between layers without mutation, which is what makes the audit reproducible.

API input contracts forbid unknown keys so a client typo surfaces as a validation
error rather than a silently dropped field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    Action,
    ActorType,
    Category,
    ClaimVerdict,
    DecisionType,
    DeficiencyCode,
    Department,
    EventType,
    EvidenceKind,
    EvidenceRequirement,
    Framing,
    ImpactLevel,
    LinkName,
    LinkVerdict,
    Status,
    SubStatus,
    Urgency,
)

# Group 1. Model output contracts. Every field is required so the model cannot
# omit a component of the audit and have it default to something permissive.


class PublicImpact(BaseModel):
    """Assessed exposure of the public to the reported defect."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    score: int = Field(ge=0, le=100, description="0-100 public impact score")
    factors: list[str] = Field(description="Concrete drivers, e.g. school_within_100m")
    affected_population: ImpactLevel


class DepartmentRecommendation(BaseModel):
    """Routing recommendation with explicit uncertainty."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    primary: Department
    confidence: float = Field(ge=0.0, le=1.0)
    alternates: list[Department] = Field(default_factory=list)


class TriageResult(BaseModel):
    """Intake output.

    defect_claim and evidence_required_for_closure are the evidentiary standard.
    They are persisted to the asset at report time, before the repairing party is
    known, so the closure bar cannot be lowered later by the party being audited.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    category: Category
    category_confidence: float = Field(ge=0.0, le=1.0)
    urgency: Urgency
    urgency_reason: str = Field(min_length=3)
    public_impact: PublicImpact
    department: DepartmentRecommendation
    defect_claim: str = Field(min_length=5, description="Physical condition to be eliminated")
    evidence_required_for_closure: list[EvidenceRequirement] = Field(min_length=1)
    min_repair_minutes: int = Field(ge=1, description="Clamped by the service, never trusted raw")
    citizen_summary: str = Field(min_length=5)
    safety_flags: list[str] = Field(default_factory=list)


class VisualSufficiency(BaseModel):
    """Whether the frame is capable of evidencing the repair at all."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    verdict: LinkVerdict
    framing: Framing
    defect_zone_visible: bool
    reason: str = Field(min_length=5, description="Must reference what is visible in the frame")


class ClaimAssessment(BaseModel):
    """One physical claim from the closure text, checked against the image."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    claim: str = Field(min_length=3)
    verdict: ClaimVerdict
    observation: str = Field(min_length=3)


class AuditorResult(BaseModel):
    """Visual audit output covering links three and four only.

    No overall claim verdict is requested. The forensics layer derives it from the
    per-claim assessments by taking the most severe result, which removes a
    consistency failure mode where a model summarises optimistically.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    visual_sufficiency: VisualSufficiency
    claim_assessments: list[ClaimAssessment] = Field(min_length=1)
    observed_condition: str = Field(min_length=3)
    additional_deficiencies: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


# Group 2. Frozen internal value objects.


class GeoPoint(BaseModel):
    """WGS84 coordinate pair."""

    model_config = ConfigDict(frozen=True)

    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)


class AssetHistorySnapshot(BaseModel):
    """Everything priority needs to know about an asset's failure history."""

    model_config = ConfigDict(frozen=True)

    asset_id: str
    prior_complaints: int = Field(default=0, ge=0)
    prior_closures: int = Field(default=0, ge=0)
    reopen_count: int = Field(default=0, ge=0)
    failed_closure_attempts: int = Field(default=0, ge=0)
    open_age_days: float = Field(default=0.0, ge=0.0)
    days_since_verified_repair: float | None = None


class PriorityBreakdown(BaseModel):
    """Fully explained priority decision, suitable for display and for audit."""

    model_config = ConfigDict(frozen=True)

    assessed_urgency: Urgency
    final_urgency: Urgency
    urgency_weight: int
    impact_score: int
    history_risk: float
    score: float
    escalated: bool
    reasons: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)


class ReuseMatch(BaseModel):
    """A near-duplicate image found in the asset or ward corpus."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    complaint_id: str | None = None
    asset_id: str | None = None
    hamming_distance: int = Field(ge=0, le=64)


class Deficiency(BaseModel):
    """An actionable, specific remedy. Never a vague rejection."""

    model_config = ConfigDict(frozen=True)

    code: DeficiencyCode
    message: str
    remedy: str
    link: LinkName | None = None


class LinkResult(BaseModel):
    """One audited link. Measurements are explicit fields rather than a free-form
    dictionary, so a report can be diffed and asserted against in tests.
    """

    model_config = ConfigDict(frozen=True)

    link: LinkName
    verdict: LinkVerdict
    reason: str
    measured_value: float | None = None
    threshold: float | None = None
    unit: str | None = None
    matched_ids: list[str] = Field(default_factory=list)
    deficiencies: list[DeficiencyCode] = Field(default_factory=list)


class ChainDecision(BaseModel):
    """Output of the pure policy engine. Contains no model-generated text."""

    model_config = ConfigDict(frozen=True)

    sufficient: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    failed_links: list[LinkName] = Field(default_factory=list)
    deficient_links: list[LinkName] = Field(default_factory=list)
    inconclusive_links: list[LinkName] = Field(default_factory=list)


class ForensicReport(BaseModel):
    """The Closure Forensics Report shown to the citizen.

    chain_sufficient is copied from ChainDecision. It is never authored by a model.
    degraded records that the visual links could not be assessed, which routes the
    attempt to a reviewer rather than allowing it to resolve.
    """

    attempt_id: str
    complaint_id: str
    asset_id: str
    links: list[LinkResult]
    reuse_detected: bool
    reuse_matches: list[ReuseMatch] = Field(default_factory=list)
    missing_evidence: list[EvidenceRequirement] = Field(default_factory=list)
    decision: ChainDecision
    deficiencies: list[Deficiency] = Field(default_factory=list)
    observed_condition: str | None = None
    model_used: str | None = None
    degraded: bool = False
    generated_at: datetime


class PassportEvent(BaseModel):
    """One append-only, hash-chained entry in an asset's permanent record."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    asset_id: str
    seq: int = Field(ge=1)
    event_type: EventType
    actor_type: ActorType
    actor_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    prev_hash: str | None = None
    event_hash: str


# Group 3. API input contracts.


class ComplaintCreate(BaseModel):
    """Citizen report payload. The image is optional and travels as multipart."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=5, max_length=140)
    description: str = Field(min_length=10, max_length=2000)
    location: GeoPoint
    category_hint: Category | None = None
    reporter_id: str = Field(min_length=3, max_length=64)
    ward: str = Field(default="WARD-DEMO", min_length=2, max_length=32)


class ClosureSubmit(BaseModel):
    """Department closure submission. Evidence files are referenced by identifier."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    officer_id: str = Field(min_length=3, max_length=64)
    remarks: str = Field(min_length=10, max_length=1000)
    work_order_reference: str | None = Field(default=None, max_length=64)
    after_evidence_id: str = Field(min_length=3)
    before_evidence_id: str | None = None
    work_completed_at: datetime | None = None

    @field_validator("remarks")
    @classmethod
    def _reject_blank_remarks(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("remarks must describe the work performed")
        return value


class DecisionIn(BaseModel):
    """Citizen acceptance or rejection of a closure attempt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    actor_id: str = Field(min_length=3, max_length=64)
    decision: DecisionType
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _require_rejection_reason(self) -> DecisionIn:
        if self.decision is DecisionType.REJECT and not (
            self.reason and len(self.reason.strip()) >= 5
        ):
            raise ValueError("a rejection must state a reason of at least 5 characters")
        return self


class ReviewDecisionIn(BaseModel):
    """Reviewer adjudication. Justification is mandatory and permanently logged."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reviewer_id: str = Field(min_length=3, max_length=64)
    decision: DecisionType
    justification: str = Field(min_length=20, max_length=2000)


class EvidenceUploadMeta(BaseModel):
    """Server-side description of a stored evidence file."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    kind: EvidenceKind
    content_hash: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    received_at: datetime


class StatusUpdate(BaseModel):
    """Admin status action. The target state is derived by the state machine,
    never supplied by the client, so a caller cannot request an illegal state.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    actor_id: str = Field(min_length=3, max_length=64)
    actor_type: ActorType
    action: Action
    assignee_department: Department | None = None


class ComplaintSummary(BaseModel):
    """Dashboard row. Primary status uses the challenge's exact vocabulary."""

    complaint_id: str
    asset_id: str
    title: str
    category: Category
    status: Status
    sub_status: SubStatus
    sub_status_label: str
    urgency: Urgency
    priority_score: float
    department: Department
    department_label: str
    ward: str
    created_at: datetime
    sla_deadline: datetime | None = None
    reopen_count: int = 0
