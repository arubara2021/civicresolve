"use client";

import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, MapPin, ScrollText } from "lucide-react";

interface AssetRow {
    asset_id: string;
    ward: string;
    reports: number;
    latest_title: string;
}

export default function PassportIndexPage() {
    const { data } = useQuery({
        queryKey: queryKeys.complaints.list({}),
        queryFn: () => api.listComplaints({ limit: 200 }),
    });

    const assets: AssetRow[] = (() => {
        const map = new Map<string, AssetRow>();
        for (const c of data?.items ?? []) {
            const existing = map.get(c.asset_id);
            if (existing) existing.reports += 1;
            else
                map.set(c.asset_id, {
                    asset_id: c.asset_id,
                    ward: c.ward,
                    reports: 1,
                    latest_title: c.title,
                });
        }
        return [...map.values()].sort((a, b) => b.reports - a.reports);
    })();

    return (
        <AppShell>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
                <div className="gov-fade-in mb-8">
                    <div className="gov-section-title">Civic Asset Passport</div>
                    <h1 className="font-serif text-4xl font-semibold text-navy-900">Physical Assets</h1>
                    <p className="mt-2 text-ink-700 max-w-2xl">
                        The passport is permanent. Complaints, closure attempts, rejections and overrides
                        accumulate on the location, not on the ticket.
                    </p>
                </div>

                {assets.length === 0 ? (
                    <Card className="gov-fade-in">
                        <CardContent className="p-10 text-center">
                            <ScrollText className="w-10 h-10 text-ink-300 mx-auto mb-3" />
                            <p className="text-ink-700">No assets recorded yet.</p>
                            <p className="text-sm text-ink-500 mt-1">
                                File a report, or open the seeded demo asset below.
                            </p>
                            <div className="mt-5">
                                <Link href="/passport/AST-0042">
                                    <span className="inline-flex items-center gap-2 px-4 py-2 bg-navy-900 text-white rounded-sm text-sm font-medium hover:bg-navy-800 transition-colors">
                                        Open AST-0042 <ArrowRight className="w-4 h-4" />
                                    </span>
                                </Link>
                            </div>
                        </CardContent>
                    </Card>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 gov-stagger">
                        {assets.map((a) => (
                            <Link key={a.asset_id} href={`/passport/${a.asset_id}`} className="block group">
                                <Card hoverable className="h-full">
                                    <CardContent className="p-5">
                                        <div className="flex items-start justify-between gap-3">
                                            <div className="w-10 h-10 bg-navy-900 rounded-sm flex items-center justify-center flex-shrink-0 group-hover:bg-bronze-500 transition-colors">
                                                <ScrollText className="w-5 h-5 text-bronze-300 group-hover:text-white transition-colors" />
                                            </div>
                                            <Badge variant="bronze">{a.reports} report{a.reports !== 1 ? "s" : ""}</Badge>
                                        </div>
                                        <h3 className="mt-3 font-serif text-lg font-semibold text-navy-900 font-mono">
                                            {a.asset_id}
                                        </h3>
                                        <p className="text-sm text-ink-500 mt-1 line-clamp-2">{a.latest_title}</p>
                                        <p className="mt-3 flex items-center gap-1 text-xs text-ink-500">
                                            <MapPin className="w-3 h-3" /> {a.ward}
                                        </p>
                                    </CardContent>
                                </Card>
                            </Link>
                        ))}
                    </div>
                )}
            </div>
        </AppShell>
    );
}