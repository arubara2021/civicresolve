"use client";

import { useState, FormEvent } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Alert } from "@/components/ui/alert";
import { useActor } from "@/app/providers";
import { Upload, Camera, FileText, Loader2 } from "lucide-react";

interface ClosureFormProps {
    complaintId: string;
    onSubmit: (data: FormData) => Promise<void>;
}

export function ClosureForm({ complaintId, onSubmit }: ClosureFormProps) {
    const { actor } = useActor();
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function handleSubmit(e: FormEvent<HTMLFormElement>) {
        e.preventDefault();
        setIsSubmitting(true);
        setError(null);
        try {
            const formData = new FormData(e.currentTarget);
            await onSubmit(formData);
        } catch (err: any) {
            setError(err.message || "Submission failed");
        } finally {
            setIsSubmitting(false);
        }
    }

    return (
        <Card elevated className="gov-fade-in">
            <CardHeader className="bg-navy-900 border-b-0">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-bronze-500/20 rounded-sm flex items-center justify-center">
                        <Camera className="w-5 h-5 text-bronze-400" />
                    </div>
                    <div>
                        <CardTitle className="text-white">Submit Closure Evidence</CardTitle>
                        <p className="text-sm text-cream-100/70 mt-0.5">
                            The evidentiary standard was fixed at intake time
                        </p>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="p-6">
                <form onSubmit={handleSubmit} className="space-y-5">
                    {error && (
                        <Alert variant="error" title="Submission failed">
                            {error}
                        </Alert>
                    )}

                    <Input
                        name="officer_id"
                        label="Officer ID"
                        defaultValue={actor}
                        required
                        hint="Your official identifier"
                    />

                    <Textarea
                        name="remarks"
                        label="Work Performed"
                        placeholder="Describe the specific work completed at this site. Include measurements, materials used, and any relevant details."
                        required
                        minLength={10}
                        hint="Site-specific remarks — identical text across multiple tickets is flagged as bulk-closure"
                    />

                    <Input
                        name="work_order_reference"
                        label="Work Order Reference"
                        placeholder="e.g. WO/4471"
                        hint="Official work order number from your department"
                    />

                    <div className="space-y-1.5">
                        <label className="block text-sm font-medium text-ink-700 tracking-wide">
                            After Photograph <span className="text-burgundy-600">*</span>
                        </label>
                        <div className="relative">
                            <input
                                name="after_image"
                                type="file"
                                accept="image/*"
                                required
                                className="absolute inset-0 opacity-0 cursor-pointer z-10"
                            />
                            <div className="w-full h-24 bg-white border-2 border-dashed border-ink-300 rounded-sm flex items-center justify-center hover:border-bronze-500 hover:bg-cream-50 transition-colors">
                                <div className="text-center">
                                    <Upload className="w-5 h-5 text-ink-400 mx-auto mb-1" />
                                    <p className="text-sm text-ink-500">
                                        <span className="text-bronze-600 font-medium">Click to upload</span> or drag and drop
                                    </p>
                                    <p className="text-xs text-ink-400 mt-0.5">
                                        Close-up with GPS metadata enabled · JPEG, PNG, WebP
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="pt-4 border-t border-ink-100 flex items-center justify-between">
                        <p className="text-xs text-ink-500">
                            Compliant with: <span className="font-medium text-ink-700">{complaintId}</span>
                        </p>
                        <Button
                            type="submit"
                            variant="navy"
                            size="lg"
                            isLoading={isSubmitting}
                            icon={<FileText className="w-4 h-4" />}
                        >
                            {isSubmitting ? "Auditing..." : "Submit to Forensics"}
                        </Button>
                    </div>
                </form>
            </CardContent>
        </Card>
    );
}