import type { Urgency, Status, SubStatus, LinkVerdict } from "./types";

export const URGENCY_COLORS: Record<Urgency, { bg: string; text: string; border: string }> = {
    P1: { bg: "bg-red-900/30", text: "text-red-400", border: "border-red-800" },
    P2: { bg: "bg-orange-900/30", text: "text-orange-400", border: "border-orange-800" },
    P3: { bg: "bg-yellow-900/30", text: "text-yellow-400", border: "border-yellow-800" },
    P4: { bg: "bg-gray-800", text: "text-gray-400", border: "border-gray-700" },
};

export const STATUS_COLORS: Record<Status, { bg: string; text: string }> = {
    Reported: { bg: "bg-blue-900/30", text: "text-blue-400" },
    "In Progress": { bg: "bg-yellow-900/30", text: "text-yellow-400" },
    Resolved: { bg: "bg-green-900/30", text: "text-green-400" },
};

export const SUB_STATUS_LABELS: Record<SubStatus, string> = {
    triaged: "Triaged by AI",
    assigned: "Assigned to department",
    work_in_progress: "Work in progress",
    pending_verification: "Evidence under audit",
    awaiting_citizen: "Awaiting citizen verification",
    disputed: "Disputed — deficiencies issued",
    escalated: "Escalated to independent reviewer",
    reopened: "Reopened after resolution",
    citizen_accepted: "Accepted by citizen",
    reviewer_override: "Resolved by reviewer override",
};

export const LINK_LABELS: Record<string, string> = {
    temporal: "Temporal Integrity",
    geospatial: "Geospatial Consistency",
    visual_sufficiency: "Visual Sufficiency",
    claim_evidence: "Claim Evidence",
    provenance: "Provenance",
    duplication: "Duplication",
};

export const VERDICT_ICONS: Record<LinkVerdict, string> = {
    PASS: "✓",
    FAIL: "✗",
    DEFICIENT: "⚠",
    INCONCLUSIVE: "?",
};

export const ACTORS = {
    CITIZEN: "CIT-201",
    OFFICER: "OFF-117",
    ADMIN: "ADM-01",
    REVIEWER: "REV-01",
} as const;