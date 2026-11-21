"use client";
import { useEffect, useRef } from "react";
import { CivicSSEClient } from "@/lib/sse";

export interface UseSSEOptions {
    recipientId: string | null;
    enabled?: boolean;
    onEvent?: (eventType: string, data: any) => void;
    onOpen?: () => void;
}

export function useSSE({ recipientId, enabled = true, onEvent, onOpen }: UseSSEOptions) {
    const clientRef = useRef<CivicSSEClient | null>(null);
    const onEventRef = useRef(onEvent);
    const onOpenRef = useRef(onOpen);

    useEffect(() => {
        onEventRef.current = onEvent;
        onOpenRef.current = onOpen;
    }, [onEvent, onOpen]);

    useEffect(() => {
        if (!recipientId || !enabled) return;

        const client = new CivicSSEClient({
            recipientId,
            onEvent: (type, data) => onEventRef.current?.(type, data),
            onOpen: () => onOpenRef.current?.(),
        });
        clientRef.current = client;
        client.connect();

        return () => {
            client.disconnect();
            clientRef.current = null;
        };
    }, [recipientId, enabled]);

    return clientRef.current;
}