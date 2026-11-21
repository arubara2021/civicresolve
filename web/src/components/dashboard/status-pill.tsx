"use client";

import { cn } from "@/lib/utils";
import { STATUS_COLORS, SUB_STATUS_LABELS } from "@/lib/constants";
import type { Status, SubStatus } from "@/lib/types";

interface StatusPillProps {
    status: Status;
    subStatus: SubStatus;
    compact?: boolean;
}

export function StatusPill({ status, subStatus, compact }: StatusPillProps) {
    const colors = STATUS_COLORS[status];
    const subLabel = SUB_STATUS_LABELS[subStatus] || subStatus;

    if (compact) {
        return (
            <div className="inline-flex items-center gap-2">
                <span
                    className={cn(
                        "px-2 py-0.5 text-xs font-medium rounded-sm",
                        colors.bg,
                        colors.text
                    )}
                >
                    {status}
                </span>
                <span className="text-xs text-ink-500">{subLabel}</span>
            </div>
        );
    }

    return (
        <div
            className={cn(
                "inline-flex items-center gap-3 px-3 py-2 rounded-sm border border-ink-200 bg-white"
            )}
        >
            <div className="flex items-center gap-2">
                <span
                    className={cn(
                        "w-2 h-2 rounded-full",
                        status === "Reported" && "bg-blue-500",
                        status === "In Progress" && "bg-yellow-500 gov-pulse",
                        status === "Resolved" && "bg-green-500"
                    )}
                />
                <span className={cn("font-medium text-sm", colors.text)}>{status}</span>
            </div>
            <span className="text-ink-300">·</span>
            <span className="text-sm text-ink-700">{subLabel}</span>
        </div>
    );
}