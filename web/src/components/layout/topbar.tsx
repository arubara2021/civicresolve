"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useActor } from "@/app/providers";
import { NotificationBell } from "@/components/notify/notification-bell";
import { Shield, LayoutDashboard, FileText, ScrollText, Home, Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

const NAV = [
    { href: "/", label: "Home", icon: Home, match: (p: string) => p === "/" },
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, match: (p: string) => p.startsWith("/dashboard") },
    { href: "/report", label: "Report", icon: FileText, match: (p: string) => p.startsWith("/report") },
    { href: "/passport", label: "Passport", icon: ScrollText, match: (p: string) => p.startsWith("/passport") },
];

const ROLES: { id: string; role: "citizen" | "officer" | "admin" | "reviewer"; label: string }[] = [
    { id: "CIT-201", role: "citizen", label: "Citizen" },
    { id: "OFF-117", role: "officer", label: "Officer" },
    { id: "ADM-01", role: "admin", label: "Admin" },
    { id: "REV-01", role: "reviewer", label: "Reviewer" },
];

export function Topbar() {
    const pathname = usePathname();
    const { actor, role, setActor } = useActor();
    const [mobileOpen, setMobileOpen] = useState(false);

    return (
        <header className="sticky top-0 z-40 bg-white border-b border-ink-200">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div className="flex items-center justify-between h-16">
                    {/* Logo */}
                    <Link href="/" className="flex items-center gap-3 group">
                        <div className="w-9 h-9 bg-navy-900 rounded-sm flex items-center justify-center shadow-institutional group-hover:bg-navy-800 transition-colors">
                            <Shield className="w-5 h-5 text-bronze-400" strokeWidth={2.5} />
                        </div>
                        <div className="hidden sm:block">
                            <div className="font-serif text-lg font-semibold text-navy-900 leading-tight">
                                CivicResolve
                            </div>
                            <div className="text-[10px] uppercase tracking-[0.2em] text-ink-500 -mt-0.5">
                                Ministry of Verification
                            </div>
                        </div>
                    </Link>

                    {/* Desktop nav */}
                    <nav className="hidden md:flex items-center gap-1">
                        {NAV.map((item) => {
                            const active = item.match(pathname);
                            const Icon = item.icon;
                            return (
                                <Link
                                    key={item.href}
                                    href={item.href}
                                    className={cn(
                                        "flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-sm transition-colors",
                                        active
                                            ? "text-navy-900 bg-cream-100 gov-nav-active"
                                            : "text-ink-500 hover:text-navy-900 hover:bg-cream-50"
                                    )}
                                >
                                    <Icon className="w-4 h-4" />
                                    {item.label}
                                </Link>
                            );
                        })}
                    </nav>

                    {/* Right side: actor switcher + bell */}
                    <div className="flex items-center gap-3">
                        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-cream-50 border border-ink-200 rounded-sm">
                            <span className="text-xs text-ink-500 uppercase tracking-wider">Acting as</span>
                            <select
                                value={`${actor}|${role}`}
                                onChange={(e) => {
                                    const [id, r] = e.target.value.split("|");
                                    setActor(id, r as any);
                                }}
                                className="bg-transparent text-sm font-medium text-navy-900 focus:outline-none cursor-pointer"
                            >
                                {ROLES.map((r) => (
                                    <option key={r.id} value={`${r.id}|${r.role}`}>
                                        {r.label} ({r.id})
                                    </option>
                                ))}
                            </select>
                        </div>

                        <NotificationBell />

                        <button
                            className="md:hidden p-2 text-ink-700 hover:bg-cream-100 rounded-sm"
                            onClick={() => setMobileOpen(!mobileOpen)}
                            aria-label="Menu"
                        >
                            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
                        </button>
                    </div>
                </div>

                {/* Mobile nav */}
                {mobileOpen && (
                    <nav className="md:hidden py-3 border-t border-ink-100 gov-stagger">
                        {NAV.map((item) => {
                            const active = item.match(pathname);
                            const Icon = item.icon;
                            return (
                                <Link
                                    key={item.href}
                                    href={item.href}
                                    onClick={() => setMobileOpen(false)}
                                    className={cn(
                                        "flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-sm",
                                        active ? "text-navy-900 bg-cream-100" : "text-ink-700 hover:bg-cream-50"
                                    )}
                                >
                                    <Icon className="w-4 h-4" />
                                    {item.label}
                                </Link>
                            );
                        })}
                        <div className="mt-3 px-3 pt-3 border-t border-ink-100">
                            <div className="text-xs text-ink-500 uppercase tracking-wider mb-2">Acting as</div>
                            <div className="grid grid-cols-2 gap-1">
                                {ROLES.map((r) => (
                                    <button
                                        key={r.id}
                                        onClick={() => {
                                            setActor(r.id, r.role);
                                            setMobileOpen(false);
                                        }}
                                        className={cn(
                                            "px-3 py-1.5 text-xs font-medium rounded-sm border transition-colors",
                                            actor === r.id
                                                ? "bg-navy-900 text-white border-navy-900"
                                                : "bg-white text-ink-700 border-ink-200 hover:border-bronze-400"
                                        )}
                                    >
                                        {r.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </nav>
                )}
            </div>
        </header>
    );
}