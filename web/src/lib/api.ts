import type { ComplaintSummary, ForensicReport, Notification, PassportEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

async function handleResponse<T>(res: Response): Promise<T> {
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
    }
    return res.json();
}

export const api = {
    async listComplaints(filters?: {
        ward?: string;
        status?: string;
        limit?: number;
    }): Promise<{ items: ComplaintSummary[]; total: number }> {
        const params = new URLSearchParams();
        if (filters?.ward) params.set("ward", filters.ward);
        if (filters?.status) params.set("status", filters.status);
        if (filters?.limit) params.set("limit", String(filters.limit));
        const res = await fetch(`${API_BASE}/complaints?${params}`);
        return handleResponse(res);
    },

    async getComplaint(id: string): Promise<{
        complaint: any;
        timeline: PassportEvent[];
        attempts: any[];
        decisions: any[];
    }> {
        const res = await fetch(`${API_BASE}/complaints/${id}`);
        return handleResponse(res);
    },

    async submitComplaint(data: FormData): Promise<ComplaintSummary> {
        const res = await fetch(`${API_BASE}/complaints`, {
            method: "POST",
            body: data,
        });
        return handleResponse(res);
    },

    async updateStatus(
        complaintId: string,
        payload: { actor_id: string; actor_type: string; action: string; assignee_department?: string }
    ): Promise<ComplaintSummary> {
        const res = await fetch(`${API_BASE}/complaints/${complaintId}/status`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        return handleResponse(res);
    },

    async submitClosure(complaintId: string, data: FormData): Promise<any> {
        const res = await fetch(`${API_BASE}/complaints/${complaintId}/closure-attempts`, {
            method: "POST",
            body: data,
        });
        return handleResponse(res);
    },

    async decide(
        attemptId: string,
        payload: { actor_id: string; decision: "accept" | "reject"; reason?: string }
    ): Promise<any> {
        const res = await fetch(`${API_BASE}/closure-attempts/${attemptId}/decision`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        return handleResponse(res);
    },

    async getPassport(assetId: string): Promise<{
        asset: any;
        timeline: PassportEvent[];
        chain_verification: any;
    }> {
        const res = await fetch(`${API_BASE}/assets/${assetId}/passport`);
        return handleResponse(res);
    },

    async verifyChain(assetId: string): Promise<{
        valid: boolean;
        events_checked: number;
        broken_seq?: number;
        reason?: string;
    }> {
        const res = await fetch(`${API_BASE}/assets/${assetId}/verify-chain`);
        return handleResponse(res);
    },

    async getNotifications(recipientId: string): Promise<{
        items: Notification[];
        unread: number;
    }> {
        const res = await fetch(`${API_BASE}/notifications?recipient_id=${recipientId}`);
        return handleResponse(res);
    },

    async markRead(recipientId: string, ids?: string[]): Promise<{ marked_read: number }> {
        const res = await fetch(`${API_BASE}/notifications/read`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ recipient_id: recipientId, notification_ids: ids }),
        });
        return handleResponse(res);
    },

    async resetDemo(): Promise<{ reset: boolean; asset_id: string }> {
        const res = await fetch(`${API_BASE}/demo/reset`, { method: "POST" });
        return handleResponse(res);
    },
};