"use client";
import { ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "secondary" | "ghost" | "outline" | "destructive" | "navy";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: Variant;
    size?: Size;
    isLoading?: boolean;
    icon?: React.ReactNode;
}

const variants: Record<Variant, string> = {
    primary:
        "bg-navy-900 text-white hover:bg-navy-800 border border-navy-900 shadow-institutional hover:shadow-institutional-lg",
    navy:
        "bg-navy-800 text-white hover:bg-navy-700 border border-navy-700 shadow-institutional hover:shadow-institutional-lg",
    secondary:
        "bg-bronze-500 text-white hover:bg-bronze-600 border border-bronze-500 shadow-institutional hover:shadow-institutional-lg",
    outline:
        "bg-white text-ink-900 hover:bg-cream-100 border border-ink-300 hover:border-navy-700",
    ghost:
        "bg-transparent text-ink-700 hover:bg-cream-100 border border-transparent",
    destructive:
        "bg-burgundy-600 text-white hover:bg-burgundy-700 border border-burgundy-600 shadow-institutional",
};

const sizes: Record<Size, string> = {
    sm: "h-8 px-3 text-sm gap-1.5",
    md: "h-10 px-4 text-sm gap-2",
    lg: "h-12 px-6 text-base gap-2.5",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant = "primary", size = "md", isLoading, icon, children, disabled, ...props }, ref) => {
        return (
            <button
                ref={ref}
                disabled={disabled || isLoading}
                className={cn(
                    "inline-flex items-center justify-center rounded-sm font-medium tracking-wide",
                    "transition-all duration-200 ease-institutional",
                    "disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bronze-400 focus-visible:ring-offset-2 focus-visible:ring-offset-cream-50",
                    "active:scale-[0.98]",
                    variants[variant],
                    sizes[size],
                    className
                )}
                {...props}
            >
                {isLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                ) : icon ? (
                    <span className="flex-shrink-0">{icon}</span>
                ) : null}
                <span>{children}</span>
            </button>
        );
    }
);

Button.displayName = "Button";