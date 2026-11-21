"""Measured evaluation. Writes eval/results.json.

Two modes, and the distinction is reported in the output rather than hidden:

offline (default) stubs the auditor from each case's declared visible support, so
the visual links are SIMULATED. Only the deterministic links (temporal,
geospatial, provenance, reuse, duplication) are genuinely measured. Runs anywhere,
costs nothing, and is reproducible.

--live calls Gemini for both triage and the visual audit. Every number is then
measured end to end, including triage accuracy and latency.

A metric that was not measured is written as null with a reason. It is never
filled with an estimate, because the whole point of this file is to publish a
false-positive rate that can be defended.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents.ports import AgentCallRecord, AuditorOutcome, TriageInput, TriageOutcome
from app.domain.enums import (
    Category,
    ClaimVerdict,
    Department,
    EvidenceKind,
    EvidenceRequirement,
    Framing,
    ImpactLevel,
    LinkVerdict,
    Status,
    SubStatus,
    Urgency,
)
from app.domain.models import Asset, Base, ClosureAttempt, Complaint, EvidenceFile
from app.domain.schemas import (
    AuditorResult,
    ClaimAssessment,
    DepartmentRecommendation,
    PublicImpact,
    TriageResult,
    VisualSufficiency,
)
from app.forensics.duplication import reset_corpus
from app.forensics.pipeline import run_pipeline
from app.storage.local import LocalStorage
from app.tools.dup_text_tool import get_index
from app.tools.phash_tool import compute_phash
from scripts.inject_exif import inject_exif, render_road_scene

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "eval" / "labels.json"
RESULTS = ROOT / "eval" / "results.json"

REUSED_REMARK = "Pothole filled with bitumen; road restored to motarable condition."
HONEST_REMARK = (
    "Left wheel path pothole cut and filled with bitumen mix, compacted, "
    "edge sealed at the school gate - work order referenced"
)
DEFECT_CLAIM = "unfilled pothole approx 40cm wide in left wheel path, broken edge"
STANDARD = [
    EvidenceRequirement.GEO_TAGGED_CLOSEUP.value,
    EvidenceRequirement.CAPTURE_AFTER_COMPLETION.value,
    EvidenceRequirement.WORK_ORDER_REFERENCE.value,
]
METRES_PER_DEGREE_LAT = 111_320.0


class _StubAuditor:
    """Simulated visual oracle driven by the case's declared visible support."""

    def __init__(self, case: dict) -> None:
        self._case = case

    async def audit(self, inputs) -> AuditorOutcome:
        support = ClaimVerdict(self._case["visible_support"])
        close_up = bool(self._case["close_up"])
        sufficient = close_up and support is ClaimVerdict.SUPPORTED
        observation = (
            "Fresh dark bitumen patch visible at frame centre, edge sealed."
            if sufficient
            else "Repair cannot be confirmed from this frame; no sealed patch visible."
        )
        return AuditorOutcome(
            result=AuditorResult(
                visual_sufficiency=VisualSufficiency(
                    verdict=LinkVerdict.PASS if sufficient else LinkVerdict.FAIL,
                    framing=Framing.CLOSE_UP if close_up else Framing.WIDE_STREET_VIEW,
                    defect_zone_visible=close_up,
                    reason=observation,
                ),
                claim_assessments=[
                    ClaimAssessment(
                        claim="filled with bitumen", verdict=support, observation=observation
                    )
                ],
                observed_condition=observation,
                additional_deficiencies=[],
                confidence=0.9,
            ),
            call=AgentCallRecord(
                model_used="offline-stub", latency_s=0.0, fallback_used=False, attempts=0
            ),
        )


class _StubTriage:
    async def triage(self, inputs: TriageInput) -> TriageOutcome:
        return TriageOutcome(
            result=TriageResult(
                category=Category.POTHOLE,
                category_confidence=0.9,
                urgency=Urgency.P2,
                urgency_reason="Injury risk to two-wheeler riders.",
                public_impact=PublicImpact(
                    score=78, factors=["school_within_100m"], affected_population=ImpactLevel.HIGH
                ),
                department=DepartmentRecommendation(
                    primary=Department.ROADS_MAINTENANCE, confidence=0.9
                ),
                defect_claim=DEFECT_CLAIM,
                evidence_required_for_closure=[EvidenceRequirement(item) for item in STANDARD],
                min_repair_minutes=120,
                citizen_summary="Pothole filed; roads department notified.",
                safety_flags=[],
            ),
            call=AgentCallRecord(
                model_used="offline-stub", latency_s=0.0, fallback_used=False, attempts=0
            ),
        )


def _image(case: dict, captured: datetime, asset: dict) -> bytes:
    raw = render_road_scene(patched=bool(case["patched"]), close_up=bool(case["close_up"]))
    if not case["exif"]:
        return raw
    software = case.get("software")
    return inject_exif(
        raw,
        lat=asset["lat"] + float(case["gps_offset_m"]) / METRES_PER_DEGREE_LAT,
        lng=asset["lng"],
        captured_at=captured,
        software=software.encode("ascii") if software else None,
    )


async def _run_case(case: dict, meta: dict, storage: LocalStorage, live: bool) -> dict:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    reset_corpus()

    asset_spec = meta["asset"]
    now = datetime.now(UTC)
    created = now - timedelta(minutes=meta["complaint_age_minutes"])
    captured = created + timedelta(minutes=case["captured_after_report_min"])
    remarks = REUSED_REMARK if case["remarks"] == "reused" else f"{HONEST_REMARK} ({case['id']})"

    auditor: Any
    if live:
        from app.agents.registry import build_auditor_agent

        auditor = build_auditor_agent()
    else:
        auditor = _StubAuditor(case)

    import app.forensics.pipeline as pipeline_module

    original = pipeline_module.get_auditor_agent
    pipeline_module.get_auditor_agent = lambda *a, **k: auditor

    started = time.monotonic()
    try:
        async with factory() as session:
            asset = Asset(
                id="AST-9001",
                ward="WARD-EVAL",
                label="Evaluation segment",
                lat=asset_spec["lat"],
                lng=asset_spec["lng"],
                radius_m=50.0,
                defect_claim=DEFECT_CLAIM,
                evidence_standard=STANDARD,
                min_repair_minutes=asset_spec["min_repair_minutes"],
            )
            session.add(asset)
            await session.flush()

            complaint = Complaint(
                id="WRD-9001",
                asset_id=asset.id,
                reporter_id="CIT-EVAL",
                title="Pothole in left wheel path",
                description="Recurring pothole beside the school gate.",
                category=Category.POTHOLE.value,
                ward="WARD-EVAL",
                lat=asset_spec["lat"],
                lng=asset_spec["lng"],
                status=Status.IN_PROGRESS.value,
                sub_status=SubStatus.WORK_IN_PROGRESS.value,
                department="roads_maintenance",
                triage={"defect_claim": DEFECT_CLAIM},
                min_repair_minutes=asset_spec["min_repair_minutes"],
                created_at=created,
            )
            session.add(complaint)
            await session.flush()

            if case.get("reuse_prior") or case["remarks"] == "reused":
                prior = Complaint(
                    id="WRD-9000",
                    asset_id=asset.id,
                    reporter_id="CIT-EVAL-OLD",
                    title="Earlier report",
                    description="Earlier report at the same spot.",
                    category=Category.POTHOLE.value,
                    ward="WARD-EVAL",
                    lat=asset_spec["lat"],
                    lng=asset_spec["lng"],
                    status=Status.RESOLVED.value,
                    sub_status=SubStatus.CITIZEN_ACCEPTED.value,
                    department="roads_maintenance",
                    created_at=created - timedelta(days=20),
                )
                session.add(prior)
                await session.flush()
                prior_attempt = ClosureAttempt(
                    id="ATT-9000",
                    complaint_id=prior.id,
                    asset_id=asset.id,
                    attempt_number=1,
                    officer_id="OFF-EVAL",
                    remarks=REUSED_REMARK,
                    chain_sufficient=True,
                )
                session.add(prior_attempt)
                await session.flush()
                prior_bytes = render_road_scene(patched=False, close_up=False, seed_shift=13)
                stored_prior = await storage.save_original(prior_bytes)
                session.add(
                    EvidenceFile(
                        id="EVI-9000",
                        asset_id=asset.id,
                        complaint_id=prior.id,
                        attempt_id=prior_attempt.id,
                        kind=EvidenceKind.AFTER.value,
                        storage_key=stored_prior.key,
                        content_hash=stored_prior.content_hash,
                        mime_type="image/jpeg",
                        size_bytes=stored_prior.size_bytes,
                        phash=compute_phash(prior_bytes),
                    )
                )
                get_index().upsert("WARD-EVAL", prior.id, REUSED_REMARK)
                await session.flush()

            attempt = ClosureAttempt(
                id="ATT-9001",
                complaint_id=complaint.id,
                asset_id=asset.id,
                attempt_number=1,
                officer_id="OFF-EVAL",
                remarks=remarks,
                work_order_reference="WO/EVAL" if case["work_order"] else None,
            )
            session.add(attempt)
            await session.flush()

            data = _image(case, captured, asset_spec)
            stored = await storage.save_original(data)
            evidence = EvidenceFile(
                id="EVI-9001",
                asset_id=asset.id,
                complaint_id=complaint.id,
                attempt_id=attempt.id,
                kind=EvidenceKind.AFTER.value,
                storage_key=stored.key,
                content_hash=stored.content_hash,
                mime_type="image/jpeg",
                size_bytes=stored.size_bytes,
                phash=compute_phash(data),
                captured_at=captured if case["exif"] else None,
                gps_lat=(
                    asset_spec["lat"] + float(case["gps_offset_m"]) / METRES_PER_DEGREE_LAT
                    if case["exif"]
                    else None
                ),
                gps_lng=asset_spec["lng"] if case["exif"] else None,
                camera_make="Pixel" if case["exif"] else None,
                camera_model="Pixel 8" if case["exif"] else None,
                software_tag=case.get("software"),
            )
            session.add(evidence)
            await session.flush()

            report = await run_pipeline(session, storage, complaint, attempt, evidence)
    finally:
        pipeline_module.get_auditor_agent = original
        await engine.dispose()
        reset_corpus()

    latency = round(time.monotonic() - started, 4)
    verdicts = {item.link.value: item.verdict.value for item in report.links}
    return {
        "id": case["id"],
        "label": case["label"],
        "expect_sufficient": case["expect_sufficient"],
        "sufficient": report.decision.sufficient,
        "blocked": not report.decision.sufficient,
        "correct": report.decision.sufficient == case["expect_sufficient"],
        "reuse_detected": report.reuse_detected,
        "degraded": report.degraded,
        "abstained": any(v == LinkVerdict.INCONCLUSIVE.value for v in verdicts.values()),
        "verdicts": verdicts,
        "blocking_reasons": report.decision.blocking_reasons,
        "latency_s": latency,
    }


async def _run_triage(cases: list[dict], live: bool) -> dict:
    if not live:
        return {
            "measured": False,
            "reason": "offline mode stubs triage; category and routing accuracy are not measured",
            "category_accuracy": None,
            "department_accuracy": None,
            "cases": [],
        }
    from app.agents.registry import build_triage_agent

    agent = build_triage_agent()
    rows = []
    for case in cases:
        outcome = await agent.triage(
            TriageInput(
                title=case["title"],
                description=case["description"],
                location={"lat": 28.4595, "lng": 77.0266},
                ward="WARD-EVAL",
            )
        )
        rows.append(
            {
                "id": case["id"],
                "expected_category": case["category"],
                "actual_category": outcome.result.category.value,
                "expected_department": case["department"],
                "actual_department": outcome.result.department.primary.value,
                "latency_s": outcome.call.latency_s,
            }
        )
    return {
        "measured": True,
        "category_accuracy": round(
            sum(r["actual_category"] == r["expected_category"] for r in rows) / len(rows), 4
        ),
        "department_accuracy": round(
            sum(r["actual_department"] == r["expected_department"] for r in rows) / len(rows), 4
        ),
        "cases": rows,
    }


def _summarise(rows: list[dict]) -> dict:
    honest = [r for r in rows if r["label"] == "honest"]
    false_positives = [r for r in honest if r["blocked"]]
    classes: dict[str, dict] = {}
    for label in sorted({r["label"] for r in rows if r["label"] != "honest"}):
        group = [r for r in rows if r["label"] == label]
        caught = [r for r in group if r["blocked"]]
        classes[label] = {
            "cases": len(group),
            "caught": len(caught),
            "recall": round(len(caught) / len(group), 4),
            "missed_ids": [r["id"] for r in group if not r["blocked"]],
        }
    latencies = sorted(r["latency_s"] for r in rows)
    p95_index = max(0, int(round(0.95 * (len(latencies) - 1))))
    return {
        "cases": len(rows),
        "honest_cases": len(honest),
        "false_positives": len(false_positives),
        "false_positive_ids": [r["id"] for r in false_positives],
        "false_positive_rate_on_honest": (
            round(len(false_positives) / len(honest), 4) if honest else None
        ),
        "recall_per_fraud_class": classes,
        "abstention_rate": round(sum(r["abstained"] for r in rows) / len(rows), 4),
        "degraded_rate": round(sum(r["degraded"] for r in rows) / len(rows), 4),
        "p95_pipeline_latency_s": latencies[p95_index],
        "median_pipeline_latency_s": round(statistics.median(latencies), 4),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CivicResolve evaluation harness.")
    parser.add_argument("--live", action="store_true", help="Call Gemini instead of stubbing")
    args = parser.parse_args()

    spec = json.loads(LABELS.read_text(encoding="utf-8"))
    storage = LocalStorage(ROOT / "eval" / ".scratch")

    rows = []
    for case in spec["closure_cases"]:
        row = await _run_case(case, spec["meta"], storage, args.live)
        rows.append(row)
        mark = "ok " if row["correct"] else "MISS"
        print(f"{mark} {row['id']} {row['label']:11s} sufficient={row['sufficient']}")

    triage = await _run_triage(spec["triage_cases"], args.live)
    summary = _summarise(rows)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "live_gemini" if args.live else "offline_stub",
        "visual_links_measured": args.live,
        "scope_note": (
            "Every link measured end to end against Gemini."
            if args.live
            else "Deterministic links measured. Visual links 3 and 4 are SIMULATED from "
            "each label's declared visible support, so their recall is not a model measurement."
        ),
        "cost_per_closure": None,
        "cost_note": "AgentCallRecord does not carry token counts; cost is not measured.",
        "summary": summary,
        "triage": triage,
        "cases": rows,
    }
    RESULTS.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    print(f"mode                        {payload['mode']}")
    print(f"cases                       {summary['cases']}")
    print(f"false-positive rate honest  {summary['false_positive_rate_on_honest']}")
    print(f"abstention rate             {summary['abstention_rate']}")
    print(f"p95 pipeline latency (s)    {summary['p95_pipeline_latency_s']}")
    for label, data in summary["recall_per_fraud_class"].items():
        print(f"recall {label:20s} {data['recall']}  missed={data['missed_ids']}")
    print(f"\nwrote {RESULTS}")


if __name__ == "__main__":
    asyncio.run(main())