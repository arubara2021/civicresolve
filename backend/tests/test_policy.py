"""Policy assertions covering every blocking branch.

Act 3 is the suspicious closure from the worked example; Act 5 is the honest one.
Both are reproduced from explicit link results so the test documents exactly which
finding causes the block.
"""

from __future__ import annotations

from app.domain.enums import EvidenceRequirement, LinkName, LinkVerdict
from app.domain.policy import DEFAULT_REQUIRED_LINKS, PolicyParameters, evaluate_chain
from app.domain.schemas import LinkResult


def _link(name: LinkName, verdict: LinkVerdict, reason: str = "test") -> LinkResult:
    return LinkResult(link=name, verdict=verdict, reason=reason)


def _all_pass() -> list[LinkResult]:
    return [_link(name, LinkVerdict.PASS) for name in LinkName]


def act_three_links() -> list[LinkResult]:
    """Wide-angle reused photo, 47-minute turnaround, stripped metadata, copied text."""
    return [
        _link(LinkName.TEMPORAL, LinkVerdict.FAIL, "47 min < 120 min floor"),
        _link(LinkName.GEOSPATIAL, LinkVerdict.DEFICIENT, "EXIF GPS absent"),
        _link(LinkName.VISUAL_SUFFICIENCY, LinkVerdict.FAIL, "wide street view"),
        _link(LinkName.CLAIM_EVIDENCE, LinkVerdict.FAIL, "no patch visible"),
        _link(LinkName.PROVENANCE, LinkVerdict.INCONCLUSIVE, "metadata stripped"),
        _link(LinkName.DUPLICATION, LinkVerdict.FAIL, "identical remarks on 6 tickets"),
    ]


def test_act_three_is_blocked() -> None:
    decision = evaluate_chain(act_three_links(), reuse_detected=True)

    assert decision.sufficient is False
    assert decision.blocking_reasons[0] == "reused_photograph"
    assert LinkName.TEMPORAL in decision.failed_links
    assert LinkName.GEOSPATIAL in decision.deficient_links
    assert LinkName.PROVENANCE in decision.inconclusive_links


def test_act_five_passes() -> None:
    decision = evaluate_chain(_all_pass(), reuse_detected=False)

    assert decision.sufficient is True
    assert decision.blocking_reasons == []


def test_reuse_alone_blocks_an_otherwise_perfect_chain() -> None:
    decision = evaluate_chain(_all_pass(), reuse_detected=True)

    assert decision.sufficient is False
    assert decision.blocking_reasons == ["reused_photograph"]


def test_missing_mandatory_evidence_blocks() -> None:
    decision = evaluate_chain(
        _all_pass(),
        reuse_detected=False,
        missing_evidence=[EvidenceRequirement.WORK_ORDER_REFERENCE],
    )

    assert decision.sufficient is False
    assert any("missing_mandatory_evidence" in reason for reason in decision.blocking_reasons)


def test_absent_required_link_blocks() -> None:
    partial = [result for result in _all_pass() if result.link is not LinkName.TEMPORAL]
    decision = evaluate_chain(partial, reuse_detected=False)

    assert decision.sufficient is False
    assert any("required_links_absent:temporal" in r for r in decision.blocking_reasons)


def test_single_required_failure_blocks() -> None:
    links = [
        _link(name, LinkVerdict.FAIL if name is LinkName.CLAIM_EVIDENCE else LinkVerdict.PASS)
        for name in LinkName
    ]
    decision = evaluate_chain(links, reuse_detected=False)

    assert decision.sufficient is False
    assert any("required_links_failed:claim_evidence" in r for r in decision.blocking_reasons)


def test_deficient_required_link_blocks() -> None:
    links = [
        _link(
            name,
            LinkVerdict.DEFICIENT if name is LinkName.GEOSPATIAL else LinkVerdict.PASS,
        )
        for name in LinkName
    ]
    decision = evaluate_chain(links, reuse_detected=False)

    assert decision.sufficient is False
    assert any("required_links_deficient:geospatial" in r for r in decision.blocking_reasons)


def test_inconclusive_required_link_blocks() -> None:
    links = [
        _link(
            name,
            LinkVerdict.INCONCLUSIVE if name is LinkName.CLAIM_EVIDENCE else LinkVerdict.PASS,
        )
        for name in LinkName
    ]
    decision = evaluate_chain(links, reuse_detected=False)

    assert decision.sufficient is False
    assert any("required_links_inconclusive" in r for r in decision.blocking_reasons)


def test_one_advisory_inconclusive_is_tolerated() -> None:
    links = [
        _link(
            name,
            LinkVerdict.INCONCLUSIVE if name is LinkName.PROVENANCE else LinkVerdict.PASS,
        )
        for name in LinkName
    ]
    decision = evaluate_chain(links, reuse_detected=False)

    assert decision.sufficient is True


def test_excess_inconclusive_links_block() -> None:
    links = [
        _link(
            name,
            LinkVerdict.INCONCLUSIVE
            if name in {LinkName.PROVENANCE, LinkName.DUPLICATION}
            else LinkVerdict.PASS,
        )
        for name in LinkName
    ]
    decision = evaluate_chain(links, reuse_detected=False)

    assert decision.sufficient is False
    assert any("too_many_inconclusive_links" in r for r in decision.blocking_reasons)


def test_stricter_parameters_are_honoured() -> None:
    links = [
        _link(
            name,
            LinkVerdict.INCONCLUSIVE if name is LinkName.PROVENANCE else LinkVerdict.PASS,
        )
        for name in LinkName
    ]
    strict = PolicyParameters(max_inconclusive=0)
    decision = evaluate_chain(links, reuse_detected=False, parameters=strict)

    assert decision.sufficient is False


def test_provenance_is_not_required_by_default() -> None:
    assert LinkName.PROVENANCE not in DEFAULT_REQUIRED_LINKS
    assert len(DEFAULT_REQUIRED_LINKS) == 5


def test_decision_is_deterministic() -> None:
    links = act_three_links()
    first = evaluate_chain(links, reuse_detected=True)
    second = evaluate_chain(links, reuse_detected=True)

    assert first == second


def test_empty_chain_is_blocked() -> None:
    decision = evaluate_chain([], reuse_detected=False)

    assert decision.sufficient is False
    assert any("required_links_absent" in reason for reason in decision.blocking_reasons)
