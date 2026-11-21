import { HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";

type Variant = "info" | "success" | "warning" | "error";

interface AlertProps extends HTMLAttributes<HTMLDivElement> {
    variant?: Variant;
    title?: string;
    dismissible?: boolean;
    onDismiss?: () => void;
}

const variants = {
    info: {
        container: "bg-slate-100 border-slate-300 text-slate-700",
        icon: <Info className="h-5 w-5 text-slate-600 flex-shrink-0" />,
    },
    success: {
        container: "bg-sage-50 border-sage-500/30 text-sage-700",
        icon: <CheckCircle2 className="h-5 w-5 text-sage-600 flex-shrink-0" />,
    },
    warning: {
        container: "bg-amber-50 border-amber-600/30 text-amber-700",
        icon: <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0" />,
    },
    error: {
        container: "bg-burgundy-50 border-burgundy-600/30 text-burgundy-700",
        icon: <XCircle className="h-5 w-5 text-burgundy-600 flex-shrink-0" />,
    },
};

export const Alert = forwardRef<HTMLDivElement, AlertProps>(
    ({ className, variant = "info", title, children, dismissible, onDismiss, ...props }, ref) => {
        const v = variants[variant];
        return (
            <div
                ref={ref}
                className={cn(
                    "relative flex gap-3 p-4 border rounded-sm animate-fade-in",
                    v.container,
                    className
                )}
                role="alert"
                {...props}
            >
                <div className="pt-0.5">{v.icon}</div>
                <div className="flex-1 min-w-0">
                    {title && (
                        <h4 className="font-serif font-medium text-base mb-1">{title}</h4>
                    )}
                    <div className="text-sm leading-relaxed">{children}</div>
                </div>
                {dismissible && (
                    <button
                        onClick={onDismiss}
                        className="flex-shrink-0 p-1 hover:bg-black/5 rounded-sm transition-colors"
                        aria-label="Dismiss"
                    >
                        <X className="h-4 w-4" />
                    </button>
                )}
            </div>
        );
    }
);
Alert.displayName = "Alert";