export type Status = "Reported" | "In Progress" | "Resolved";
export type SubStatus =
    | "triaged"
    | "assigned"
    | "work_in_progress"
    | "pending_verification"
    | "awaiting_citizen"
    | "disputed"
    | "escalated"
    | "reopened"
    | "citizen_accepted"
    | "reviewer_override";
export type Urgency = "P1" | "P2" | "P3" | "P4";
export type Department =
    | "roads_maintenance"
    | "solid_waste"
    | "electrical_streetlighting"
    | "water_sewerage"
    | "public_works"
    | "storm_drainage"
    | "health_sanitation"
    | "general_administration";
export type LinkVerdict = "PASS" | "FAIL" | "DEFICIENT" | "INCONCLUSIVE";

export interface ComplaintSummary {
    complaint_id: string;
    asset_id: string;
    title: string;
    category: string;
    status: Status;
    sub_status: SubStatus;
    sub_status_label: string;
    urgency: Urgency;
    priority_score: number;
    department: Department;
    department_label: string;
    ward: string;
    created_at: string;
    sla_deadline: string | null;
    reopen_count: number;
}

export interface PassportEvent {
    event_id: string;
    asset_id: string;
    seq: number;
    event_type: string;
    actor_type: string;
    actor_id: string | null;
    payload: Record<string, unknown>;
    occurred_at: string;
    prev_hash: string | null;
    event_hash: string;
}

export interface LinkResult {
    link: string;
    verdict: LinkVerdict;
    reason: string;
    measured_value?: number;
    threshold?: number;
    unit?: string;
    matched_ids?: string[];
    deficiencies?: string[];
}

export interface ForensicReport {
    attempt_id: string;
    complaint_id: string;
    asset_id: string;
    links: LinkResult[];
    reuse_detected: boolean;
    reuse_matches?: { evidence_id: string; hamming_distance: number }[];
    missing_evidence: string[];
    decision: {
        sufficient: boolean;
        blocking_reasons: string[];
        failed_links: string[];
        deficient_links: string[];
        inconclusive_links: string[];
    };
    deficiencies: { code: string; message: string; remedy: string; link?: string }[];
    observed_condition: string | null;
    model_used: string | null;
    degraded: boolean;
    generated_at: string;
}

export interface ClosureAttempt {
    id: string;
    attempt_number: number;
    officer_id: string;
    remarks: string;
    work_order_reference: string | null;
    submitted_at: string;
    chain_sufficient: boolean | null;
    reuse_detected: boolean;
    deficiencies: { code: string; message: string; remedy: string }[];
    forensic_report?: ForensicReport;
}

export interface Notification {
    id: string;
    recipient_id: string;
    event_type: string;
    title: string;
    body: string;
    complaint_id: string | null;
    asset_id: string | null;
    payload: Record<string, unknown>;
    created_at: string;
    read: boolean;
}