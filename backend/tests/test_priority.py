"""Priority assertions anchored to the worked example.

These numbers are the product claim: the same report scores 54.9 without the asset
passport and 79.9 with it, and escalates from P2 to P1. If a refactor changes them,
the demo narrative is no longer true, so the test must fail.
"""

from __future__ import annotations

import pytest

from app.domain.enums import Urgency
from app.domain.priority import (
    EscalationRules,
    PriorityWeights,
    RiskCoefficients,
    compute_priority,
    history_risk,
)
from app.domain.schemas import AssetHistorySnapshot

CHRONIC_ASSET = AssetHistorySnapshot(
    asset_id="AST-0042",
    prior_complaints=6,
    prior_closures=6,
    reopen_count=5,
    failed_closure_attempts=1,
    open_age_days=0.0,
)

NEW_ASSET = AssetHistorySnapshot(asset_id="AST-9999")


def test_chronic_asset_reproduces_the_worked_example() -> None:
    result = compute_priority(Urgency.P2, 78, CHRONIC_ASSET)

    assert result.history_risk == 100.0
    assert result.score == 79.9
    assert result.assessed_urgency is Urgency.P2
    assert result.final_urgency is Urgency.P1
    assert result.escalated is True


def test_without_history_the_same_report_scores_lower() -> None:
    result = compute_priority(Urgency.P2, 78, NEW_ASSET)

    assert result.history_risk == 0.0
    assert result.score == 54.9
    assert result.final_urgency is Urgency.P2
    assert result.escalated is False


def test_passport_delta_is_the_differentiator() -> None:
    with_history = compute_priority(Urgency.P2, 78, CHRONIC_ASSET).score
    without_history = compute_priority(Urgency.P2, 78, NEW_ASSET).score

    assert round(with_history - without_history, 1) == 25.0


def test_history_risk_is_capped() -> None:
    extreme = AssetHistorySnapshot(asset_id="AST-0001", reopen_count=50, failed_closure_attempts=50)
    assert history_risk(extreme) == 100.0


def test_reopen_weighs_more_than_a_failed_attempt() -> None:
    reopens = AssetHistorySnapshot(asset_id="AST-0001", reopen_count=1)
    failures = AssetHistorySnapshot(asset_id="AST-0001", failed_closure_attempts=1)

    assert history_risk(reopens) > history_risk(failures)


def test_open_age_contributes_linearly() -> None:
    aged = AssetHistorySnapshot(asset_id="AST-0001", open_age_days=10)
    assert history_risk(aged) == 20.0


def test_escalation_saturates_at_p1() -> None:
    result = compute_priority(Urgency.P1, 90, CHRONIC_ASSET)

    assert result.final_urgency is Urgency.P1
    assert result.escalated is True


def test_failed_closures_alone_can_trigger_escalation() -> None:
    snapshot = AssetHistorySnapshot(asset_id="AST-0001", failed_closure_attempts=3)
    result = compute_priority(Urgency.P3, 20, snapshot)

    assert result.final_urgency is Urgency.P2
    assert any("failed_closure_attempts" in reason for reason in result.reasons)


def test_thresholds_are_configurable() -> None:
    snapshot = AssetHistorySnapshot(asset_id="AST-0001", reopen_count=2)
    strict = EscalationRules(reopen_threshold=5, failed_closure_threshold=5)
    result = compute_priority(Urgency.P3, 20, snapshot, escalation=strict)

    assert result.escalated is False
    assert result.final_urgency is Urgency.P3


def test_custom_coefficients_are_honoured() -> None:
    coefficients = RiskCoefficients(failed_closure=0.0, reopen=10.0, open_age_day=0.0)
    snapshot = AssetHistorySnapshot(asset_id="AST-0001", reopen_count=3)

    assert history_risk(snapshot, coefficients) == 30.0


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        PriorityWeights(urgency=0.5, impact=0.5, history=0.5)


def test_impact_score_is_range_checked() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        compute_priority(Urgency.P2, 101, NEW_ASSET)


def test_breakdown_records_the_weights_used() -> None:
    result = compute_priority(Urgency.P2, 78, CHRONIC_ASSET)

    assert result.weights == {"urgency": 0.45, "impact": 0.30, "history": 0.25}
