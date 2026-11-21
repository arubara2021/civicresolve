"""Build the synthetic demo ward from fixtures/demo_trace.json.

Idempotent: seed_if_empty is a no-op once the ward exists, so every boot is safe.

reset_demo drops the entire ward and rebuilds it. That is a teardown, not a
rewrite: no event row is ever edited in place, and the append-only invariant of
the passport is untouched. Reset is disabled in production by configuration.

The six historical closures were accepted under the old regime with the same
photograph and the same remark. That is the chronic-asset narrative, and it is
what makes the passport-derived priority term visible on the next report.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import IdPrefix
from app.core.logging import get_logger
from app.core.sequences import sync_sequence
from app.domain.enums import (
    ActorType,
    Category,
    DecisionType,
    EventType,
    EvidenceKind,
    Status,
    SubStatus,
)
from app.domain.models import (
    Asset,
    ClosureAttempt,
    Complaint,
    Decision,
    Event,
    EvidenceFile,
    IdSequence,
    Notification,
)
from app.forensics.duplication import remember_remarks, reset_corpus
from app.modules.assets.hash_chain import append_event
from app.modules.closure.evidence import store_evidence
from app.storage.local import get_storage
from scripts.inject_exif import build_scene, write_seed_images

log = get_logger(__name__)

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "demo_trace.json"

_TEARDOWN_ORDER = (
    Notification,
    Decision,
    EvidenceFile,
    Event,
    ClosureAttempt,
    Complaint,
    Asset,
    IdSequence,
)


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


async def seed_ward(session: AsyncSession) -> dict:
    """Build the ward. Assumes an empty database; caller owns the transaction."""
    fixture = load_fixture()
    write_seed_images()
    storage = get_storage()
    settings = get_settings()
    now = datetime.now(UTC)
    ward = fixture["ward"]
    reused = fixture["closure_remarks"]["reused"]

    spec = fixture["asset"]
    asset = Asset(
        id=spec["id"],
        asset_type=spec["asset_type"],
        ward=ward,
        label=spec["label"],
        lat=spec["lat"],
        lng=spec["lng"],
        radius_m=spec["radius_m"],
        defect_claim=spec["defect_claim"],
        evidence_standard=spec["evidence_standard"],
        min_repair_minutes=spec["min_repair_minutes"],
        created_at=now - timedelta(days=spec["age_days"]),
    )
    session.add(asset)
    await session.flush()
    await append_event(
        session,
        asset_id=asset.id,
        event_type=EventType.ASSET_CREATED,
        actor_type=ActorType.SYSTEM,
        payload={"ward": ward, "label": asset.label, "synthetic": True},
        occurred_at=asset.created_at,
    )

    triage_blob = {
        "defect_claim": asset.defect_claim,
        "evidence_required_for_closure": asset.evidence_standard,
    }
    attempts_created = 0
    evidence_created = 0

    for index, entry in enumerate(fixture["history"]):
        reported = now - timedelta(days=entry["reported_days_ago"])
        resolved = now - timedelta(days=entry["resolved_days_ago"])
        failed = sum(1 for item in entry["attempts"] if not item["chain_sufficient"])
        complaint = Complaint(
            id=entry["complaint_id"],
            asset_id=asset.id,
            reporter_id=entry["reporter_id"],
            title=entry["title"],
            description=entry["description"],
            category=Category.POTHOLE.value,
            ward=ward,
            lat=asset.lat,
            lng=asset.lng,
            status=Status.RESOLVED.value,
            sub_status=SubStatus.CITIZEN_ACCEPTED.value,
            assessed_urgency="P2",
            urgency="P2",
            impact_score=entry["impact_score"],
            department="roads_maintenance",
            triage=triage_blob,
            min_repair_minutes=asset.min_repair_minutes,
            reopen_count=entry["reopen_count"],
            attempt_count=len(entry["attempts"]),
            failed_attempt_count=failed,
            created_at=reported,
            updated_at=resolved,
            resolved_at=resolved,
        )
        session.add(complaint)
        await session.flush()
        await append_event(
            session,
            asset_id=asset.id,
            event_type=EventType.COMPLAINT_REPORTED,
            actor_type=ActorType.CITIZEN,
            actor_id=complaint.reporter_id,
            payload={"complaint_id": complaint.id, "title": complaint.title},
            occurred_at=reported,
        )

        for item in entry["attempts"]:
            submitted = reported + timedelta(minutes=item["submitted_after_report_minutes"])
            audited = submitted + timedelta(seconds=8)
            attempt = ClosureAttempt(
                id=item["id"],
                complaint_id=complaint.id,
                asset_id=asset.id,
                attempt_number=item["number"],
                officer_id=entry["officer_id"],
                remarks=reused,
                work_order_reference=item.get("work_order_reference"),
                submitted_at=submitted,
                audited_at=audited,
                chain_sufficient=item["chain_sufficient"],
                reuse_detected=False,
                forensic_report={
                    "synthetic": True,
                    "decision": {"sufficient": item["chain_sufficient"]},
                },
                deficiencies=[],
            )
            session.add(attempt)
            await session.flush()
            attempts_created += 1

            data = build_scene("prior_reuse", variant=index)
            await store_evidence(
                session,
                storage=storage,
                complaint=complaint,
                attempt=attempt,
                data=data,
                kind=EvidenceKind.AFTER,
                mime_type="image/jpeg",
            )
            evidence_created += 1

            await append_event(
                session,
                asset_id=asset.id,
                event_type=EventType.CLOSURE_ATTEMPT_SUBMITTED,
                actor_type=ActorType.OFFICER,
                actor_id=attempt.officer_id,
                payload={
                    "complaint_id": complaint.id,
                    "attempt_id": attempt.id,
                    "attempt_number": attempt.attempt_number,
                    "remarks": reused,
                },
                occurred_at=submitted,
            )
            await append_event(
                session,
                asset_id=asset.id,
                event_type=EventType.FORENSIC_REPORT_ISSUED,
                actor_type=ActorType.SYSTEM,
                payload={
                    "complaint_id": complaint.id,
                    "attempt_id": attempt.id,
                    "chain_sufficient": item["chain_sufficient"],
                    "synthetic": True,
                },
                occurred_at=audited,
            )

            decided = submitted + timedelta(minutes=item["decided_after_submit_minutes"])
            accepted = item["decision"] == DecisionType.ACCEPT.value
            session.add(
                Decision(
                    id=f"DEC-{attempts_created:04d}",
                    attempt_id=attempt.id,
                    complaint_id=complaint.id,
                    actor_type=ActorType.CITIZEN.value,
                    actor_id=complaint.reporter_id,
                    decision=item["decision"],
                    reason=item.get("reason"),
                    chain_sufficient_at_decision=item["chain_sufficient"],
                    created_at=decided,
                )
            )
            await append_event(
                session,
                asset_id=asset.id,
                event_type=(
                    EventType.CITIZEN_ACCEPTED if accepted else EventType.CITIZEN_REJECTED
                ),
                actor_type=ActorType.CITIZEN,
                actor_id=complaint.reporter_id,
                payload={
                    "complaint_id": complaint.id,
                    "attempt_id": attempt.id,
                    "decision": item["decision"],
                    "reason": item.get("reason"),
                },
                occurred_at=decided,
            )

        remember_remarks(ward, complaint.id, reused)

    live = fixture["live_complaint"]
    live_created = now - timedelta(minutes=live["created_minutes_ago"])
    live_complaint = Complaint(
        id=live["id"],
        asset_id=asset.id,
        reporter_id=live["reporter_id"],
        title=live["title"],
        description=live["description"],
        category=Category.POTHOLE.value,
        ward=ward,
        lat=28.45952,
        lng=77.02663,
        status=Status.IN_PROGRESS.value,
        sub_status=SubStatus.WORK_IN_PROGRESS.value,
        assessed_urgency=live["assessed_urgency"],
        urgency=live["urgency"],
        impact_score=live["impact_score"],
        history_risk=live["history_risk"],
        priority_score=live["priority_score"],
        department=live["department"],
        assignee_department=live["department"],
        assigned_officer_id=live["officer_id"],
        triage=triage_blob,
        min_repair_minutes=asset.min_repair_minutes,
        created_at=live_created,
        updated_at=now,
        sla_deadline=now + timedelta(seconds=settings.effective_sla_seconds),
    )
    session.add(live_complaint)
    await session.flush()

    for event_type, actor_type, actor_id, offset in (
        (EventType.COMPLAINT_REPORTED, ActorType.CITIZEN, live["reporter_id"], 0),
        (EventType.TRIAGE_COMPLETED, ActorType.SYSTEM, None, 4),
        (EventType.PRIORITY_ESCALATED, ActorType.SYSTEM, None, 5),
        (EventType.COMPLAINT_ASSIGNED, ActorType.ADMIN, "ADM-01", 60),
        (EventType.WORK_STARTED, ActorType.OFFICER, live["officer_id"], 900),
    ):
        await append_event(
            session,
            asset_id=asset.id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "complaint_id": live_complaint.id,
                "assessed_urgency": live["assessed_urgency"],
                "final_urgency": live["urgency"],
                "priority_score": live["priority_score"],
                "history_risk": live["history_risk"],
            },
            occurred_at=live_created + timedelta(seconds=offset),
        )

    for prefix, value in fixture["sequences"].items():
        await sync_sequence(session, IdPrefix(prefix), value)
    await sync_sequence(session, IdPrefix.DECISION, attempts_created)
    await session.flush()

    summary = {
        "asset_id": asset.id,
        "ward": ward,
        "historical_complaints": len(fixture["history"]),
        "live_complaint_id": live_complaint.id,
        "closure_attempts": attempts_created,
        "evidence_files": evidence_created,
        "reused_remark_tickets": [entry["complaint_id"] for entry in fixture["history"]],
        "next_complaint_id": f"WRD-{fixture['sequences']['WRD'] + 1:04d}",
    }
    log.info("demo.seeded", **summary)
    return summary


async def seed_if_empty(session: AsyncSession) -> bool:
    """Seed only when the demo asset is absent. Called from lifespan."""
    fixture = load_fixture()
    if await session.get(Asset, fixture["asset"]["id"]) is not None:
        return False
    await seed_ward(session)
    return True


async def reset_demo(session: AsyncSession) -> dict:
    """Drop the whole ward and rebuild it. Never edits an existing event row."""
    for model in _TEARDOWN_ORDER:
        await session.execute(delete(model))
    await session.flush()
    reset_corpus()
    summary = await seed_ward(session)
    log.warning("demo.reset", tables_cleared=len(_TEARDOWN_ORDER))
    return summary


async def demo_state(session: AsyncSession) -> dict:
    """Current row counts, for the demo panel in the frontend."""
    counts = {}
    for model in (Asset, Complaint, ClosureAttempt, EvidenceFile, Decision, Event, Notification):
        rows = (await session.execute(select(model.id))).scalars().all()
        counts[model.__tablename__] = len(rows)
    return counts