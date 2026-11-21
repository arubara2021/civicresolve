/**
 * Server-Sent Events client with automatic reconnect and Last-Event-ID replay.
 * The backend's SSE stream replays events newer than the cursor on reconnect,
 * so a dropped connection loses nothing.
 */
export type SSEHandler = (event: MessageEvent) => void;

export interface SSEOptions {
    recipientId: string;
    baseUrl?: string;
    onEvent?: (eventType: string, data: any) => void;
    onOpen?: () => void;
    onError?: (error: Event) => void;
    reconnectDelayMs?: number;
}

export class CivicSSEClient {
    private source: EventSource | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private closed = false;
    private lastEventId: string | null = null;

    constructor(private options: SSEOptions) { }

    connect() {
        if (this.closed) return;
        if (this.source) this.source.close();

        const base = this.options.baseUrl || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";
        const url = new URL(`${base}/stream`);
        url.searchParams.set("recipient_id", this.options.recipientId);
        if (this.lastEventId) {
            url.searchParams.set("last_event_id", this.lastEventId);
        }

        this.source = new EventSource(url.toString());

        this.source.onopen = () => {
            this.options.onOpen?.();
        };

        this.source.onerror = (e) => {
            this.options.onError?.(e);
            this.source?.close();
            this.source = null;
            if (!this.closed) {
                this.reconnectTimer = setTimeout(
                    () => this.connect(),
                    this.options.reconnectDelayMs ?? 3000
                );
            }
        };

        const knownEvents = [
            "complaint_reported",
            "triage_completed",
            "priority_escalated",
            "complaint_assigned",
            "work_started",
            "closure_attempt_submitted",
            "forensic_report_issued",
            "citizen_accepted",
            "citizen_rejected",
            "sla_expired",
            "escalated",
            "reviewer_override",
            "reopened",
        ];

        for (const eventType of knownEvents) {
            this.source.addEventListener(eventType, (e: MessageEvent) => {
                this.lastEventId = e.lastEventId || this.lastEventId;
                try {
                    const data = JSON.parse(e.data);
                    this.options.onEvent?.(eventType, data);
                } catch {
                    // ignore malformed
                }
            });
        }
    }

    disconnect() {
        this.closed = true;
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        if (this.source) {
            this.source.close();
            this.source = null;
        }
    }
}