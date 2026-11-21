"""Direct Gemini implementations of the agent contracts.

Each agent performs exactly one structured-output call. No tool use and no
iterative reasoning — those belong to the ADK and LangGraph runtimes, which can be
swapped in without changing any other code.

Two invariants are enforced here rather than trusted to the model.

First, the system prompt is always attached via system_instruction. It carries the
auditor's behavioural rules: never guess whether an image is AI-generated, cite a
visible observation for every verdict, and abstain rather than speculate. A
response produced without them is a wiring bug, not a prompt-quality problem.

Second, the auditor's output is re-validated after parsing. A confident claim
verdict with no supporting observation is downgraded to INCONCLUSIVE, because a
wrongly-confident FAIL can falsely accuse an honest officer.

The call record returned by the client is passed through unchanged rather than
rebuilt, so field renames in the client cannot silently desynchronise from here.
"""

from __future__ import annotations

import json
from dataclasses import replace

from google.genai import types

from app.agents.gemini_client import (
    GeminiClient,
    build_config,
    build_image_part,
    build_text_part,
    get_client,
)
from app.agents.ports import (
    AgentCallRecord,
    AuditorInput,
    AuditorOutcome,
    TriageInput,
    TriageOutcome,
)
from app.agents.prompts import (
    AUDITOR_SYSTEM,
    TRIAGE_SYSTEM,
    auditor_schema,
    triage_schema,
)
from app.core.config import Settings, get_settings
from app.core.errors import UpstreamUnavailableError
from app.core.logging import get_logger
from app.domain.enums import ClaimVerdict, Framing, LinkVerdict
from app.domain.schemas import (
    AuditorResult,
    ClaimAssessment,
    TriageResult,
    VisualSufficiency,
)

log = get_logger(__name__)

_TRIAGE_USER_TEMPLATE = """Analyse this civic complaint.

Title: {title}
Description: {description}
Location: latitude {lat}, longitude {lng}
Ward: {ward}
Citizen category hint: {category_hint}
{reporter_block}
{image_block}

Return a single JSON object matching the response schema."""

_AUDITOR_USER_TEMPLATE = """Audit this closure attempt against the intake standard.

Defect claim fixed at intake:
{defect_claim}

Evidence required for closure:
{evidence_required}

Closure remarks submitted by the department:
{remarks}

{work_order_block}

{snapshot_block}

Return a single JSON object matching the response schema."""


def _extract_json(response: types.GenerateContentResponse) -> dict:
    """Parse the model's structured JSON output.

    An empty or non-JSON body is treated as upstream unavailability so the caller
    degrades safely rather than raising an opaque parse error.
    """
    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise UpstreamUnavailableError("Model returned an empty response.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamUnavailableError("Model returned malformed JSON.") from exc
    if not isinstance(parsed, dict):
        raise UpstreamUnavailableError("Model returned a JSON value that is not an object.")
    return parsed


def _clamp_min_repair_minutes(result: TriageResult, settings: Settings) -> TriageResult:
    """Enforce the configured floor and ceiling regardless of model suggestion.

    The model proposes a repair duration; the configuration decides what is
    physically plausible. A model cannot invent a short window that would let a
    same-hour closure pass the temporal link.
    """
    clamped = max(
        settings.min_repair_floor,
        min(settings.min_repair_ceiling, result.min_repair_minutes),
    )
    if clamped == result.min_repair_minutes:
        return result
    log.info(
        "triage.repair_window_clamped",
        suggested=result.min_repair_minutes,
        clamped=clamped,
    )
    return result.model_copy(update={"min_repair_minutes": clamped})


def _format_snapshot(inputs: AuditorInput) -> str:
    """Render the asset snapshot for the prompt, or a placeholder."""
    snapshot = inputs.asset_snapshot
    if snapshot is None:
        return "No asset history is available."
    return (
        f"Asset history: {snapshot.prior_complaints} prior complaints, "
        f"{snapshot.prior_closures} prior closures, "
        f"{snapshot.reopen_count} reopens, "
        f"{snapshot.failed_closure_attempts} prior failed closure attempts."
    )


def _degraded_result(reason: str) -> AuditorResult:
    """Safe default when the model could not be consulted.

    Every visual link is INCONCLUSIVE, no claims are assessed, and no deficiencies
    are invented. The policy engine treats this as degraded and routes the attempt
    to a reviewer rather than silently passing a chain nobody examined.
    """
    return AuditorResult(
        visual_sufficiency=VisualSufficiency(
            verdict=LinkVerdict.INCONCLUSIVE,
            framing=Framing.MID_RANGE,
            defect_zone_visible=False,
            reason=f"Model unavailable: {reason}",
        ),
        claim_assessments=[
            ClaimAssessment(
                claim="unable to assess",
                verdict=ClaimVerdict.INCONCLUSIVE,
                observation="Model unavailable; no visual assessment performed.",
            )
        ],
        observed_condition="no visual assessment performed",
        additional_deficiencies=[],
        confidence=0.0,
    )


def _enforce_invariants(result: AuditorResult) -> AuditorResult:
    """Reject model outputs that violate the audit contract.

    Two rules. A claim verdict with no supporting observation is downgraded to
    INCONCLUSIVE. And when the frame is insufficient to assess repair at all, no
    individual claim may carry a confident verdict — you cannot contradict a claim
    from a photograph that does not show the defect zone.

    Violations are rewritten rather than raised, so one bad model output degrades
    the report instead of failing the request.
    """
    updated: list[ClaimAssessment] = []
    mutated = False

    for claim in result.claim_assessments:
        if not claim.observation or not claim.observation.strip():
            mutated = True
            updated.append(claim.model_copy(update={"verdict": ClaimVerdict.INCONCLUSIVE}))
            continue
        updated.append(claim)

    if result.visual_sufficiency.verdict is LinkVerdict.FAIL and any(
        claim.verdict is not ClaimVerdict.INCONCLUSIVE for claim in updated
    ):
        mutated = True
        updated = [
            claim.model_copy(update={"verdict": ClaimVerdict.INCONCLUSIVE}) for claim in updated
        ]

    if not mutated:
        return result

    log.warning("auditor.invariants_enforced", claims=len(updated))
    return result.model_copy(update={"claim_assessments": updated})


class GeminiTriageAgent:
    """Intake classifier backed by a single structured-output Gemini call."""

    def __init__(self, client: GeminiClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> GeminiClient:
        if self._client is None:
            self._client = get_client()
        return self._client

    async def triage(self, inputs: TriageInput) -> TriageOutcome:
        """Classify the complaint and emit the evidentiary standard."""
        settings = get_settings()

        reporter_block = (
            f"Citizen summary: {inputs.reporter_summary}"
            if inputs.reporter_summary
            else "No citizen summary provided."
        )
        image_block = (
            "An optional image is attached inline. Assess it directly."
            if inputs.image_bytes
            else "No image was provided."
        )

        user_prompt = _TRIAGE_USER_TEMPLATE.format(
            title=inputs.title,
            description=inputs.description,
            lat=inputs.location.lat,
            lng=inputs.location.lng,
            ward=inputs.ward,
            category_hint=inputs.category_hint or "not provided",
            reporter_block=reporter_block,
            image_block=image_block,
        )

        contents: list[types.Part] = [build_text_part(user_prompt)]
        if inputs.image_bytes and inputs.image_mime:
            contents.append(build_image_part(inputs.image_bytes, inputs.image_mime))

        config = build_config(
            response_schema=triage_schema(),
            system_instruction=TRIAGE_SYSTEM,
            temperature=settings.gemini_temperature,
        )

        response, call = await self.client.call_with_fallback(
            primary_model=settings.triage_model,
            fallback_model=settings.fallback_model,
            contents=contents,
            config=config,
            timeout_s=settings.triage_timeout_s,
        )

        raw = _extract_json(response)
        result = _clamp_min_repair_minutes(TriageResult.model_validate(raw), settings)

        return TriageOutcome(result=result, call=call)


class GeminiAuditorAgent:
    """Closure forensics backed by a single structured-output Gemini call."""

    def __init__(self, client: GeminiClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> GeminiClient:
        if self._client is None:
            self._client = get_client()
        return self._client

    async def audit(self, inputs: AuditorInput) -> AuditorOutcome:
        """Audit one closure attempt and enforce the invariants at the boundary."""
        settings = get_settings()

        user_prompt = _AUDITOR_USER_TEMPLATE.format(
            defect_claim=inputs.defect_claim,
            evidence_required="\n".join(f"- {item}" for item in inputs.evidence_required)
            or "- none specified",
            remarks=inputs.closure_remarks,
            work_order_block=(
                f"Work order reference: {inputs.work_order_reference}"
                if inputs.work_order_reference
                else "No work order reference was provided."
            ),
            snapshot_block=_format_snapshot(inputs),
        )

        contents: list[types.Part] = [build_text_part(user_prompt)]
        if inputs.before_image_bytes and inputs.before_image_mime:
            contents.append(build_image_part(inputs.before_image_bytes, inputs.before_image_mime))
        if inputs.after_image_bytes and inputs.after_image_mime:
            contents.append(build_image_part(inputs.after_image_bytes, inputs.after_image_mime))

        config = build_config(
            response_schema=auditor_schema(),
            system_instruction=AUDITOR_SYSTEM,
            temperature=settings.gemini_temperature,
        )

        degraded = False
        reason: str | None = None
        call: AgentCallRecord | None = None

        try:
            response, call = await self.client.call_with_fallback(
                primary_model=settings.forensics_model,
                fallback_model=settings.fallback_model,
                contents=contents,
                config=config,
                timeout_s=settings.forensics_timeout_s,
            )
            result = AuditorResult.model_validate(_extract_json(response))
        except UpstreamUnavailableError as exc:
            degraded = True
            reason = f"upstream_unavailable:{exc.detail}"
            log.warning("auditor.degraded", reason=reason)
            result = _degraded_result(reason)
        except Exception as exc:
            degraded = True
            reason = f"parse_failed:{type(exc).__name__}"
            log.exception("auditor.degraded", reason=reason)
            result = _degraded_result(reason)

        result = _enforce_invariants(result)

        if call is None:
            record = AgentCallRecord(
                model_used="",
                latency_s=0.0,
                fallback_used=False,
                attempts=0,
                degraded=True,
                reason=reason,
            )
        elif degraded:
            record = replace(call, degraded=True, reason=reason)
        else:
            record = call

        return AuditorOutcome(result=result, call=record)
