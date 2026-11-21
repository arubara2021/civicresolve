"""Domain vocabulary. The single source of truth for every enumerated value.

Status values are the exact strings the challenge specifies, because they are the
labels a reviewer looks for on the dashboard. Verification detail lives in
SubStatus, never in a renamed primary status.

Two verdict vocabularies exist deliberately. LinkVerdict is the normalised set the
policy engine reasons over. ClaimVerdict is the richer vocabulary the model emits
for claim reconciliation; the forensics layer maps it down before policy sees it.
Keeping the mapping outside the model prevents the model from influencing the
verdict grammar.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """Primary lifecycle states. These strings are part of the public contract."""

    REPORTED = "Reported"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"


class SubStatus(StrEnum):
    """Verification detail carried beneath the primary status."""

    TRIAGED = "triaged"
    ASSIGNED = "assigned"
    WORK_IN_PROGRESS = "work_in_progress"
    PENDING_VERIFICATION = "pending_verification"
    AWAITING_CITIZEN = "awaiting_citizen"
    DISPUTED = "disputed"
    ESCALATED = "escalated"
    REOPENED = "reopened"
    CITIZEN_ACCEPTED = "citizen_accepted"
    REVIEWER_OVERRIDE = "reviewer_override"


_SUB_STATUS_LABELS: dict[SubStatus, str] = {
    SubStatus.TRIAGED: "Triaged by AI",
    SubStatus.ASSIGNED: "Assigned to department",
    SubStatus.WORK_IN_PROGRESS: "Work in progress",
    SubStatus.PENDING_VERIFICATION: "Evidence under audit",
    SubStatus.AWAITING_CITIZEN: "Awaiting citizen verification",
    SubStatus.DISPUTED: "Disputed — deficiencies issued",
    SubStatus.ESCALATED: "Escalated to independent reviewer",
    SubStatus.REOPENED: "Reopened after resolution",
    SubStatus.CITIZEN_ACCEPTED: "Accepted by citizen",
    SubStatus.REVIEWER_OVERRIDE: "Resolved by reviewer override",
}


class Urgency(StrEnum):
    """Assessed urgency band, independent of the computed queue score."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


_URGENCY_WEIGHTS: dict[Urgency, int] = {
    Urgency.P1: 100,
    Urgency.P2: 70,
    Urgency.P3: 40,
    Urgency.P4: 15,
}

_URGENCY_LABELS: dict[Urgency, str] = {
    Urgency.P1: "Critical",
    Urgency.P2: "High",
    Urgency.P3: "Moderate",
    Urgency.P4: "Low",
}

_URGENCY_ORDER: tuple[Urgency, ...] = (Urgency.P1, Urgency.P2, Urgency.P3, Urgency.P4)


class Category(StrEnum):
    """Issue categories the intake model may assign."""

    POTHOLE = "pothole"
    GARBAGE_OVERFLOW = "garbage_overflow"
    STREETLIGHT_FAILURE = "streetlight_failure"
    WATER_LEAKAGE = "water_leakage"
    ROAD_DAMAGE = "road_damage"
    DRAINAGE = "drainage"
    OTHER = "other"


class Department(StrEnum):
    """Routing targets. Codes are stored; labels are displayed."""

    ROADS_MAINTENANCE = "roads_maintenance"
    SOLID_WASTE = "solid_waste"
    ELECTRICAL_STREETLIGHTING = "electrical_streetlighting"
    WATER_SEWERAGE = "water_sewerage"
    PUBLIC_WORKS = "public_works"
    STORM_DRAINAGE = "storm_drainage"
    HEALTH_SANITATION = "health_sanitation"
    GENERAL_ADMINISTRATION = "general_administration"


_DEPARTMENT_LABELS: dict[Department, str] = {
    Department.ROADS_MAINTENANCE: "Municipal Roads & Maintenance",
    Department.SOLID_WASTE: "Solid Waste Management",
    Department.ELECTRICAL_STREETLIGHTING: "Electrical & Street Lighting",
    Department.WATER_SEWERAGE: "Water Supply & Sewerage",
    Department.PUBLIC_WORKS: "Public Works Department",
    Department.STORM_DRAINAGE: "Storm Water Drainage",
    Department.HEALTH_SANITATION: "Municipal Health & Sanitation",
    Department.GENERAL_ADMINISTRATION: "General Administration",
}

_CATEGORY_DEPARTMENT: dict[Category, Department] = {
    Category.POTHOLE: Department.ROADS_MAINTENANCE,
    Category.GARBAGE_OVERFLOW: Department.SOLID_WASTE,
    Category.STREETLIGHT_FAILURE: Department.ELECTRICAL_STREETLIGHTING,
    Category.WATER_LEAKAGE: Department.WATER_SEWERAGE,
    Category.ROAD_DAMAGE: Department.PUBLIC_WORKS,
    Category.DRAINAGE: Department.STORM_DRAINAGE,
    Category.OTHER: Department.GENERAL_ADMINISTRATION,
}

# Baseline physical repair durations. The intake service clamps the model's
# suggestion between the configured floor and ceiling, so a model cannot invent an
# implausibly short window that would let a same-hour closure pass the temporal link.
_CATEGORY_REPAIR_MINUTES: dict[Category, int] = {
    Category.POTHOLE: 120,
    Category.GARBAGE_OVERFLOW: 60,
    Category.STREETLIGHT_FAILURE: 90,
    Category.WATER_LEAKAGE: 120,
    Category.ROAD_DAMAGE: 240,
    Category.DRAINAGE: 180,
    Category.OTHER: 120,
}


class ImpactLevel(StrEnum):
    """Coarse population exposure, reported alongside the numeric impact score."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LinkName(StrEnum):
    """The six links of the closure evidence chain."""

    TEMPORAL = "temporal"
    GEOSPATIAL = "geospatial"
    VISUAL_SUFFICIENCY = "visual_sufficiency"
    CLAIM_EVIDENCE = "claim_evidence"
    PROVENANCE = "provenance"
    DUPLICATION = "duplication"


class LinkVerdict(StrEnum):
    """Normalised verdict grammar consumed by the policy engine.

    DEFICIENT means required evidence is absent, which is distinct from FAIL
    meaning present evidence contradicts the claim. Absence is never treated as
    proof of fraud, but it still blocks closure.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    DEFICIENT = "DEFICIENT"
    INCONCLUSIVE = "INCONCLUSIVE"


class ClaimVerdict(StrEnum):
    """Model-facing vocabulary for claim-to-evidence reconciliation."""

    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    INCONCLUSIVE = "INCONCLUSIVE"


_CLAIM_TO_LINK: dict[ClaimVerdict, LinkVerdict] = {
    ClaimVerdict.SUPPORTED: LinkVerdict.PASS,
    ClaimVerdict.PARTIAL: LinkVerdict.DEFICIENT,
    ClaimVerdict.CONTRADICTED: LinkVerdict.FAIL,
    ClaimVerdict.INCONCLUSIVE: LinkVerdict.INCONCLUSIVE,
}


class Framing(StrEnum):
    """Evidentiary framing of a closure photograph."""

    CLOSE_UP = "close_up"
    MID_RANGE = "mid_range"
    WIDE_STREET_VIEW = "wide_street_view"


class EvidenceKind(StrEnum):
    """Role of an uploaded file within a closure attempt."""

    BEFORE = "before"
    AFTER = "after"
    WORK_ORDER = "work_order"
    OTHER = "other"


class EvidenceRequirement(StrEnum):
    """Proof demanded at intake, before the repairing party is known."""

    GEO_TAGGED_CLOSEUP = "geo_tagged_closeup_of_repaired_zone"
    CAPTURE_AFTER_COMPLETION = "capture_timestamp_after_work_completion"
    WORK_ORDER_REFERENCE = "work_order_reference"
    SITE_SPECIFIC_REMARKS = "site_specific_remarks"
    BEFORE_AFTER_PAIR = "before_after_pair"


class DeficiencyCode(StrEnum):
    """Machine-readable deficiencies, each mapped to a concrete remedy."""

    MISSING_GEOTAG = "missing_geotag"
    LOCATION_MISMATCH = "location_mismatch"
    WIDE_FRAMING = "wide_framing"
    DEFECT_ZONE_NOT_VISIBLE = "defect_zone_not_visible"
    STALE_CAPTURE = "stale_capture"
    IMPLAUSIBLE_DURATION = "implausible_duration"
    CAPTURE_TIME_UNKNOWN = "capture_time_unknown"
    MISSING_WORK_ORDER = "missing_work_order"
    GENERIC_REMARKS = "generic_remarks"
    REUSED_PHOTO = "reused_photo"
    CLAIM_UNSUPPORTED = "claim_unsupported"
    METADATA_STRIPPED = "metadata_stripped"
    EDIT_SOFTWARE_DETECTED = "edit_software_detected"


class ActorType(StrEnum):
    """Who performed an action. Authority is derived from this, never from a role flag."""

    CITIZEN = "citizen"
    OFFICER = "officer"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    SYSTEM = "system"


class Action(StrEnum):
    """State-machine inputs."""

    ASSIGN = "assign"
    START_WORK = "start_work"
    SUBMIT_CLOSURE = "submit_closure"
    AUDIT_PASS = "audit_pass"
    AUDIT_FAIL = "audit_fail"
    ACCEPT = "accept"
    REJECT = "reject"
    SLA_EXPIRE = "sla_expire"
    REVIEWER_RESOLVE = "reviewer_resolve"
    REVIEWER_RETURN = "reviewer_return"
    REOPEN = "reopen"


class DecisionType(StrEnum):
    """Citizen or reviewer decision on a closure attempt."""

    ACCEPT = "accept"
    REJECT = "reject"


class EventType(StrEnum):
    """Append-only passport event types."""

    ASSET_CREATED = "asset_created"
    COMPLAINT_REPORTED = "complaint_reported"
    TRIAGE_COMPLETED = "triage_completed"
    PRIORITY_ESCALATED = "priority_escalated"
    COMPLAINT_ASSIGNED = "complaint_assigned"
    WORK_STARTED = "work_started"
    CLOSURE_ATTEMPT_SUBMITTED = "closure_attempt_submitted"
    FORENSIC_REPORT_ISSUED = "forensic_report_issued"
    CITIZEN_ACCEPTED = "citizen_accepted"
    CITIZEN_REJECTED = "citizen_rejected"
    SLA_EXPIRED = "sla_expired"
    ESCALATED = "escalated"
    REVIEWER_OVERRIDE = "reviewer_override"
    REVIEWER_RETURNED = "reviewer_returned"
    REOPENED = "reopened"


# Convenience accessors keep domain knowledge in one place rather than scattered
# across services that would otherwise each hardcode their own mapping.


def urgency_weight(urgency: Urgency) -> int:
    """Numeric weight of an urgency band for priority composition."""
    return _URGENCY_WEIGHTS[urgency]


def urgency_label(urgency: Urgency) -> str:
    """Human-readable urgency label."""
    return _URGENCY_LABELS[urgency]


def escalate_urgency(urgency: Urgency) -> Urgency:
    """Return one band higher, saturating at P1."""
    index = _URGENCY_ORDER.index(urgency)
    return _URGENCY_ORDER[max(0, index - 1)]


def sub_status_label(sub_status: SubStatus) -> str:
    """Human-readable verification detail for the dashboard badge."""
    return _SUB_STATUS_LABELS[sub_status]


def department_label(department: Department) -> str:
    """Human-readable department name."""
    return _DEPARTMENT_LABELS[department]


def default_department(category: Category) -> Department:
    """Deterministic routing fallback used when the model is unavailable."""
    return _CATEGORY_DEPARTMENT[category]


def baseline_repair_minutes(category: Category) -> int:
    """Category-specific minimum plausible repair duration."""
    return _CATEGORY_REPAIR_MINUTES[category]


def claim_to_link_verdict(verdict: ClaimVerdict) -> LinkVerdict:
    """Project the model's claim vocabulary onto the policy engine's grammar."""
    return _CLAIM_TO_LINK[verdict]
