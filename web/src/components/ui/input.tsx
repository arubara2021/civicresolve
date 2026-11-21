"use client";

import { InputHTMLAttributes, TextareaHTMLAttributes, forwardRef, useId } from "react";
import { cn } from "@/lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
    label?: string;
    error?: string;
    hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
    ({ className, label, error, hint, id, ...props }, ref) => {
        const autoId = useId();
        const inputId = id ?? autoId;
        return (
            <div className="space-y-1.5">
                {label && (
                    <label
                        htmlFor={inputId}
                        className="block text-sm font-medium text-ink-700 tracking-wide"
                    >
                        {label}
                    </label>
                )}
                <input
                    ref={ref}
                    id={inputId}
                    className={cn(
                        "w-full h-10 px-3 bg-white border rounded-sm text-sm text-ink-900",
                        "placeholder:text-ink-400",
                        "transition-all duration-200 ease-institutional",
                        "focus:outline-none focus:ring-2 focus:ring-bronze-400/40 focus:border-bronze-500",
                        error ? "border-burgundy-600 bg-burgundy-50/30" : "border-ink-300 hover:border-ink-400",
                        className
                    )}
                    {...props}
                />
                {hint && !error && <p className="text-xs text-ink-500">{hint}</p>}
                {error && <p className="text-xs text-burgundy-600 font-medium">{error}</p>}
            </div>
        );
    }
);
Input.displayName = "Input";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
    label?: string;
    error?: string;
    hint?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
    ({ className, label, error, hint, id, ...props }, ref) => {
        const autoId = useId();
        const inputId = id ?? autoId;
        return (
            <div className="space-y-1.5">
                {label && (
                    <label
                        htmlFor={inputId}
                        className="block text-sm font-medium text-ink-700 tracking-wide"
                    >
                        {label}
                    </label>
                )}
                <textarea
                    ref={ref}
                    id={inputId}
                    className={cn(
                        "w-full px-3 py-2.5 bg-white border rounded-sm text-sm text-ink-900 min-h-[100px] resize-y",
                        "placeholder:text-ink-400",
                        "transition-all duration-200 ease-institutional",
                        "focus:outline-none focus:ring-2 focus:ring-bronze-400/40 focus:border-bronze-500",
                        error ? "border-burgundy-600 bg-burgundy-50/30" : "border-ink-300 hover:border-ink-400",
                        className
                    )}
                    {...props}
                />
                {hint && !error && <p className="text-xs text-ink-500">{hint}</p>}
                {error && <p className="text-xs text-burgundy-600 font-medium">{error}</p>}
            </div>
        );
    }
);
Textarea.displayName = "Textarea";