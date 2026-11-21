"use client";

import { cn } from "@/lib/utils";
import { formatEventTitle, formatEventTimestamp, formatChainHash } from "@/lib/format";
import type { PassportEvent } from "@/lib/types";
import {
    FileText,
    Zap,
    ArrowRight,
    Wrench,
    Camera,
    Shield,
    CheckCircle2,
    XCircle,
    Clock,
    AlertTriangle,
    RotateCcw,
    User,
    Scale,
} from "lucide-react";

interface PassportTimelineProps {
    events: PassportEvent[];
    chainValid: boolean;
}

const eventIcons: Record<string, any> = {
    asset_created: FileText,
    complaint_reported: FileText,
    triage_completed: Zap,
    priority_escalated: AlertTriangle,
    complaint_assigned: ArrowRight,
    work_started: Wrench,
    closure_attempt_submitted: Camera,
    forensic_report_issued: Shield,
    citizen_accepted: CheckCircle2,
    citizen_rejected: XCircle,
    sla_expired: Clock,
    escalated: AlertTriangle,
    reviewer_override: Scale,
    reviewer_returned: RotateCcw,
    reopened: RotateCcw,
};

const eventColors: Record<string, { bg: string; text: string; ring: string }> = {
    complaint_reported: { bg: "bg-blue-600", text: "text-blue-50", ring: "ring-blue-200" },
    triage_completed: { bg: "bg-navy-800", text: "text-bronze-300", ring: "ring-navy-300" },
    priority_escalated: { bg: "bg-bronze-500", text: "text-white", ring: "ring-bronze-200" },
    complaint_assigned: { bg: "bg-slate-600", text: "text-white", ring: "ring-slate-200" },
    work_started: { bg: "bg-amber-600", text: "text-white", ring: "ring-amber-200" },
    closure_attempt_submitted: { bg: "bg-purple-600", text: "text-white", ring: "ring-purple-200" },
    forensic_report_issued: { bg: "bg-indigo-600", text: "text-white", ring: "ring-indigo-200" },
    citizen_accepted: { bg: "bg-sage-600", text: "text-white", ring: "ring-sage-200" },
    citizen_rejected: { bg: "bg-burgundy-600", text: "text-white", ring: "ring-burgundy-200" },
    reopened: { bg: "bg-amber-700", text: "text-white", ring: "ring-amber-200" },
};

const defaultColor = { bg: "bg-ink-500", text: "text-white", ring: "ring-ink-200" };

export function PassportTimeline({ events, chainValid }: PassportTimelineProps) {
    return (
        <div className="space-y-4">
            {/* Chain Status */}
            <div
                className={cn(
                    "flex items-center gap-3 p-4 rounded-sm border",
                    chainValid
                        ? "bg-sage-50 border-sage-500/30"
                        : "bg-burgundy-50 border-burgundy-600/30"
                )}
            >
                <div
                    className={cn(
                        "w-8 h-8 rounded-sm flex items-center justify-center",
                        chainValid ? "bg-sage-600" : "bg-burgundy-600"
                    )}
                >
                    {chainValid ? (
                        <CheckCircle2 className="w-4 h-4 text-white" />
                    ) : (
                        <AlertTriangle className="w-4 h-4 text-white" />
                    )}
                </div>
                <div>
                    <p className={cn("font-medium text-sm", chainValid ? "text-sage-900" : "text-burgundy-900")}>
                        {chainValid ? "Hash chain intact" : "Chain integrity compromised"}
                    </p>
                    <p className="text-xs text-ink-500 mt-0.5">
                        {events.length} event{events.length !== 1 ? "s" : ""} · Append-only since creation
                    </p>
                </div>
            </div>

            {/* Timeline */}
            <div className="relative">
                {/* Connecting line */}
                <div className="absolute left-[15px] top-4 bottom-4 w-[2px] bg-ink-200" />

                <div className="space-y-0 gov-stagger">
                    {events.map((event, i) => {
                        const Icon = eventIcons[event.event_type] || FileText;
                        const color = eventColors[event.event_type] || defaultColor;

                        return (
                            <div key={event.event_id} className="relative pl-12 pb-6 last:pb-0">
                                {/* Node */}
                                <div
                                    className={cn(
                                        "absolute left-0 top-1 w-8 h-8 rounded-sm flex items-center justify-center ring-4 ring-cream-50 z-10",
                                        color.bg
                                    )}
                                >
                                    <Icon className={cn("w-4 h-4", color.text)} />
                                </div>

                                {/* Content */}
                                <div className="bg-white border border-ink-200 rounded-sm p-4 shadow-institutional hover:shadow-institutional-lg transition-shadow">
                                    <div className="flex items-start justify-between gap-3 mb-2">
                                        <div>
                                            <h4 className="font-serif font-semibold text-navy-900 text-sm">
                                                {formatEventTitle(event.event_type)}
                                            </h4>
                                            <div className="flex items-center gap-2 mt-1 text-xs text-ink-500">
                                                <span className="font-mono">seq {event.seq}</span>
                                                <span>·</span>
                                                <span className="flex items-center gap-1">
                                                    <User className="w-3 h-3" />
                                                    {event.actor_type}
                                                    {event.actor_id && (
                                                        <span className="font-mono text-ink-700">{event.actor_id}</span>
                                                    )}
                                                </span>
                                            </div>
                                        </div>
                                        <span className="text-xs text-ink-500 tabular-nums flex-shrink-0">
                                            {formatEventTimestamp(event)}
                                        </span>
                                    </div>

                                    {Object.keys(event.payload).length > 0 && (
                                        <div className="mt-2 pt-2 border-t border-ink-100">
                                            <div className="text-xs space-y-1">
                                                {Object.entries(event.payload).slice(0, 3).map(([k, v]) => (
                                                    <div key={k} className="flex items-start gap-2">
                                                        <span className="text-ink-500 uppercase tracking-wider text-[10px] font-medium pt-0.5">
                                                            {k.replace(/_/g, " ")}
                                                        </span>
                                                        <span className="text-ink-900 font-mono text-[11px]">
                                                            {typeof v === "object" ? JSON.stringify(v) : String(v)}
                                                        </span>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    <div className="mt-2 pt-2 border-t border-ink-100 flex items-center justify-between text-[10px] font-mono text-ink-400">
                                        <span>prev: {event.prev_hash ? formatChainHash(event.prev_hash) : "genesis"}</span>
                                        <span>hash: {formatChainHash(event.event_hash)}</span>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}