"use client";

import { useState, useEffect } from "react";
import { Bell, Check } from "lucide-react";
import { useActor } from "@/app/providers";
import { useNotifications, useMarkRead } from "@/hooks/use-notifications";
import { useSSE } from "@/hooks/use-sse";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function NotificationBell() {
    const { actor } = useActor();
    const [open, setOpen] = useState(false);
    const [flash, setFlash] = useState(false);
    const qc = useQueryClient();

    const { data, isLoading } = useNotifications(actor);
    const markRead = useMarkRead();

    // Real-time updates via SSE
    useSSE({
        recipientId: actor,
        onEvent: () => {
            setFlash(true);
            setTimeout(() => setFlash(false), 2000);
            qc.invalidateQueries({ queryKey: queryKeys.notifications.list(actor) });
        },
    });

    const unread = data?.unread ?? 0;
    const items = data?.items ?? [];

    const handleMarkAll = async () => {
        if (items.length === 0) return;
        await markRead.mutateAsync({ recipientId: actor });
    };

    return (
        <div className="relative">
            <button
                onClick={() => setOpen(!open)}
                className={cn(
                    "relative p-2 rounded-sm transition-colors",
                    "hover:bg-cream-100 text-ink-700",
                    flash && "bg-bronze-400/20"
                )}
                aria-label="Notifications"
            >
                <Bell className="w-5 h-5" />
                {unread > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold text-white bg-burgundy-600 rounded-full gov-pulse">
                        {unread > 99 ? "99+" : unread}
                    </span>
                )}
            </button>

            {open && (
                <>
                    <div
                        className="fixed inset-0 z-30"
                        onClick={() => setOpen(false)}
                    />
                    <div className="absolute right-0 mt-2 w-96 bg-white border border-ink-200 rounded-sm shadow-institutional-xl z-40 animate-fade-in">
                        <div className="flex items-center justify-between px-4 py-3 border-b border-ink-100">
                            <div>
                                <h3 className="font-serif text-base font-semibold text-navy-900">
                                    Notifications
                                </h3>
                                <p className="text-xs text-ink-500 mt-0.5">
                                    {unread === 0 ? "All caught up" : `${unread} unread`}
                                </p>
                            </div>
                            {unread > 0 && (
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={handleMarkAll}
                                    isLoading={markRead.isPending}
                                    icon={<Check className="w-3.5 h-3.5" />}
                                >
                                    Mark all read
                                </Button>
                            )}
                        </div>
                        <div className="max-h-96 overflow-y-auto gov-scrollbar">
                            {isLoading ? (
                                <div className="p-6 text-center text-sm text-ink-500">Loading…</div>
                            ) : items.length === 0 ? (
                                <div className="p-8 text-center">
                                    <Bell className="w-8 h-8 text-ink-300 mx-auto mb-2" />
                                    <p className="text-sm text-ink-500">No notifications yet</p>
                                </div>
                            ) : (
                                <div className="gov-stagger">
                                    {items.map((n) => (
                                        <div
                                            key={n.id}
                                            className={cn(
                                                "px-4 py-3 border-b border-ink-100 last:border-0 hover:bg-cream-50 transition-colors",
                                                !n.read && "bg-bronze-400/5 border-l-2 border-l-bronze-500"
                                            )}
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center gap-2">
                                                        <h4 className={cn("text-sm", n.read ? "text-ink-700" : "font-semibold text-navy-900")}>
                                                            {n.title}
                                                        </h4>
                                                        {!n.read && (
                                                            <span className="w-1.5 h-1.5 rounded-full bg-bronze-500 gov-pulse flex-shrink-0" />
                                                        )}
                                                    </div>
                                                    <p className="text-xs text-ink-500 mt-0.5 line-clamp-2">{n.body}</p>
                                                    <p className="text-[10px] text-ink-400 mt-1 uppercase tracking-wider">
                                                        {formatRelativeTime(n.created_at)}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}