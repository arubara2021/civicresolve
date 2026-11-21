"""Priority composition. Pure arithmetic, no configuration import, no I/O.

The score answers "how bad is this report". The urgency band answers "how fast must
we route it". They are computed separately on purpose: the score reflects the
assessed urgency, while band escalation is an operational decision driven by the
asset's failure history. Both are recorded so the ranking is fully explainable.

Coefficients are passed in as frozen parameter objects rather than read from
settings, which keeps this module importable and testable in complete isolation.
The service layer constructs the parameters from configuration.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import Urgency, escalate_urgency, urgency_weight
from app.domain.schemas import AssetHistorySnapshot, PriorityBreakdown


class PriorityWeights(BaseModel):
    """Relative contribution of each priority component. Must sum to one."""

    model_config = ConfigDict(frozen=True)

    urgency: float = Field(default=0.45, ge=0.0, le=1.0)
    impact: float = Field(default=0.30, ge=0.0, le=1.0)
    history: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_sum(self) -> PriorityWeights:
        total = self.urgency + self.impact + self.history
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"priority weights must sum to 1.0; got {total:.6f}")
        return self

    def as_dict(self) -> dict[str, float]:
        return {"urgency": self.urgency, "impact": self.impact, "history": self.history}


class RiskCoefficients(BaseModel):
    """How strongly each history signal contributes to asset risk.

    A reopen weighs more than a failed closure attempt because a reopen is proof
    that a previously declared resolution did not hold on the ground.
    """

    model_config = ConfigDict(frozen=True)

    failed_closure: float = Field(default=15.0, ge=0.0)
    reopen: float = Field(default=20.0, ge=0.0)
    open_age_day: float = Field(default=2.0, ge=0.0)
    cap: float = Field(default=100.0, gt=0.0)


class EscalationRules(BaseModel):
    """History thresholds that force a one-band urgency escalation."""

    model_config = ConfigDict(frozen=True)

    reopen_threshold: int = Field(default=2, ge=1)
    failed_closure_threshold: int = Field(default=3, ge=1)


def history_risk(
    snapshot: AssetHistorySnapshot,
    coefficients: RiskCoefficients | None = None,
) -> float:
    """Compute capped asset risk from the failure history.

    A brand-new asset scores zero, which is what makes the passport-derived
    component visible as a delta rather than a constant offset.
    """
    rules = coefficients or RiskCoefficients()
    raw = (
        rules.failed_closure * snapshot.failed_closure_attempts
        + rules.reopen * snapshot.reopen_count
        + rules.open_age_day * snapshot.open_age_days
    )
    return round(min(rules.cap, raw), 2)


def compute_priority(
    urgency: Urgency,
    impact_score: int,
    snapshot: AssetHistorySnapshot,
    *,
    weights: PriorityWeights | None = None,
    coefficients: RiskCoefficients | None = None,
    escalation: EscalationRules | None = None,
) -> PriorityBreakdown:
    """Compose the queue score and decide whether to escalate the urgency band.

    The score is computed from the assessed urgency and is not recomputed after
    escalation. Escalation changes routing priority, not the assessment of the
    report itself, and both values are retained for audit.
    """
    if not 0 <= impact_score <= 100:
        raise ValueError("impact_score must lie between 0 and 100")

    active_weights = weights or PriorityWeights()
    active_rules = escalation or EscalationRules()

    weight = urgency_weight(urgency)
    risk = history_risk(snapshot, coefficients)
    score = round(
        active_weights.urgency * weight
        + active_weights.impact * impact_score
        + active_weights.history * risk,
        1,
    )

    reasons: list[str] = []
    if snapshot.reopen_count >= active_rules.reopen_threshold:
        reasons.append(f"reopen_count {snapshot.reopen_count} >= {active_rules.reopen_threshold}")
    if snapshot.failed_closure_attempts >= active_rules.failed_closure_threshold:
        reasons.append(
            f"failed_closure_attempts {snapshot.failed_closure_attempts} "
            f">= {active_rules.failed_closure_threshold}"
        )

    escalated = bool(reasons)
    final_urgency = escalate_urgency(urgency) if escalated else urgency

    return PriorityBreakdown(
        assessed_urgency=urgency,
        final_urgency=final_urgency,
        urgency_weight=weight,
        impact_score=impact_score,
        history_risk=risk,
        score=score,
        escalated=escalated,
        reasons=reasons,
        weights=active_weights.as_dict(),
    )
