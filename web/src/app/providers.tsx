"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, createContext, useContext, ReactNode } from "react";

interface ActorContextValue {
    actor: string;
    role: "citizen" | "officer" | "admin" | "reviewer";
    setActor: (id: string, role: "citizen" | "officer" | "admin" | "reviewer") => void;
}

const ActorContext = createContext<ActorContextValue | null>(null);

export function useActor() {
    const ctx = useContext(ActorContext);
    if (!ctx) throw new Error("useActor must be used within Providers");
    return ctx;
}

export function Providers({ children }: { children: ReactNode }) {
    const [queryClient] = useState(
        () =>
            new QueryClient({
                defaultOptions: {
                    queries: {
                        staleTime: 15_000,
                        retry: 1,
                        refetchOnWindowFocus: false,
                    },
                },
            })
    );

    const [actor, setActorState] = useState("CIT-201");
    const [role, setRoleState] = useState<"citizen" | "officer" | "admin" | "reviewer">("citizen");

    const setActor = (id: string, newRole: "citizen" | "officer" | "admin" | "reviewer") => {
        setActorState(id);
        setRoleState(newRole);
    };

    return (
        <QueryClientProvider client={queryClient}>
            <ActorContext.Provider value={{ actor, role, setActor }}>
                {children}
            </ActorContext.Provider>
        </QueryClientProvider>
    );
}