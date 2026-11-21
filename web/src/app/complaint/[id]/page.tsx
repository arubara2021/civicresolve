"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { StatusPill } from "@/components/dashboard/status-pill";
import { PriorityBadge } from "@/components/dashboard/priority-badge";
import { ForensicsReport } from "@/components/closure/forensics-report";
import { ClosureForm } from "@/components/closure/closure-form";
import { PassportTimeline } from "@/components/passport/passport-timeline";
import { api } from "@/lib/api";
import { useActor } from "@/app/providers";
import type { ComplaintSummary, ForensicReport } from "@/lib/types";
import {
    MapPin,
    User,
    Building2,
    Calendar,
    ArrowLeft,
    ThumbsUp,
    ThumbsDown,
    Shield,
    Link as LinkIcon,
} from "lucide-react";

interface ComplaintDetail {
    complaint: any;
    timeline: any[];
    attempts: any[];
    decisions: any[];
}

export default function ComplaintDetailPage() {
    const { id } = useParams<{ id: string }>();
    const router = useRouter();
    const { actor, role } = useActor();
    const [data, setData] = useState<ComplaintDetail | null>(null);
    const [passport, setPassport] = useState<any>(null);
    const [chain, setChain] = useState<any>(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

    useEffect(() => {
        load();
    }, [id]);

    async function load() {
        try {
            const [detail, pass, verify] = await Promise.all([
                api.getComplaint(id),
                api.getPassport(await api.getComplaint(id).then((d) => d.complaint.asset_id)),
                api.verifyChain(await api.getComplaint(id).then((d) => d.complaint.asset_id)),
            ]);
            setData(detail);
            setPassport(pass);
            setChain(verify);
        } catch (err) {
            console.error(err);
        }
    }

    async function handleStatusUpdate(action: string, extra: Record<string, any> = {}) {
        setActionLoading(true);
        setMessage(null);
        try {
            await api.updateStatus(id, {
                actor_id: actor,
                actor_type: role === "admin" ? "admin" : role === "officer" ? "officer" : "citizen",
                action,
                ...extra,
            });
            setMessage({ type: "success", text: `Action '${action}' applied successfully.` });
            await load();
        } catch (err: any) {
            setMessage({ type: "error", text: err.message });
        } finally {
            setActionLoading(false);
        }
    }

    async function handleClosure(data: FormData) {
        await api.submitClosure(id, data);
        setMessage({ type: "success", text: "Closure submitted. Forensics report generated." });
        await load();
    }

    async function handleDecision(attemptId: string, decision: "accept" | "reject", reason?: string) {
        setActionLoading(true);
        try {
            await api.decide(attemptId, { actor_id: actor, decision, reason });
            setMessage({
                type: "success",
                text: decision === "accept" ? "Closure accepted." : "Closure rejected.",
            });
            await load();
        } catch (err: any) {
            setMessage({ type: "error", text: err.message });
        } finally {
            setActionLoading(false);
        }
    }

    if (!data) {
        return (
            <AppShell>
                <div className="max-w-7xl mx-auto px-4 py-12 text-center text-ink-500">Loading...</div>
            </AppShell>
        );
    }

    const c = data.complaint;
    const latestAttempt = data.attempts[0];
    const subStatus = c.sub_status;

    return (
        <AppShell>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                {/* Back */}
                <button
                    onClick={() => router.push("/dashboard")}
                    className="flex items-center gap-2 text-sm text-ink-500 hover:text-navy-900 mb-6 transition-colors"
                >
                    <ArrowLeft className="w-4 h-4" />
                    Back to Dashboard
                </button>

                {message && (
                    <Alert
                        variant={message.type}
                        dismissible
                        onDismiss={() => setMessage(null)}
                        className="mb-6"
                    >
                        {message.text}
                    </Alert>
                )}

                {/* Header */}
                <div className="gov-fade-in mb-8">
                    <div className="flex items-start justify-between gap-6 mb-4">
                        <div>
                            <div className="flex items-center gap-2 text-xs font-mono text-ink-500 mb-2">
                                <span>{c.id}</span>
                                <span>·</span>
                                <span>Asset {c.asset_id}</span>
                            </div>
                            <h1 className="font-serif text-3xl font-semibold text-navy-900">{c.title}</h1>
                            <p className="mt-2 text-ink-700 leading-relaxed max-w-3xl">{c.description}</p>
                        </div>
                        <PriorityBadge
                            urgency={c.urgency}
                            score={c.priority_score}
                            escalated={c.urgency !== c.assessed_urgency}
                        />
                    </div>

                    <div className="flex flex-wrap items-center gap-4 text-sm text-ink-500">
                        <StatusPill status={c.status} subStatus={c.sub_status} />
                        <span className="flex items-center gap-1">
                            <MapPin className="w-4 h-4" />
                            {c.ward}
                        </span>
                        <span className="flex items-center gap-1">
                            <Building2 className="w-4 h-4" />
                            {c.department.replace(/_/g, " ").replace(/\b\w/g, (l: string) => l.toUpperCase())}
                        </span>
                        <span className="flex items-center gap-1">
                            <Calendar className="w-4 h-4" />
                            {new Date(c.created_at).toLocaleDateString()}
                        </span>
                    </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                    {/* Main Column */}
                    <div className="lg:col-span-2 space-y-6">
                        {/* Actions */}
                        <Card className="gov-fade-in" style={{ animationDelay: "100ms" }}>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Shield className="w-5 h-5 text-navy-900" />
                                    Available Actions
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="flex flex-wrap gap-2">
                                {subStatus === "triaged" && role === "admin" && (
                                    <Button
                                        variant="navy"
                                        onClick={() =>
                                            handleStatusUpdate("assign", { assignee_department: c.department })
                                        }
                                        isLoading={actionLoading}
                                    >
                                        Admin: Assign
                                    </Button>
                                )}
                                {subStatus === "assigned" && role === "officer" && (
                                    <Button
                                        variant="navy"
                                        onClick={() => handleStatusUpdate("start_work")}
                                        isLoading={actionLoading}
                                    >
                                        Officer: Start Work
                                    </Button>
                                )}
                                {subStatus === "awaiting_citizen" && role === "citizen" && latestAttempt && (
                                    <>
                                        <Button
                                            variant="secondary"
                                            onClick={() => handleDecision(latestAttempt.id, "accept")}
                                            isLoading={actionLoading}
                                            icon={<ThumbsUp className="w-4 h-4" />}
                                        >
                                            Citizen: Accept
                                        </Button>
                                        <Button
                                            variant="destructive"
                                            onClick={() =>
                                                handleDecision(
                                                    latestAttempt.id,
                                                    "reject",
                                                    "The repair is incomplete or defective."
                                                )
                                            }
                                            isLoading={actionLoading}
                                            icon={<ThumbsDown className="w-4 h-4" />}
                                        >
                                            Citizen: Reject
                                        </Button>
                                    </>
                                )}
                                {subStatus === "disputed" && role === "officer" && (
                                    <p className="text-sm text-ink-500">
                                        Resubmit improved evidence below.
                                    </p>
                                )}
                            </CardContent>
                        </Card>

                        {/* Latest Forensic Report */}
                        {latestAttempt?.forensic_report && (
                            <Card className="gov-fade-in" style={{ animationDelay: "150ms" }}>
                                <CardHeader className="bg-cream-100">
                                    <CardTitle className="flex items-center gap-2">
                                        <LinkIcon className="w-5 h-5 text-bronze-600" />
                                        Forensic Report · Attempt #{latestAttempt.attempt_number}
                                    </CardTitle>
                                </CardHeader>
                                <CardContent className="p-6">
                                    <ForensicsReport report={latestAttempt.forensic_report as ForensicReport} />
                                </CardContent>
                            </Card>
                        )}

                        {/* Closure Form */}
                        {(subStatus === "work_in_progress" || subStatus === "disputed") &&
                            (role === "officer" || role === "admin") && (
                                <div className="gov-fade-in" style={{ animationDelay: "200ms" }}>
                                    <ClosureForm complaintId={c.id} onSubmit={handleClosure} />
                                </div>
                            )}
                    </div>

                    {/* Sidebar — Passport */}
                    <aside className="lg:col-span-1">
                        <Card elevated className="sticky top-24 gov-fade-in" style={{ animationDelay: "250ms" }}>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Shield className="w-5 h-5 text-bronze-500" />
                                    Asset Passport
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                <PassportTimeline
                                    events={passport?.timeline ?? []}
                                    chainValid={chain?.valid ?? true}
                                />
                            </CardContent>
                        </Card>
                    </aside>
                </div>
            </div>
        </AppShell>
    );
}