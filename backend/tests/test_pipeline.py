"""Checkpoint 7. Act 3 is caught, Act 5 passes, on the same inputs every run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ports import AgentCallRecord, AuditorOutcome
from app.domain.enums import (
    Category,
    ClaimVerdict,
    DeficiencyCode,
    EvidenceRequirement,
    Framing,
    LinkName,
    LinkVerdict,
    Status,
    SubStatus,
)
from app.domain.models import Asset, ClosureAttempt, Complaint, EvidenceFile
from app.domain.schemas import AuditorResult, ClaimAssessment, VisualSufficiency
from app.forensics.duplication import reset_corpus
from app.forensics.pipeline import run_pipeline
from app.tools.dup_text_tool import get_index

FAKE_REMARK = "Pothole filled with bitumen; road restored to motarable condition."
HONEST_REMARK = (
    "Left wheel path pothole at school gate cut and filled with bitumen mix, "
    "compacted, edge sealed — WO/4471"
)
BULK_TICKETS = ["WRD-1042", "WRD-1044", "WRD-1051", "WRD-1055", "WRD-1060", "WRD-1063"]


@pytest.fixture(autouse=True)
def _clean_index():
    reset_corpus()
    yield
    reset_corpus()


class MockStorage:
    async def read(self, key: str) -> bytes:
        return b"image-bytes"

    async def exists(self, key: str) -> bool:
        return True

    def path_for(self, key: str) -> str:
        return key


def _auditor(verdict: LinkVerdict, claim: ClaimVerdict, observation: str):
    def _factory():
        class _Agent:
            async def audit(self, inputs):
                return AuditorOutcome(
                    result=AuditorResult(
                        visual_sufficiency=VisualSufficiency(
                            verdict=verdict,
                            framing=Framing.WIDE_STREET_VIEW
                            if verdict is LinkVerdict.FAIL
                            else Framing.CLOSE_UP,
                            defect_zone_visible=verdict is LinkVerdict.PASS,
                            reason=observation,
                        ),
                        claim_assessments=[
                            ClaimAssessment(
                                claim="filled with bitumen",
                                verdict=claim,
                                observation=observation,
                            )
                        ],
                        observed_condition=observation,
                        additional_deficiencies=[],
                        confidence=0.91,
                    ),
                    call=AgentCallRecord(
                        model_used="stub-auditor", latency_s=0.01, fallback_used=False, attempts=1
                    ),
                )

        return _Agent()

    return _factory


@pytest.fixture
async def act3(session: AsyncSession) -> dict:
    now = datetime.now(UTC)
    created = now - timedelta(minutes=47)

    asset = Asset(
        id="AST-0042", ward="WARD-12", label="MG Road service lane",
        lat=28.45950, lng=77.02660,
        defect_claim="unfilled pothole approx 40cm wide in left wheel path",
        evidence_standard=[
            EvidenceRequirement.GEO_TAGGED_CLOSEUP.value,
            EvidenceRequirement.WORK_ORDER_REFERENCE.value,
        ],
        min_repair_minutes=120,
    )
    session.add(asset)
    await session.flush()

    prior = Complaint(
        id="WRD-1042", asset_id=asset.id, reporter_id="CIT-100", title="Pothole",
        description="Recurring pothole", category=Category.POTHOLE.value, ward="WARD-12",
        lat=28.4595, lng=77.0266, status=Status.RESOLVED.value,
        sub_status=SubStatus.CITIZEN_ACCEPTED.value, department="roads_maintenance",
    )
    session.add(prior)
    await session.flush()

    prior_attempt = ClosureAttempt(
        id="ATT-0000", complaint_id=prior.id, asset_id=asset.id, attempt_number=1,
        officer_id="OFF-117", remarks=FAKE_REMARK, chain_sufficient=True,
    )
    session.add(prior_attempt)
    await session.flush()
    session.add(
        EvidenceFile(
            id="EVI-0000", asset_id=asset.id, complaint_id=prior.id, attempt_id=prior_attempt.id,
            kind="after", storage_key="prior.jpg", content_hash="a" * 64,
            mime_type="image/jpeg", phash="0" * 16,
        )
    )

    complaint = Complaint(
        id="WRD-1071", asset_id=asset.id, reporter_id="CIT-201", title="Pothole near school",
        description="Two scooter riders almost fell", category=Category.POTHOLE.value,
        ward="WARD-12", lat=28.45952, lng=77.02663, status=Status.IN_PROGRESS.value,
        sub_status=SubStatus.WORK_IN_PROGRESS.value, department="roads_maintenance",
        triage={"defect_claim": asset.defect_claim}, min_repair_minutes=120, created_at=created,
    )
    session.add(complaint)
    await session.flush()

    attempt = ClosureAttempt(
        id="ATT-0001", complaint_id=complaint.id, asset_id=asset.id, attempt_number=1,
        officer_id="OFF-117", remarks=FAKE_REMARK,
        work_completed_at=created + timedelta(minutes=47),
    )
    session.add(attempt)
    await session.flush()

    after = EvidenceFile(
        id="EVI-0001", asset_id=asset.id, complaint_id=complaint.id, attempt_id=attempt.id,
        kind="after", storage_key="fake.jpg", content_hash="a" * 64,
        mime_type="image/jpeg", phash="0" * 16,
    )
    session.add(after)
    await session.commit()

    for ticket in BULK_TICKETS:
        get_index().upsert("WARD-12", ticket, FAKE_REMARK)

    return {"complaint": complaint, "attempt": attempt, "after": after}


@pytest.fixture
async def act5(session: AsyncSession) -> dict:
    now = datetime.now(UTC)
    asset = Asset(
        id="AST-0043", ward="WARD-12", label="Sector 4 crossing",
        lat=28.45950, lng=77.02660, defect_claim="unfilled pothole in left wheel path",
        evidence_standard=[
            EvidenceRequirement.GEO_TAGGED_CLOSEUP.value,
            EvidenceRequirement.CAPTURE_AFTER_COMPLETION.value,
            EvidenceRequirement.WORK_ORDER_REFERENCE.value,
        ],
        min_repair_minutes=120,
    )
    session.add(asset)
    await session.flush()

    complaint = Complaint(
        id="WRD-1072", asset_id=asset.id, reporter_id="CIT-201", title="Pothole",
        description="Deep pothole", category=Category.POTHOLE.value, ward="WARD-12",
        lat=28.45952, lng=77.02663, status=Status.IN_PROGRESS.value,
        sub_status=SubStatus.WORK_IN_PROGRESS.value, department="roads_maintenance",
        triage={"defect_claim": asset.defect_claim}, min_repair_minutes=120,
        created_at=now - timedelta(hours=3),
    )
    session.add(complaint)
    await session.flush()

    attempt = ClosureAttempt(
        id="ATT-0002", complaint_id=complaint.id, asset_id=asset.id, attempt_number=1,
        officer_id="OFF-117", remarks=HONEST_REMARK, work_order_reference="WO/4471",
    )
    session.add(attempt)
    await session.flush()

    after = EvidenceFile(
        id="EVI-0002", asset_id=asset.id, complaint_id=complaint.id, attempt_id=attempt.id,
        kind="after", storage_key="honest.jpg", content_hash="b" * 64, mime_type="image/jpeg",
        phash="f" * 16, gps_lat=28.45954, gps_lng=77.02657,
        captured_at=now - timedelta(minutes=10), camera_make="Pixel", camera_model="Pixel 8",
    )
    session.add(after)
    await session.commit()
    return {"complaint": complaint, "attempt": attempt, "after": after}


async def test_act3_fake_closure_is_caught(session, act3, monkeypatch):
    monkeypatch.setattr(
        "app.forensics.pipeline.get_auditor_agent",
        _auditor(LinkVerdict.FAIL, ClaimVerdict.CONTRADICTED, "No patch visible; broken edge remains"),
    )
    report = await run_pipeline(
        session, MockStorage(), act3["complaint"], act3["attempt"], act3["after"]
    )
    by_link = {item.link: item for item in report.links}

    assert report.decision.sufficient is False
    assert report.reuse_detected is True
    assert report.reuse_matches and report.reuse_matches[0].evidence_id == "EVI-0000"
    assert by_link[LinkName.TEMPORAL].verdict is LinkVerdict.FAIL
    assert by_link[LinkName.GEOSPATIAL].verdict is LinkVerdict.DEFICIENT
    assert by_link[LinkName.PROVENANCE].verdict is LinkVerdict.FAIL
    assert by_link[LinkName.DUPLICATION].verdict is LinkVerdict.FAIL
    assert "WRD-1042" in by_link[LinkName.DUPLICATION].matched_ids
    assert report.decision.blocking_reasons[0] == "reused_photograph"

    codes = {d.code for d in report.deficiencies}
    assert DeficiencyCode.REUSED_PHOTO in codes
    assert DeficiencyCode.GENERIC_REMARKS in codes
    assert all(d.remedy for d in report.deficiencies)


async def test_act5_honest_closure_passes(session, act5, monkeypatch):
    monkeypatch.setattr(
        "app.forensics.pipeline.get_auditor_agent",
        _auditor(LinkVerdict.PASS, ClaimVerdict.SUPPORTED, "Fresh bitumen patch visible at frame centre"),
    )
    report = await run_pipeline(
        session, MockStorage(), act5["complaint"], act5["attempt"], act5["after"]
    )
    assert report.decision.sufficient is True
    assert report.decision.blocking_reasons == []
    assert report.reuse_detected is False
    assert report.deficiencies == []
    assert all(item.verdict is LinkVerdict.PASS for item in report.links)


async def test_pipeline_is_reproducible(session, act5, monkeypatch):
    monkeypatch.setattr(
        "app.forensics.pipeline.get_auditor_agent",
        _auditor(LinkVerdict.PASS, ClaimVerdict.SUPPORTED, "Fresh bitumen patch visible at frame centre"),
    )
    args = (session, MockStorage(), act5["complaint"], act5["attempt"], act5["after"])
    first = await run_pipeline(*args)
    second = await run_pipeline(*args)
    assert first.decision == second.decision
    assert [x.verdict for x in first.links] == [x.verdict for x in second.links]