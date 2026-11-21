"""Tamper-evidence assertions.

The central test mutates a stored payload directly with SQL, bypassing every
application code path, and requires verification to name the exact broken sequence
number. That is the property the passport claims, so it is tested adversarially
rather than through the happy path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ActorType, EventType, LinkVerdict
from app.domain.models import Asset, Event
from app.modules.assets.hash_chain import (
    GENESIS_HASH,
    AssetMissingError,
    append_event,
    canonical_json,
    compute_event_hash,
    event_preimage,
    read_events,
    verify_chain,
)

ASSET_ID = "AST-0042"


async def _append_five(session: AsyncSession) -> list[Event]:
    """Reproduce the opening of the worked example."""
    plan = [
        (EventType.COMPLAINT_REPORTED, ActorType.CITIZEN, "CIT-201", {"complaint_id": "WRD-1071"}),
        (EventType.TRIAGE_COMPLETED, ActorType.SYSTEM, None, {"category": "pothole"}),
        (EventType.COMPLAINT_ASSIGNED, ActorType.ADMIN, "ADM-01", {"department": "roads"}),
        (
            EventType.CLOSURE_ATTEMPT_SUBMITTED,
            ActorType.OFFICER,
            "OFF-117",
            {"attempt_id": "ATT-0001"},
        ),
        (
            EventType.FORENSIC_REPORT_ISSUED,
            ActorType.SYSTEM,
            None,
            {"chain_sufficient": False, "temporal": LinkVerdict.FAIL.value},
        ),
    ]
    records = []
    for event_type, actor_type, actor_id, payload in plan:
        records.append(
            await append_event(
                session,
                asset_id=ASSET_ID,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload,
            )
        )
    await session.commit()
    return records


async def test_five_appends_verify_cleanly(session: AsyncSession, asset: Asset) -> None:
    records = await _append_five(session)
    result = await verify_chain(session, ASSET_ID)

    assert result.valid is True
    assert result.events_checked == 5
    assert result.broken_seq is None
    assert result.head_matches is True
    assert [record.seq for record in records] == [1, 2, 3, 4, 5]
    assert records[0].prev_hash == GENESIS_HASH
    assert records[4].event_hash == asset.chain_head_hash


async def test_mutating_event_two_payload_is_detected_at_seq_two(
    session: AsyncSession, asset: Asset
) -> None:
    await _append_five(session)

    await session.execute(
        text("UPDATE events SET payload = :payload WHERE asset_id = :asset AND seq = 2"),
        {"payload": '{"category":"streetlight_failure"}', "asset": ASSET_ID},
    )
    await session.commit()
    session.expire_all()

    result = await verify_chain(session, ASSET_ID)

    assert result.valid is False
    assert result.broken_seq == 2
    assert result.reason == "event_content_modified"
    assert result.expected_hash != result.actual_hash


async def test_relinking_a_hash_to_hide_an_edit_is_still_detected(
    session: AsyncSession, asset: Asset
) -> None:
    """An attacker who recomputes one hash breaks the next event's linkage."""
    await _append_five(session)

    await session.execute(
        text("UPDATE events SET event_hash = :forged WHERE asset_id = :asset AND seq = 2"),
        {"forged": "f" * 64, "asset": ASSET_ID},
    )
    await session.commit()
    session.expire_all()

    result = await verify_chain(session, ASSET_ID)

    assert result.valid is False
    assert result.broken_seq == 2
    assert result.reason == "event_content_modified"


async def test_backdating_an_event_is_detected(session: AsyncSession, asset: Asset) -> None:
    await _append_five(session)
    earlier = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S.%f")

    await session.execute(
        text("UPDATE events SET occurred_at = :moment WHERE asset_id = :asset AND seq = 4"),
        {"moment": earlier, "asset": ASSET_ID},
    )
    await session.commit()
    session.expire_all()

    result = await verify_chain(session, ASSET_ID)

    assert result.valid is False
    assert result.broken_seq == 4


async def test_relabelling_the_actor_is_detected(session: AsyncSession, asset: Asset) -> None:
    await _append_five(session)

    await session.execute(
        text("UPDATE events SET actor_id = 'OFF-999' WHERE asset_id = :asset AND seq = 4"),
        {"asset": ASSET_ID},
    )
    await session.commit()
    session.expire_all()

    result = await verify_chain(session, ASSET_ID)

    assert result.valid is False
    assert result.broken_seq == 4


async def test_deleting_a_middle_event_reports_a_sequence_gap(
    session: AsyncSession, asset: Asset
) -> None:
    await _append_five(session)

    await session.execute(
        text("DELETE FROM events WHERE asset_id = :asset AND seq = 3"), {"asset": ASSET_ID}
    )
    await session.commit()
    session.expire_all()

    result = await verify_chain(session, ASSET_ID)

    assert result.valid is False
    assert result.broken_seq == 3
    assert result.reason == "sequence_gap"


async def test_tampering_with_the_cached_tip_is_detected(
    session: AsyncSession, asset: Asset
) -> None:
    await _append_five(session)

    await session.execute(
        text("UPDATE assets SET chain_head_hash = :tip WHERE id = :asset"),
        {"tip": "a" * 64, "asset": ASSET_ID},
    )
    await session.commit()
    session.expire_all()

    result = await verify_chain(session, ASSET_ID)

    assert result.valid is False
    assert result.reason == "head_pointer_mismatch"


async def test_empty_chain_is_valid(session: AsyncSession, asset: Asset) -> None:
    result = await verify_chain(session, ASSET_ID)

    assert result.valid is True
    assert result.events_checked == 0
    assert asset.chain_head_hash is None


async def test_unknown_asset_reports_explicitly(session: AsyncSession) -> None:
    result = await verify_chain(session, "AST-9999")

    assert result.valid is False
    assert result.reason == "asset_not_found"


async def test_append_to_unknown_asset_raises(session: AsyncSession) -> None:
    with pytest.raises(AssetMissingError):
        await append_event(
            session,
            asset_id="AST-9999",
            event_type=EventType.COMPLAINT_REPORTED,
            actor_type=ActorType.CITIZEN,
        )


async def test_sequence_numbers_are_unique_per_asset(session: AsyncSession, asset: Asset) -> None:
    """The database constraint is the real guard against duplicate sequencing."""
    await append_event(
        session,
        asset_id=ASSET_ID,
        event_type=EventType.COMPLAINT_REPORTED,
        actor_type=ActorType.CITIZEN,
    )
    await session.commit()

    duplicate = Event(
        id="EVT-DUP",
        asset_id=ASSET_ID,
        seq=1,
        event_type=EventType.COMPLAINT_REPORTED.value,
        actor_type=ActorType.CITIZEN.value,
        payload={},
        occurred_at=datetime.now(UTC),
        prev_hash=GENESIS_HASH,
        event_hash="b" * 64,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_chains_are_independent_per_asset(session: AsyncSession, asset: Asset) -> None:
    other = Asset(id="AST-0043", ward="WARD-12", label="Adjacent segment", lat=28.46, lng=77.03)
    session.add(other)
    await session.commit()

    await _append_five(session)
    await append_event(
        session,
        asset_id="AST-0043",
        event_type=EventType.COMPLAINT_REPORTED,
        actor_type=ActorType.CITIZEN,
    )
    await session.commit()

    first = await verify_chain(session, ASSET_ID)
    second = await verify_chain(session, "AST-0043")

    assert first.events_checked == 5
    assert second.events_checked == 1
    assert first.valid and second.valid

    events = await read_events(session, "AST-0043")
    assert events[0].prev_hash == GENESIS_HASH


async def test_read_events_supports_incremental_fetch(session: AsyncSession, asset: Asset) -> None:
    await _append_five(session)
    tail = await read_events(session, ASSET_ID, after_seq=3)

    assert [record.seq for record in tail] == [4, 5]


def test_canonical_json_ignores_key_order() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_canonical_json_renders_enums_and_datetimes() -> None:
    moment = datetime(2026, 11, 18, 9, 12, tzinfo=UTC)
    rendered = canonical_json({"verdict": LinkVerdict.FAIL, "at": moment})

    assert '"FAIL"' in rendered
    assert "2026-11-18T09:12:00.000000+00:00" in rendered


def test_canonical_json_preserves_non_ascii() -> None:
    assert "पोthole" not in canonical_json({"note": "गड्ढा"})
    assert "गड्ढा" in canonical_json({"note": "गड्ढा"})


def test_hash_changes_when_any_envelope_field_changes() -> None:
    moment = datetime(2026, 11, 18, 9, 12, tzinfo=UTC)
    base = event_preimage(
        asset_id=ASSET_ID,
        seq=1,
        event_type=EventType.COMPLAINT_REPORTED,
        actor_type=ActorType.CITIZEN,
        actor_id="CIT-201",
        occurred_at=moment,
        payload={"a": 1},
        prev_hash=GENESIS_HASH,
    )
    original = compute_event_hash(base)

    assert compute_event_hash({**base, "seq": 2}) != original
    assert compute_event_hash({**base, "actor_id": "CIT-202"}) != original
    assert compute_event_hash({**base, "payload": {"a": 2}}) != original
    assert compute_event_hash({**base, "prev_hash": "c" * 64}) != original
