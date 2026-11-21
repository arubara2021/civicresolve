"use client";

import { cn } from "@/lib/utils";
import { URGENCY_COLORS } from "@/lib/constants";
import type { Urgency } from "@/lib/types";
import { AlertTriangle, ArrowUp, Zap, Activity } from "lucide-react";

interface PriorityBadgeProps {
    urgency: Urgency;
    score: number;
    escalated?: boolean;
    compact?: boolean;
}

const icons = {
    P1: AlertTriangle,
    P2: ArrowUp,
    P3: Zap,
    P4: Activity,
};

export function PriorityBadge({ urgency, score, escalated, compact }: PriorityBadgeProps) {
    const colors = URGENCY_COLORS[urgency];
    const Icon = icons[urgency];

    if (compact) {
        return (
            <div
                className={cn(
                    "inline-flex items-center gap-1.5 px-2 py-1 rounded-sm border font-medium text-xs",
                    colors.bg,
                    colors.text,
                    colors.border
                )}
            >
                <Icon className="w-3 h-3" />
                <span className="font-bold">{urgency}</span>
                <span className="opacity-70">·</span>
                <span className="tabular-nums">{score.toFixed(1)}</span>
            </div>
        );
    }

    return (
        <div
            className={cn(
                "relative inline-flex items-stretch rounded-sm border overflow-hidden shadow-institutional",
                colors.border
            )}
        >
            <div
                className={cn(
                    "flex items-center gap-2 px-3 py-2",
                    colors.bg,
                    colors.text
                )}
            >
                <Icon className="w-4 h-4" />
                <div>
                    <div className="text-[10px] uppercase tracking-wider opacity-80">Priority</div>
                    <div className="font-serif text-lg font-semibold leading-tight">{urgency}</div>
                </div>
            </div>
            <div className="bg-white px-3 py-2 border-l border-ink-200">
                <div className="text-[10px] uppercase tracking-wider text-ink-500">Score</div>
                <div className="font-serif text-lg font-semibold text-navy-900 leading-tight tabular-nums">
                    {score.toFixed(1)}
                </div>
            </div>
            {escalated && (
                <div className="absolute -top-1 -right-1 w-4 h-4 bg-bronze-500 rounded-full flex items-center justify-center shadow-sm gov-pulse">
                    <span className="text-white text-[9px] font-bold">!</span>
                </div>
            )}
        </div>
    );
}