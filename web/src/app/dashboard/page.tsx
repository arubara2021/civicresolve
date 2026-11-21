"use client";

import { useState, useEffect } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ComplaintCard } from "@/components/dashboard/complaint-card";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { ComplaintSummary, Status, Urgency } from "@/lib/types";
import { FilePlus, Filter, RotateCcw, Loader2 } from "lucide-react";
import Link from "next/link";

export default function DashboardPage() {
    const qc = useQueryClient();
    const [ward, setWard] = useState("");
    const [status, setStatus] = useState<Status | "">("");
    const [urgency, setUrgency] = useState<Urgency | "">("");
    const [refreshing, setRefreshing] = useState(false);

    const { data, isLoading } = useQuery({
        queryKey: queryKeys.complaints.list({
            ward: ward || undefined,
            status: status || undefined,
        }),
        queryFn: () =>
            api.listComplaints({
                ward: ward || undefined,
                status: status || undefined,
                urgency: urgency || undefined,
                limit: 50,
            }),
    });

    const handleResetDemo = async () => {
        setRefreshing(true);
        try {
            await api.resetDemo();
            qc.invalidateQueries({ queryKey: queryKeys.complaints.all });
        } finally {
            setRefreshing(false);
        }
    };

    const complaints = data?.items ?? [];
    const total = data?.total ?? 0;

    return (
        <AppShell>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
                <div className="flex items-start justify-between mb-8 gov-fade-in">
                    <div>
                        <div className="gov-section-title">Triage Queue</div>
                        <h1 className="font-serif text-4xl font-semibold text-navy-900">
                            Priority-Sorted Dashboard
                        </h1>
                        <p className="mt-2 text-ink-700">
                            Sorted by computed priority (urgency × 0.45 + impact × 0.30 + history risk × 0.25).
                        </p>
                    </div>
                    <div className="flex gap-2">
                        <Button
                            variant="outline"
                            onClick={handleResetDemo}
                            isLoading={refreshing}
                            icon={<RotateCcw className="w-4 h-4" />}
                        >
                            Reset Demo
                        </Button>
                        <Link href="/report">
                            <Button variant="navy" icon={<FilePlus className="w-4 h-4" />}>
                                New Report
                            </Button>
                        </Link>
                    </div>
                </div>

                {/* Filters */}
                <Card className="mb-6 gov-fade-in" style={{ animationDelay: "100ms" }}>
                    <CardContent className="p-5">
                        <div className="flex items-center gap-2 mb-3">
                            <Filter className="w-4 h-4 text-ink-500" />
                            <span className="text-sm font-medium text-ink-700">Filters</span>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <Input
                                placeholder="Ward (e.g. WARD-12)"
                                value={ward}
                                onChange={(e) => setWard(e.target.value)}
                            />
                            <select
                                value={status}
                                onChange={(e) => setStatus(e.target.value as any)}
                                className="w-full h-10 px-3 bg-white border border-ink-300 rounded-sm text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-bronze-400/40 focus:border-bronze-500"
                            >
                                <option value="">All Statuses</option>
                                <option value="Reported">Reported</option>
                                <option value="In Progress">In Progress</option>
                                <option value="Resolved">Resolved</option>
                            </select>
                            <select
                                value={urgency}
                                onChange={(e) => setUrgency(e.target.value as any)}
                                className="w-full h-10 px-3 bg-white border border-ink-300 rounded-sm text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-bronze-400/40 focus:border-bronze-500"
                            >
                                <option value="">All Urgencies</option>
                                <option value="P1">P1 — Critical</option>
                                <option value="P2">P2 — High</option>
                                <option value="P3">P3 — Moderate</option>
                                <option value="P4">P4 — Low</option>
                            </select>
                        </div>
                    </CardContent>
                </Card>

                {/* Results */}
                {isLoading ? (
                    <div className="flex items-center justify-center py-20">
                        <Loader2 className="w-8 h-8 text-bronze-500 animate-spin" />
                    </div>
                ) : complaints.length === 0 ? (
                    <Card className="gov-fade-in">
                        <CardContent className="p-12 text-center">
                            <FilePlus className="w-12 h-12 text-ink-300 mx-auto mb-3" />
                            <h3 className="font-serif text-lg font-medium text-navy-900">
                                No complaints match your filters
                            </h3>
                            <p className="text-sm text-ink-500 mt-1">
                                Try resetting filters or file a new report.
                            </p>
                        </CardContent>
                    </Card>
                ) : (
                    <div className="gov-stagger">
                        <div className="flex items-center justify-between mb-4">
                            <p className="text-sm text-ink-500">
                                Showing <span className="font-semibold text-ink-900">{complaints.length}</span> of{" "}
                                <span className="font-semibold text-ink-900">{total}</span> complaints
                            </p>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {complaints.map((c) => (
                                <ComplaintCard key={c.complaint_id} complaint={c} />
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </AppShell>
    );
}