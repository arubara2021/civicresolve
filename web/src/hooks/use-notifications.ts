"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export function useNotifications(recipientId: string | null, enabled = true) {
    return useQuery({
        queryKey: queryKeys.notifications.list(recipientId || ""),
        queryFn: () => api.getNotifications(recipientId!),
        enabled: !!recipientId && enabled,
        refetchInterval: 30_000,
    });
}

export function useUnreadCount(recipientId: string | null) {
    const { data } = useNotifications(recipientId);
    return data?.unread ?? 0;
}

export function useMarkRead() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ recipientId, ids }: { recipientId: string; ids?: string[] }) =>
            api.markRead(recipientId, ids),
        onSuccess: (_, { recipientId }) => {
            qc.invalidateQueries({ queryKey: queryKeys.notifications.list(recipientId) });
        },
    });
}