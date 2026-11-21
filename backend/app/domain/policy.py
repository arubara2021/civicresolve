"""The closure policy engine. Deterministic, total, and model-free.

This is the only place in the system that decides whether an evidence chain is
sufficient. It performs no I/O and calls no model, so the same report always yields
the same decision. That property is what makes a forensic verdict defensible in a
hearing: an officer cannot appeal to model nondeterminism.

Blocking reasons are ordered by severity so the first reason reported is the most
serious finding, which is what the interface surfaces first.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EvidenceRequirement, LinkName, LinkVerdict
from app.domain.schemas import ChainDecision, LinkResult

# Provenance is advisory. A missing C2PA manifest or stripped metadata is common on
# honest uploads, so it may be inconclusive without blocking. Every other link is
# required, and a required link must be an explicit PASS.
DEFAULT_REQUIRED_LINKS: frozenset[LinkName] = frozenset(
    {
        LinkName.TEMPORAL,
        LinkName.GEOSPATIAL,
        LinkName.VISUAL_SUFFICIENCY,
        LinkName.CLAIM_EVIDENCE,
        LinkName.DUPLICATION,
    }
)


class PolicyParameters(BaseModel):
    """Tunables supplied by the service layer from configuration."""

    model_config = ConfigDict(frozen=True)

    required_links: frozenset[LinkName] = DEFAULT_REQUIRED_LINKS
    max_inconclusive: int = Field(default=1, ge=0, le=6)


def evaluate_chain(
    links: Iterable[LinkResult],
    *,
    reuse_detected: bool,
    missing_evidence: Iterable[EvidenceRequirement] = (),
    parameters: PolicyParameters | None = None,
) -> ChainDecision:
    """Decide whether the submitted chain meets the standard fixed at intake.

    A reused photograph short-circuits immediately: no combination of other passes
    can redeem evidence that was already used to declare a different repair done.
    """
    params = parameters or PolicyParameters()
    results = {result.link: result for result in links}
    missing_requirements = list(missing_evidence)

    failed = sorted(
        (name for name, result in results.items() if result.verdict is LinkVerdict.FAIL),
        key=lambda item: item.value,
    )
    deficient = sorted(
        (name for name, result in results.items() if result.verdict is LinkVerdict.DEFICIENT),
        key=lambda item: item.value,
    )
    inconclusive = sorted(
        (name for name, result in results.items() if result.verdict is LinkVerdict.INCONCLUSIVE),
        key=lambda item: item.value,
    )

    reasons: list[str] = []

    if reuse_detected:
        reasons.append("reused_photograph")

    if missing_requirements:
        reasons.append(
            "missing_mandatory_evidence:"
            + ",".join(sorted(requirement.value for requirement in missing_requirements))
        )

    absent_required = sorted(
        (name for name in params.required_links if name not in results),
        key=lambda item: item.value,
    )
    if absent_required:
        reasons.append("required_links_absent:" + ",".join(name.value for name in absent_required))

    required_failures = [name for name in failed if name in params.required_links]
    if required_failures:
        reasons.append("required_links_failed:" + ",".join(n.value for n in required_failures))

    required_deficient = [name for name in deficient if name in params.required_links]
    if required_deficient:
        reasons.append("required_links_deficient:" + ",".join(n.value for n in required_deficient))

    required_inconclusive = [name for name in inconclusive if name in params.required_links]
    if required_inconclusive:
        reasons.append(
            "required_links_inconclusive:" + ",".join(n.value for n in required_inconclusive)
        )

    if len(inconclusive) > params.max_inconclusive:
        reasons.append(f"too_many_inconclusive_links:{len(inconclusive)}>{params.max_inconclusive}")

    return ChainDecision(
        sufficient=not reasons,
        blocking_reasons=reasons,
        failed_links=failed,
        deficient_links=deficient,
        inconclusive_links=inconclusive,
    )
