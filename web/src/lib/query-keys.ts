export const queryKeys = {
    complaints: {
        all: ["complaints"] as const,
        list: (filters?: { ward?: string; status?: string }) =>
            ["complaints", "list", filters] as const,
        detail: (id: string) => ["complaints", "detail", id] as const,
    },
    passport: {
        all: ["passport"] as const,
        detail: (assetId: string) => ["passport", "detail", assetId] as const,
        verify: (assetId: string) => ["passport", "verify", assetId] as const,
    },
    notifications: {
        all: ["notifications"] as const,
        list: (recipientId: string) => ["notifications", "list", recipientId] as const,
    },
} as const;