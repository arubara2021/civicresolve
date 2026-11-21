"use client";

import { cn } from "@/lib/utils";
import { formatLinkName } from "@/lib/format";
import { VERDICT_ICONS } from "@/lib/constants";
import type { LinkResult, LinkVerdict } from "@/lib/types";
import {
    Clock,
    MapPin,
    Camera,
    Scale,
    Shield,
    Copy,
    CheckCircle2,
    XCircle,
    AlertTriangle,
    HelpCircle,
} from "lucide-react";

interface ChainLinkProps {
    link: LinkResult;
    index: number;
}

const linkIcons: Record<string, any> = {
    temporal: Clock,
    geospatial: MapPin,
    visual_sufficiency: Camera,
    claim_evidence: Scale,
    provenance: Shield,
    duplication: Copy,
};

const verdictStyles: Record<LinkVerdict, { bg: string; border: string; icon: any; iconColor: string }> = {
    PASS: {
        bg: "bg-sage-50",
        border: "border-sage-500/30",
        icon: CheckCircle2,
        iconColor: "text-sage-600",
    },
    FAIL: {
        bg: "bg-burgundy-50",
        border: "border-burgundy-600/30",
        icon: XCircle,
        iconColor: "text-burgundy-600",
    },
    DEFICIENT: {
        bg: "bg-amber-50",
        border: "border-amber-600/30",
        icon: AlertTriangle,
        iconColor: "text-amber-600",
    },
    INCONCLUSIVE: {
        bg: "bg-slate-100",
        border: "border-slate-300",
        icon: HelpCircle,
        iconColor: "text-slate-500",
    },
};

export function ChainLink({ link, index }: ChainLinkProps) {
    const LinkIcon = linkIcons[link.link] || Shield;
    const style = verdictStyles[link.verdict];
    const VerdictIcon = style.icon;

    return (
        <div
            className={cn(
                "relative p-4 rounded-sm border transition-all",
                style.bg,
                style.border,
                "gov-fade-in"
            )}
            style={{ animationDelay: `${index * 60}ms` }}
        >
            <div className="flex items-start gap-3">
                <div className="flex-shrink-0 w-10 h-10 bg-white rounded-sm border border-ink-200 flex items-center justify-center shadow-institutional">
                    <LinkIcon className="w-5 h-5 text-navy-900" />
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 mb-1">
                        <div>
                            <div className="text-[10px] uppercase tracking-wider text-ink-500">
                                L{index + 1}
                            </div>
                            <h4 className="font-serif font-medium text-navy-900">
                                {formatLinkName(link.link)}
                            </h4>
                        </div>
                        <div
                            className={cn(
                                "inline-flex items-center gap-1.5 px-2 py-1 text-xs font-bold uppercase tracking-wider rounded-sm bg-white border",
                                style.border
                            )}
                        >
                            <VerdictIcon className={cn("w-3.5 h-3.5", style.iconColor)} />
                            <span className={style.iconColor}>{VERDICT_ICONS[link.verdict]} {link.verdict}</span>
                        </div>
                    </div>

                    <p className="text-sm text-ink-700 leading-relaxed mb-2">{link.reason}</p>

                    {link.measured_value !== undefined && link.threshold !== undefined && (
                        <div className="flex items-center gap-3 text-xs font-mono text-ink-500">
                            <span>
                                Measured: <span className="font-semibold text-ink-700">{link.measured_value.toFixed(1)}</span>
                            </span>
                            <span className="text-ink-300">/</span>
                            <span>
                                Threshold: <span className="font-semibold text-ink-700">{link.threshold.toFixed(1)}</span>
                                {link.unit && <span className="ml-0.5">{link.unit}</span>}
                            </span>
                        </div>
                    )}

                    {link.matched_ids && link.matched_ids.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                            <span className="text-xs text-ink-500">Matched:</span>
                            {link.matched_ids.map((id) => (
                                <span
                                    key={id}
                                    className="px-1.5 py-0.5 text-[10px] font-mono bg-white border border-ink-200 rounded-sm"
                                >
                                    {id}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}