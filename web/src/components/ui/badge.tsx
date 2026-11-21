import { HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

type Variant =
    | "default"
    | "navy"
    | "bronze"
    | "success"
    | "warning"
    | "danger"
    | "info"
    | "outline";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
    variant?: Variant;
    size?: "sm" | "md";
    dot?: boolean;
}

const variants: Record<Variant, string> = {
    default: "bg-ink-100 text-ink-700 border-ink-200",
    navy: "bg-navy-900 text-cream-50 border-navy-800",
    bronze: "bg-bronze-500/10 text-bronze-600 border-bronze-500/30",
    success: "bg-sage-50 text-sage-700 border-sage-500/30",
    warning: "bg-amber-50 text-amber-700 border-amber-600/30",
    danger: "bg-burgundy-50 text-burgundy-700 border-burgundy-600/30",
    info: "bg-slate-100 text-slate-700 border-slate-300",
    outline: "bg-transparent text-ink-700 border-ink-300",
};

const sizes = {
    sm: "text-xs px-2 py-0.5",
    md: "text-sm px-2.5 py-1",
};

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
    ({ className, variant = "default", size = "sm", dot, children, ...props }, ref) => {
        return (
            <span
                ref={ref}
                className={cn(
                    "inline-flex items-center gap-1.5 font-medium rounded-sm border tracking-wide uppercase",
                    variants[variant],
                    sizes[size],
                    className
                )}
                {...props}
            >
                {dot && (
                    <span
                        className={cn(
                            "h-1.5 w-1.5 rounded-full flex-shrink-0",
                            variant === "success" && "bg-sage-600 gov-pulse",
                            variant === "warning" && "bg-amber-600 gov-pulse",
                            variant === "danger" && "bg-burgundy-600 gov-pulse",
                            variant === "info" && "bg-slate-500 gov-pulse",
                            variant === "navy" && "bg-bronze-400 gov-pulse",
                            variant === "bronze" && "bg-bronze-500 gov-pulse",
                            (variant === "default" || variant === "outline") && "bg-ink-400",
                        )}
                    />
                )}
                {children}
            </span>
        );
    }
);
Badge.displayName = "Badge";