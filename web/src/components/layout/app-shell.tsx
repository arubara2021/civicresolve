"use client";

import { Topbar } from "./topbar";
import { ReactNode } from "react";
import { useSSE } from "@/hooks/use-sse";
import { useActor } from "@/app/providers";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";

interface AppShellProps {
    children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
    const { actor } = useActor();
    const qc = useQueryClient();

    // Global SSE subscription — refreshes any relevant query on events
    useSSE({
        recipientId: actor,
        onEvent: (eventType) => {
            if (eventType.startsWith("complaint_") || eventType === "reopened") {
                qc.invalidateQueries({ queryKey: queryKeys.complaints.all });
            }
            if (eventType === "forensic_report_issued" || eventType === "citizen_accepted") {
                qc.invalidateQueries({ queryKey: queryKeys.complaints.all });
            }
        },
    });

    return (
        <div className="min-h-screen bg-cream-50 flex flex-col">
            <Topbar />
            <main className="flex-1">{children}</main>
            <footer className="border-t border-ink-200 bg-white">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                        <div>
                            <p className="text-sm text-ink-500">
                                <span className="font-semibold text-navy-900">CivicResolve</span> · Ministry of Verification
                            </p>
                            <p className="text-xs text-ink-400 mt-1">
                                A protocol demonstration on synthetic data. No real municipal records.
                            </p>
                        </div>
                        <div className="flex items-center gap-4 text-xs text-ink-500">
                            <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noopener" className="hover:text-navy-900 transition-colors">
                                API Docs
                            </a>
                            <span className="text-ink-300">·</span>
                            <a href="http://127.0.0.1:8000/openapi.json" target="_blank" rel="noopener" className="hover:text-navy-900 transition-colors">
                                OpenAPI
                            </a>
                            <span className="text-ink-300">·</span>
                            <span>v0.1.0</span>
                        </div>
                    </div>
                </div>
            </footer>
        </div>
    );
}