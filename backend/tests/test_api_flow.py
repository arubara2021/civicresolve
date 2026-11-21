"""Checkpoint 12. Act 1 to Act 7 over HTTP, with the model stubbed.

This is the demo, automated. Two numbers are asserted exactly because they are
the product claim: a brand-new asset scores 54.9, and the same report on a
chronic asset scores higher. The tamper test writes raw SQL, bypassing every
application code path, because that is the threat the passport claims to detect.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.core.db as db
import app.core.lifespan as life
import app.storage.local as local
from app.agents.ports import AgentCallRecord, AuditorOutcome, TriageOutcome
from app.domain.enums import (
    Category,
    ClaimVerdict,
    Department,
    EvidenceRequirement,
    Framing,
    ImpactLevel,
    LinkVerdict,
    Urgency,
)
from app.core.security import reset_security_state
from app.domain.models import Base
from app.domain.schemas import (
    AuditorResult,
    ClaimAssessment,
    DepartmentRecommendation,
    PublicImpact,
    TriageResult,
    VisualSufficiency,
)
from app.forensics.duplication import reset_corpus
from app.main import create_app
from app.tools.dup_text_tool import get_index
from scripts.inject_exif import build_scene

REUSED = "Pothole filled with bitumen; road restored to motarable condition."
HONEST = (
    "Left wheel path pothole at school gate cut and filled with bitumen mix, "
    "compacted, edge sealed - WO/4471"
)
REPORT = {
    "title": "Pothole in left wheel path near school gate",
    "description": "Two scooter riders almost fell this morning. Active injury risk.",
    "lat": "28.45952",
    "lng": "77.02663",
    "reporter_id": "CIT-201",
    "ward": "WARD-12",
    "category_hint": "pothole",
}


class _TriageStub:
    async def triage(self, inputs):
        return TriageOutcome(
            result=TriageResult(
                category=Category.POTHOLE,
                category_confidence=0.95,
                urgency=Urgency.P2,
                urgency_reason="Injury risk to two-wheeler riders beside a school gate.",
                public_impact=PublicImpact(
                    score=78,
                    factors=["school_within_100m", "injury_risk"],
                    affected_population=ImpactLevel.HIGH,
                ),
                department=DepartmentRecommendation(
                    primary=Department.ROADS_MAINTENANCE, confidence=0.93
                ),
                defect_claim="unfilled pothole approx 40cm wide in left wheel path",
                evidence_required_for_closure=[
                    EvidenceRequirement.GEO_TAGGED_CLOSEUP,
                    EvidenceRequirement.CAPTURE_AFTER_COMPLETION,
                    EvidenceRequirement.WORK_ORDER_REFERENCE,
                ],
                min_repair_minutes=120,
                citizen_summary="Pothole filed near the school gate; roads department notified.",
                safety_flags=["injury_risk"],
            ),
            call=AgentCallRecord(
                model_used="stub-triage", latency_s=0.01, fallback_used=False, attempts=1
            ),
        )


class _AuditorStub:
    """Flip the verdict between submissions so one stub serves both acts."""

    def __init__(self) -> None:
        self._verdict = LinkVerdict.FAIL
        self._claim = ClaimVerdict.CONTRADICTED
        self._observation = "No patch visible; the broken edge remains at frame centre."

    def fail(self) -> None:
        self._verdict = LinkVerdict.FAIL
        self._claim = ClaimVerdict.CONTRADICTED
        self._observation = "No patch visible; the broken edge remains at frame centre."

    def pass_(self) -> None:
        self._verdict = LinkVerdict.PASS
        self._claim = ClaimVerdict.SUPPORTED
        self._observation = "Fresh dark bitumen patch visible, compacted, edge sealed."

    async def audit(self, inputs):
        passing = self._verdict is LinkVerdict.PASS
        return AuditorOutcome(
            result=AuditorResult(
                visual_sufficiency=VisualSufficiency(
                    verdict=self._verdict,
                    framing=Framing.CLOSE_UP if passing else Framing.WIDE_STREET_VIEW,
                    defect_zone_visible=passing,
                    reason=self._observation,
                ),
                claim_assessments=[
                    ClaimAssessment(
                        claim="filled with bitumen",
                        verdict=self._claim,
                        observation=self._observation,
                    )
                ],
                observed_condition=self._observation,
                additional_deficiencies=[],
                confidence=0.91,
            ),
            call=AgentCallRecord(
                model_used="stub-auditor", latency_s=0.01, fallback_used=False, attempts=1
            ),
        )


@pytest.fixture
async def api(monkeypatch, tmp_path):
    """A real app on a private in-memory database, with both agents stubbed."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_sessionmaker", factory)
    monkeypatch.setattr(local, "_storage", local.LocalStorage(tmp_path))
    monkeypatch.setattr(life, "register_sla_job", lambda *a, **k: None)
    monkeypatch.setattr(life, "register_outbox_job", lambda *a, **k: None)

    async def _no_seed(_settings):
        return "disabled"

    monkeypatch.setattr(life, "_seed_if_available", _no_seed)

    auditor = _AuditorStub()
    monkeypatch.setattr(
        "app.modules.intake.service.build_triage_agent", lambda *a, **k: _TriageStub()
    )
    monkeypatch.setattr("app.forensics.pipeline.get_auditor_agent", lambda *a, **k: auditor)

    reset_corpus()
    reset_security_state()
    application = create_app()
    transport = ASGITransport(app=application)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield SimpleNamespace(client=client, engine=engine, auditor=auditor)
    reset_corpus()
    reset_security_state()
    await engine.dispose()


async def _backdate(engine, complaint_id: str, hours: int = 3) -> datetime:
    """Test-only time travel so a plausible repair window exists.

    A complaint filed seconds ago cannot have a 120-minute repair. Backdating the
    row is legitimate in a test; it touches no event, so the chain stays intact.
    """
    moment = datetime.now(UTC) - timedelta(hours=hours)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE complaints SET created_at = :moment WHERE id = :id"),
            {"moment": moment.strftime("%Y-%m-%d %H:%M:%S.%f"), "id": complaint_id},
        )
    return moment


async def test_act_one_to_seven_over_http(api) -> None:
    client = api.client

    response = await client.post("/api/complaints", data=REPORT)
    assert response.status_code == 201, response.text
    filed = response.json()
    complaint_id = filed["complaint_id"]
    asset_id = filed["asset_id"]
    assert filed["category"] == "pothole"
    assert filed["department"] == "roads_maintenance"
    assert filed["status"] == "Reported"
    assert filed["urgency"] == "P2"
    assert filed["priority_score"] == 54.9

    created = await _backdate(api.engine, complaint_id)

    for actor, action, extra in (
        ("ADM-01", "assign", {"assignee_department": "roads_maintenance"}),
        ("OFF-117", "start_work", {}),
    ):
        response = await client.patch(
            f"/api/complaints/{complaint_id}/status",
            json={
                "actor_id": actor,
                "actor_type": "admin" if action == "assign" else "officer",
                "action": action,
                **extra,
            },
        )
        assert response.status_code == 200, response.text

    for ticket in ("WRD-1042", "WRD-1044"):
        get_index().upsert("WARD-12", ticket, REUSED)

    api.auditor.fail()
    response = await client.post(
        f"/api/complaints/{complaint_id}/closure-attempts",
        data={
            "officer_id": "OFF-117",
            "remarks": REUSED,
            "work_completed_at": (created + timedelta(minutes=47)).isoformat(),
        },
        files={"after_image": ("fake.jpg", build_scene("fake_after"), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["chain_sufficient"] is False
    verdicts = {item["link"]: item for item in first["report"]["links"]}
    assert verdicts["temporal"]["verdict"] == "FAIL"
    assert verdicts["geospatial"]["verdict"] == "DEFICIENT"
    assert verdicts["duplication"]["verdict"] == "FAIL"
    assert "WRD-1042" in verdicts["duplication"]["matched_ids"]
    assert all(item["remedy"] for item in first["report"]["deficiencies"])

    response = await client.post(
        f"/api/closure-attempts/{first['attempt_id']}/decision",
        json={
            "actor_id": "CIT-201",
            "decision": "reject",
            "reason": "Road still broken at the reported location.",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "In Progress"
    assert response.json()["sub_status"] == "disputed"

    response = await client.post(
        f"/api/complaints/{complaint_id}/closure-attempts",
        data={"officer_id": "OFF-117", "remarks": REUSED},
        files={
            "after_image": (
                "reuse.jpg",
                build_scene("prior_reuse", variant=1),
                "image/jpeg",
            )
        },
    )
    assert response.status_code == 201, response.text
    again = response.json()["report"]
    assert again["reuse_detected"] is True
    assert again["decision"]["blocking_reasons"][0] == "reused_photograph"
    assert again["reuse_matches"][0]["hamming_distance"] == 0

    api.auditor.pass_()
    response = await client.post(
        f"/api/complaints/{complaint_id}/closure-attempts",
        data={
            "officer_id": "OFF-117",
            "remarks": HONEST,
            "work_order_reference": "WO/4471",
        },
        files={"after_image": ("honest.jpg", build_scene("honest_after"), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    honest = response.json()
    assert honest["chain_sufficient"] is True, honest["report"]["decision"]
    assert honest["report"]["reuse_detected"] is False
    assert all(item["verdict"] == "PASS" for item in honest["report"]["links"])

    response = await client.post(
        f"/api/closure-attempts/{honest['attempt_id']}/decision",
        json={"actor_id": "CIT-201", "decision": "accept"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "Resolved"
    assert response.json()["sub_status"] == "citizen_accepted"

    response = await client.post(
        f"/api/complaints/{complaint_id}/reopen",
        data={"actor_id": "CIT-201", "reason": "The patch broke up again within two weeks."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sub_status"] == "reopened"
    assert response.json()["reopen_count"] == 1

    response = await client.get(f"/api/assets/{asset_id}/passport")
    assert response.status_code == 200
    passport = response.json()
    assert passport["chain_verification"]["valid"] is True
    seen = {event["event_type"] for event in passport["timeline"]}
    for expected in (
        "complaint_reported",
        "closure_attempt_submitted",
        "forensic_report_issued",
        "citizen_rejected",
        "citizen_accepted",
        "reopened",
    ):
        assert expected in seen


async def test_admin_cannot_reach_resolved_over_http(api) -> None:
    client = api.client
    created = await client.post("/api/complaints", data=REPORT)
    assert created.status_code == 201, created.text
    filed = created.json()
    response = await client.patch(
        f"/api/complaints/{filed['complaint_id']}/status",
        json={"actor_id": "ADM-01", "actor_type": "admin", "action": "accept"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE_TRANSITION"
    assert response.json()["trace_id"]


async def test_chain_tampering_is_detected_over_http(api) -> None:
    client = api.client
    created = await client.post("/api/complaints", data=REPORT)
    assert created.status_code == 201, created.text
    filed = created.json()
    asset_id = filed["asset_id"]

    clean = (await client.get(f"/api/assets/{asset_id}/verify-chain")).json()
    assert clean["valid"] is True
    assert clean["events_checked"] >= 3

    async with api.engine.begin() as connection:
        await connection.execute(
            text("UPDATE events SET payload = :payload WHERE asset_id = :asset AND seq = 2"),
            {"payload": '{"category":"streetlight_failure"}', "asset": asset_id},
        )

    broken = (await client.get(f"/api/assets/{asset_id}/verify-chain")).json()
    assert broken["valid"] is False
    assert broken["broken_seq"] == 2
    assert broken["reason"] == "event_content_modified"