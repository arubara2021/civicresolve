import { formatDate, truncateHash } from "./utils";
import type { LinkResult, PassportEvent } from "./types";

export function formatVerdict(verdict: string): string {
    const map: Record<string, string> = {
        PASS: "Verified",
        FAIL: "Failed",
        DEFICIENT: "Incomplete",
        INCONCLUSIVE: "Inconclusive",
    };
    return map[verdict] || verdict;
}

export function formatLinkName(link: string): string {
    const map: Record<string, string> = {
        temporal: "Temporal Integrity",
        geospatial: "Geospatial Consistency",
        visual_sufficiency: "Visual Sufficiency",
        claim_evidence: "Claim-Evidence",
        provenance: "Provenance",
        duplication: "Duplication",
    };
    return map[link] || link.replace(/_/g, " ");
}

export function formatLinkDescription(link: LinkResult): string {
    if (link.measured_value !== undefined && link.threshold !== undefined) {
        return `${link.measured_value.toFixed(1)} ${link.unit || ""} / ${link.threshold.toFixed(1)} ${link.unit || ""}`;
    }
    return link.reason;
}

export function formatEventTitle(eventType: string): string {
    return eventType
        .split("_")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
}

export function formatEventTimestamp(event: PassportEvent): string {
    return formatDate(event.occurred_at);
}

export function formatChainHash(event: PassportEvent): string {
    return truncateHash(event.event_hash, 12);
}

export function formatDeficiencyRemedy(code: string): string {
    const map: Record<string, string> = {
        missing_geotag: "Upload a photo with GPS metadata enabled in camera settings.",
        location_mismatch: "Ensure the photo was taken at the reported location.",
        wide_framing: "Submit a close-up photograph clearly showing the repaired area.",
        defect_zone_not_visible: "Frame the photograph to include the specific defect zone.",
        stale_capture: "Photo must be taken after the complaint was filed.",
        implausible_duration: "Repair time is shorter than physically plausible.",
        capture_time_unknown: "Enable date/time stamping in camera settings.",
        missing_work_order: "Include the official work order reference number.",
        generic_remarks: "Provide site-specific details about the work performed.",
        reused_photo: "Submit an original photograph of this specific repair.",
        claim_unsupported: "The closure text claims work not visible in the photograph.",
        metadata_stripped: "Upload from a camera that preserves EXIF data.",
        edit_software_detected: "Submit an unedited original photograph.",
    };
    return map[code] || "Address the identified deficiency and resubmit.";
}