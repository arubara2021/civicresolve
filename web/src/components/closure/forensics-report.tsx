"use client";

import { cn } from "@/lib/utils";
import { formatDeficiencyRemedy } from "@/lib/format";
import { ChainLink } from "./chain-link";
import type { ForensicReport } from "@/lib/types";
import {
    ShieldCheck,
    ShieldX,
    AlertTriangle,
    CheckCircle2,
    Info,
} from "lucide-react";

interface ForensicsReportProps {
    report: ForensicReport;
}

export function ForensicsReport({ report }: ForensicsReportProps) {
    const { decision, links, deficiencies, reuse_detected, model_used, degraded } = report;

    return (
        <div className="space-y-6 gov-fade-in">
            {/* Verdict Header */}
            <div
                className={cn(
                    "p-6 rounded-sm border",
                    decision.sufficient
                        ? "bg-sage-50 border-sage-500/30"
                        : "bg-burgundy-50 border-burgundy-600/30"
                )}
            >
                <div className="flex items-start gap-4">
                    <div
                        className={cn(
                            "flex-shrink-0 w-12 h-12 rounded-sm flex items-center justify-center",
                            decision.sufficient ? "bg-sage-600" : "bg-burgundy-600"
                        )}
                    >
                        {decision.sufficient ? (
                            <ShieldCheck className="w-6 h-6 text-white" />
                        ) : (
                            <ShieldX className="w-6 h-6 text-white" />
                        )}
                    </div>
                    <div className="flex-1">
                        <h2 className="font-serif text-xl font-semibold text-navy-900 mb-1">
                            {decision.sufficient
                                ? "Evidence Chain Sufficient for Closure"
                                : "Evidence Chain Insufficient"}
                        </h2>
                        <p className="text-sm text-ink-700">
                            {decision.sufficient
                                ? "All six links have been verified. This closure may be presented to the citizen for acceptance."
                                : `${decision.blocking_reasons.length} blocking finding${decision.blocking_reasons.length !== 1 ? "s" : ""} must be addressed before closure.`}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2 text-xs font-mono">
                            {decision.failed_links.map((l) => (
                                <span
                                    key={l}
                                    className="px-2 py-0.5 bg-burgundy-600 text-white rounded-sm"
                                >
                                    ✗ {l.replace(/_/g, " ")}
                                </span>
                            ))}
                            {decision.deficient_links.map((l) => (
                                <span
                                    key={l}
                                    className="px-2 py-0.5 bg-amber-600 text-white rounded-sm"
                                >
                                    ⚠ {l.replace(/_/g, " ")}
                                </span>
                            ))}
                            {decision.inconclusive_links.map((l) => (
                                <span
                                    key={l}
                                    className="px-2 py-0.5 bg-slate-500 text-white rounded-sm"
                                >
                                    ? {l.replace(/_/g, " ")}
                                </span>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            {/* Degraded / Reuse Warnings */}
            {degraded && (
                <div className="flex items-start gap-3 p-4 bg-amber-50 border border-amber-600/30 rounded-sm">
                    <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
                    <div>
                        <h4 className="font-medium text-amber-900">Visual Assessment Degraded</h4>
                        <p className="text-sm text-amber-800 mt-0.5">
                            The visual audit could not complete. The attempt has been routed to a reviewer.
                        </p>
                    </div>
                </div>
            )}

            {reuse_detected && (
                <div className="flex items-start gap-3 p-4 bg-burgundy-50 border border-burgundy-600/30 rounded-sm">
                    <AlertTriangle className="w-5 h-5 text-burgundy-600 flex-shrink-0 mt-0.5" />
                    <div>
                        <h4 className="font-medium text-burgundy-900">Photograph Reuse Detected</h4>
                        <p className="text-sm text-burgundy-800 mt-0.5">
                            This image has been previously submitted as evidence for another closure attempt.
                        </p>
                    </div>
                </div>
            )}

            {/* Chain Links Grid */}
            <div>
                <div className="gov-section-title mb-4">Evidence Chain — Six Links</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {links.map((link, i) => (
                        <ChainLink key={link.link} link={link} index={i} />
                    ))}
                </div>
            </div>

            {/* Deficiencies */}
            {deficiencies.length > 0 && (
                <div className="gov-report-panel bg-white p-6">
                    <div className="flex items-center gap-2 mb-4">
                        <AlertTriangle className="w-5 h-5 text-bronze-600" />
                        <h3 className="font-serif text-lg font-semibold text-navy-900">
                            Required Remedies
                        </h3>
                    </div>
                    <div className="space-y-3 gov-stagger">
                        {deficiencies.map((d, i) => (
                            <div
                                key={i}
                                className="flex items-start gap-3 p-3 bg-cream-50 border border-ink-200 rounded-sm"
                            >
                                <span className="flex-shrink-0 w-6 h-6 bg-bronze-500 text-white rounded-sm flex items-center justify-center text-xs font-bold">
                                    {i + 1}
                                </span>
                                <div className="flex-1">
                                    <p className="text-sm text-ink-900 font-medium">{d.message}</p>
                                    <p className="text-xs text-ink-500 mt-1">
                                        <span className="font-semibold">Remedy:</span>{" "}
                                        {formatDeficiencyRemedy(d.code)}
                                    </p>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Footer meta */}
            <div className="flex items-center justify-between text-xs text-ink-500 pt-4 border-t border-ink-100">
                <div className="flex items-center gap-4">
                    {model_used && (
                        <span className="flex items-center gap-1">
                            <Info className="w-3 h-3" />
                            Model: <span className="font-mono text-ink-700">{model_used}</span>
                        </span>
                    )}
                </div>
                <span className="font-mono">{report.generated_at}</span>
            </div>
        </div>
    );
}