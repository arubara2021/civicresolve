"use client";

import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { PriorityBadge } from "./priority-badge";
import { StatusPill } from "./status-pill";
import { formatRelativeTime } from "@/lib/utils";
import type { ComplaintSummary } from "@/lib/types";
import { MapPin, Clock, User, AlertTriangle } from "lucide-react";

interface ComplaintCardProps {
    complaint: ComplaintSummary;
}

export function ComplaintCard({ complaint }: ComplaintCardProps) {
    const isP1 = complaint.urgency === "P1";

    return (
        <Link href={`/complaint/${complaint.complaint_id}`} className="block group">
            <Card
                hoverable
                className={cn(
                    "overflow-hidden transition-all",
                    isP1 && "border-l-4 border-l-bronze-500"
                )}
            >
                <CardContent className="p-5">
                    <div className="flex items-start justify-between gap-4 mb-3">
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                                <h3 className="font-serif text-lg font-semibold text-navy-900 group-hover:text-bronze-600 transition-colors truncate">
                                    {complaint.title}
                                </h3>
                                {complaint.reopen_count > 0 && (
                                    <span className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-bold bg-amber-100 text-amber-700 rounded-sm uppercase tracking-wider">
                                        <AlertTriangle className="w-3 h-3" />
                                        Reopened {complaint.reopen_count}×
                                    </span>
                                )}
                            </div>
                            <p className="text-xs text-ink-500 font-mono">{complaint.complaint_id}</p>
                        </div>
                        <PriorityBadge
                            urgency={complaint.urgency}
                            score={complaint.priority_score}
                            compact
                        />
                    </div>

                    <div className="flex items-center gap-4 text-xs text-ink-500 mb-3">
                        <span className="flex items-center gap-1">
                            <MapPin className="w-3 h-3" />
                            {complaint.ward}
                        </span>
                        <span className="flex items-center gap-1">
                            <User className="w-3 h-3" />
                            {complaint.department_label}
                        </span>
                        <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {formatRelativeTime(complaint.created_at)}
                        </span>
                    </div>

                    <div className="pt-3 border-t border-ink-100">
                        <StatusPill
                            status={complaint.status}
                            subStatus={complaint.sub_status}
                            compact
                        />
                    </div>
                </CardContent>
            </Card>
        </Link>
    );
}

function cn(...classes: (string | boolean | undefined)[]) {
    return classes.filter(Boolean).join(" ");
}