"use client";

import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
    Shield,
    FileText,
    Scale,
    Link2,
    ScrollText,
    AlertTriangle,
    CheckCircle2,
    XCircle,
    ArrowRight,
    Sparkles,
    Lock,
    Fingerprint,
} from "lucide-react";
import { api } from "@/lib/api";
import { useEffect, useState } from "react";

export default function HomePage() {
    const [stats, setStats] = useState({ total: 0, open: 0, resolved: 0 });

    useEffect(() => {
        api.listComplaints({ limit: 200 }).then((res) => {
            const open = res.items.filter((c: any) => c.status !== "Resolved").length;
            setStats({
                total: res.total,
                open,
                resolved: res.total - open,
            });
        }).catch(() => { });
    }, []);

    return (
        <AppShell>
            {/* HERO */}
            <section className="gov-hero relative">
                <div className="gov-grain absolute inset-0 opacity-40 pointer-events-none" />
                <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 lg:py-28">
                    <div className="max-w-3xl gov-fade-in">
                        <Badge variant="bronze" size="md" dot className="mb-6">
                            Evidence-Verified Civic Resolution
                        </Badge>
                        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-serif font-semibold text-white leading-[1.05] tracking-tight">
                            From complaint to <span className="text-bronze-300">verified closure</span> — with an evidence chain, not a dropdown.
                        </h1>
                        <p className="mt-6 text-lg text-cream-100/80 leading-relaxed max-w-2xl">
                            Every civic app can tell you a complaint was closed. CivicResolve can tell you whether
                            it was actually fixed — and it keeps that record permanently, per physical asset.
                        </p>
                        <div className="mt-10 flex flex-col sm:flex-row gap-3">
                            <Link href="/report">
                                <Button variant="secondary" size="lg" icon={<FileText className="w-4 h-4" />}>
                                    File a Complaint
                                </Button>
                            </Link>
                            <Link href="/dashboard">
                                <Button
                                    variant="outline"
                                    size="lg"
                                    className="!bg-transparent !text-white !border-cream-100/30 hover:!bg-white/10 hover:!border-cream-100/60"
                                    icon={<Shield className="w-4 h-4" />}
                                >
                                    Open Dashboard
                                </Button>
                            </Link>
                        </div>
                    </div>

                    {/* Stat strip */}
                    <div className="mt-16 grid grid-cols-3 gap-px bg-white/10 rounded-sm overflow-hidden gov-fade-in max-w-2xl">
                        {[
                            { label: "Complaints Filed", value: stats.total, icon: FileText },
                            { label: "Currently Active", value: stats.open, icon: AlertTriangle },
                            { label: "Verified Resolved", value: stats.resolved, icon: CheckCircle2 },
                        ].map((s, i) => {
                            const Icon = s.icon;
                            return (
                                <div
                                    key={s.label}
                                    className="bg-navy-800/50 backdrop-blur-sm px-6 py-5"
                                    style={{ animationDelay: `${i * 100}ms` }}
                                >
                                    <div className="flex items-center gap-2 text-cream-100/60 text-xs uppercase tracking-wider">
                                        <Icon className="w-3.5 h-3.5" />
                                        {s.label}
                                    </div>
                                    <div className="mt-2 font-serif text-3xl font-semibold text-white">
                                        {s.value}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </section>

            {/* THE PROBLEM */}
            <section className="py-20 bg-white border-b border-ink-200">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="max-w-3xl gov-fade-in">
                        <div className="gov-section-title">The Problem</div>
                        <h2 className="text-3xl sm:text-4xl font-serif font-semibold text-navy-900">
                            Closure is a status field,<br />not an evidentiary claim.
                        </h2>
                        <p className="mt-4 text-lg text-ink-700 leading-relaxed">
                            Gurugram, 2026: municipal officials uploaded AI-edited photographs and spoofed GPS
                            coordinates to close complaints never attended. Panchkula, 2026: six pothole complaints
                            closed with identical remarks — including identical typos — and identical photographs
                            that still showed damaged roads.
                        </p>
                        <p className="mt-4 text-lg text-ink-700 leading-relaxed">
                            Three failure modes, one root cause: <span className="font-semibold text-navy-900">a dropdown can be changed from a desk. A repair cannot.</span>
                        </p>
                    </div>
                </div>
            </section>

            {/* THE SIX LINKS */}
            <section className="py-20 bg-cream-50">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="max-w-2xl gov-fade-in">
                        <div className="gov-section-title">The Evidence Chain</div>
                        <h2 className="text-3xl sm:text-4xl font-serif font-semibold text-navy-900">
                            Six links. Every one must hold.
                        </h2>
                        <p className="mt-4 text-lg text-ink-700">
                            Before a ticket can display <Badge variant="success" size="md">Resolved</Badge>, it must
                            pass a forensically audited evidence chain. Each link is independently testable.
                        </p>
                    </div>

                    <div className="mt-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 gov-stagger">
                        {[
                            {
                                icon: Lock,
                                title: "L1 · Temporal",
                                desc: "EXIF capture timestamp vs complaint filing time vs plausible repair duration.",
                                verdict: "PASS",
                            },
                            {
                                icon: Fingerprint,
                                title: "L2 · Geospatial",
                                desc: "GPS distance to asset centroid within 50 m tolerance. Reported as claimed presence.",
                                verdict: "PASS",
                            },
                            {
                                icon: Sparkles,
                                title: "L3 · Visual Sufficiency",
                                desc: "Gemini vision audit: is the frame capable of evidencing the repair at all?",
                                verdict: "PASS",
                            },
                            {
                                icon: Scale,
                                title: "L4 · Claim-Evidence",
                                desc: "Every claim in the closure text reconciled against what is visible in the photograph.",
                                verdict: "PASS",
                            },
                            {
                                icon: Link2,
                                title: "L5 · Provenance & Reuse",
                                desc: "Metadata integrity, edit-software flags, and pHash scan against prior ward evidence.",
                                verdict: "PASS",
                            },
                            {
                                icon: ScrollText,
                                title: "L6 · Duplication",
                                desc: "Exact and TF-IDF cosine match against ward closure corpus — including shared typos.",
                                verdict: "PASS",
                            },
                        ].map((link, i) => {
                            const Icon = link.icon;
                            return (
                                <Card key={link.title} className="gov-card group">
                                    <CardContent className="p-6">
                                        <div className="flex items-start justify-between gap-3">
                                            <div className="w-11 h-11 bg-navy-900 rounded-sm flex items-center justify-center flex-shrink-0 group-hover:bg-bronze-500 transition-colors">
                                                <Icon className="w-5 h-5 text-bronze-300 group-hover:text-white transition-colors" />
                                            </div>
                                            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-sage-50 text-sage-700 border border-sage-500/30 rounded-sm">
                                                <CheckCircle2 className="w-3 h-3" />
                                                {link.verdict}
                                            </span>
                                        </div>
                                        <h3 className="mt-4 font-serif text-lg font-semibold text-navy-900">
                                            {link.title}
                                        </h3>
                                        <p className="mt-1.5 text-sm text-ink-500 leading-relaxed">{link.desc}</p>
                                    </CardContent>
                                </Card>
                            );
                        })}
                    </div>
                </div>
            </section>

            {/* PASSPORT SECTION */}
            <section className="py-20 bg-white border-t border-ink-200">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
                        <div className="gov-fade-in">
                            <div className="gov-section-title">The Civic Asset Passport</div>
                            <h2 className="text-3xl sm:text-4xl font-serif font-semibold text-navy-900">
                                The record is the asset, not the ticket.
                            </h2>
                            <p className="mt-4 text-lg text-ink-700 leading-relaxed">
                                Tickets are temporary. A pothole at a junction is permanent. Every complaint, closure
                                attempt, forensic report, citizen rejection and reviewer override is appended to the
                                asset's history.
                            </p>
                            <ul className="mt-6 space-y-3">
                                {[
                                    "One road segment 'resolved' 6 times and re-reported 7 → chronic failure, not bad luck",
                                    "One closure text reused across 6 assets → bulk-closure signature",
                                    "One officer ID with repeated deficiencies → training or audit need",
                                ].map((item, i) => (
                                    <li key={i} className="flex items-start gap-3 text-ink-700">
                                        <div className="w-1 h-1 rounded-full bg-bronze-500 mt-2 flex-shrink-0" />
                                        <span className="leading-relaxed">{item}</span>
                                    </li>
                                ))}
                            </ul>
                            <div className="mt-8">
                                <Link href="/passport/AST-0042">
                                    <Button variant="navy" icon={<ArrowRight className="w-4 h-4" />}>
                                        View Sample Passport
                                    </Button>
                                </Link>
                            </div>
                        </div>

                        {/* Passport visualization mock */}
                        <div className="gov-fade-in" style={{ animationDelay: "150ms" }}>
                            <div className="bg-navy-900 rounded-sm shadow-institutional-xl overflow-hidden">
                                <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
                                    <div>
                                        <div className="text-[10px] uppercase tracking-[0.2em] text-bronze-300">
                                            Asset Passport
                                        </div>
                                        <div className="font-serif text-white font-semibold">AST-0042 · WARD-12</div>
                                    </div>
                                    <Badge variant="success" dot>
                                        Chain Valid
                                    </Badge>
                                </div>
                                <div className="p-6 space-y-4">
                                    {[
                                        { type: "complaint_reported", actor: "CIT-201", time: "180 min ago" },
                                        { type: "triage_completed", actor: "System", time: "179 min ago" },
                                        { type: "priority_escalated", actor: "System", time: "179 min ago" },
                                        { type: "complaint_assigned", actor: "ADM-01", time: "178 min ago" },
                                        { type: "work_started", actor: "OFF-117", time: "165 min ago" },
                                        { type: "closure_attempt_submitted", actor: "OFF-117", time: "47 min ago" },
                                        { type: "forensic_report_issued", actor: "System", time: "47 min ago" },
                                    ].map((ev, i) => (
                                        <div
                                            key={i}
                                            className="relative pl-8 pb-4 last:pb-0"
                                            style={{ animationDelay: `${i * 80}ms` }}
                                        >
                                            {i < 6 && (
                                                <div className="absolute left-[11px] top-4 bottom-0 w-[1px] bg-white/10" />
                                            )}
                                            <div className="absolute left-0 top-1 w-[22px] h-[22px] rounded-full bg-bronze-500/20 border border-bronze-400 flex items-center justify-center">
                                                <div className="w-1.5 h-1.5 rounded-full bg-bronze-400" />
                                            </div>
                                            <div className="font-mono text-xs text-bronze-300">{ev.type}</div>
                                            <div className="flex items-center gap-2 mt-0.5 text-xs text-cream-100/60">
                                                <span>{ev.actor}</span>
                                                <span>·</span>
                                                <span>{ev.time}</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* FINAL CTA */}
            <section className="py-20 bg-cream-100 border-t border-ink-200">
                <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center gov-fade-in">
                    <h2 className="text-3xl sm:text-4xl font-serif font-semibold text-navy-900">
                        Ready to see the protocol in action?
                    </h2>
                    <p className="mt-4 text-lg text-ink-700">
                        File a complaint. Watch it triage in seconds. Submit a fake closure and watch the chain
                        reject it. Submit an honest closure and watch it resolve.
                    </p>
                    <div className="mt-8 flex flex-col sm:flex-row gap-3 justify-center">
                        <Link href="/report">
                            <Button variant="navy" size="lg" icon={<FileText className="w-4 h-4" />}>
                                Start the Demo
                            </Button>
                        </Link>
                        <Link href="/dashboard">
                            <Button variant="outline" size="lg" icon={<ArrowRight className="w-4 h-4" />}>
                                Explore Dashboard
                            </Button>
                        </Link>
                    </div>
                </div>
            </section>
        </AppShell>
    );
}