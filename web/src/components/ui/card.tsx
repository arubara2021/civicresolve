import { HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
    elevated?: boolean;
    hoverable?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
    ({ className, elevated, hoverable = true, ...props }, ref) => {
        return (
            <div
                ref={ref}
                className={cn(
                    "bg-white rounded-sm border border-ink-200",
                    elevated ? "shadow-institutional-lg" : "shadow-institutional",
                    hoverable && "transition-all duration-200 ease-institutional hover:shadow-institutional-lg hover:border-bronze-400 hover:-translate-y-0.5",
                    className
                )}
                {...props}
            />
        );
    }
);
Card.displayName = "Card";

export const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div
            ref={ref}
            className={cn(
                "px-6 py-5 border-b border-ink-100",
                className
            )}
            {...props}
        />
    )
);
CardHeader.displayName = "CardHeader";

export const CardTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(
    ({ className, ...props }, ref) => (
        <h3
            ref={ref}
            className={cn("font-serif text-lg font-semibold text-navy-900 tracking-tight", className)}
            {...props}
        />
    )
);
CardTitle.displayName = "CardTitle";

export const CardDescription = forwardRef<HTMLParagraphElement, HTMLAttributes<HTMLParagraphElement>>(
    ({ className, ...props }, ref) => (
        <p ref={ref} className={cn("text-sm text-ink-500 mt-1", className)} {...props} />
    )
);
CardDescription.displayName = "CardDescription";

export const CardContent = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div ref={ref} className={cn("p-6", className)} {...props} />
    )
);
CardContent.displayName = "CardContent";

export const CardFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div
            ref={ref}
            className={cn("px-6 py-4 bg-cream-50 border-t border-ink-100 rounded-b-sm", className)}
            {...props}
        />
    )
);
CardFooter.displayName = "CardFooter";