"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Alert } from "@/components/ui/alert";
import { useActor } from "@/app/providers";
import { api } from "@/lib/api";
import type { ComplaintSummary } from "@/lib/types";
import { FileText, MapPin, Upload, Sparkles, ArrowRight, CheckCircle2 } from "lucide-react";

export default function ReportPage() {
    const router = useRouter();
    const { actor } = useActor();
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [result, setResult] = useState<ComplaintSummary | null>(null);

    async function handleSubmit(e: FormEvent<HTMLFormElement>) {
        e.preventDefault();
        setIsSubmitting(true);
        setError(null);
        try {
            const formData = new FormData(e.currentTarget);
            const complaint = await api.submitComplaint(formData);
            setResult(complaint);
        } catch (err: any) {
            setError(err.message || "Submission failed");
            setIsSubmitting(false);
        }
    }

    return (
        <AppShell>
            <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
                <div className="mb-10 gov-fade-in">
                    <div className="gov-section-title">Citizen Report</div>
                    <h1 className="font-serif text-4xl font-semibold text-navy-900">
                        File a Civic Grievance
                    </h1>
                    <p className="mt-3 text-lg text-ink-700 max-w-2xl">
                        Gemini will triage your report in seconds and set the evidentiary standard
                        that any future closure must meet.
                    </p>
                </div>

                {result ? (
                    <div className="gov-fade-in space-y-6">
                        <Alert variant="success" title="Report Filed & Triaged">
                            Your complaint <span className="font-mono font-semibold">{result.complaint_id}</span>{" "}
                            has been classified and the asset record opened.
                        </Alert>

                        <Card elevated>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Sparkles className="w-5 h-5 text-bronze-500" />
                                    AI Triage Result
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <div className="text-xs uppercase tracking-wider text-ink-500 mb-1">Category</div>
                                        <div className="font-medium text-navy-900 capitalize">{result.category}</div>
                                    </div>
                                    <div>
                                        <div className="text-xs uppercase tracking-wider text-ink-500 mb-1">Urgency</div>
                                        <div className="font-medium text-navy-900">{result.urgency}</div>
                                    </div>
                                    <div>
                                        <div className="text-xs uppercase tracking-wider text-ink-500 mb-1">Department</div>
                                        <div className="font-medium text-navy-900">{result.department_label}</div>
                                    </div>
                                    <div>
                                        <div className="text-xs uppercase tracking-wider text-ink-500 mb-1">Priority Score</div>
                                        <div className="font-serif text-2xl font-semibold text-navy-900">
                                            {result.priority_score.toFixed(1)}
                                        </div>
                                    </div>
                                </div>

                                <div className="pt-4 border-t border-ink-100">
                                    <div className="text-xs uppercase tracking-wider text-ink-500 mb-2">
                                        Evidence Standard (Locked at Intake)
                                    </div>
                                    <div className="text-sm text-ink-700">
                                        Any future closure must satisfy: geo-tagged close-up of repaired zone,
                                        capture timestamp after work completion, work-order reference.
                                    </div>
                                </div>

                                <div className="pt-4 flex gap-3">
                                    <Button
                                        variant="navy"
                                        onClick={() => router.push(`/complaint/${result.complaint_id}`)}
                                        icon={<ArrowRight className="w-4 h-4" />}
                                    >
                                        View Complaint Detail
                                    </Button>
                                    <Button variant="outline" onClick={() => router.push("/dashboard")}>
                                        Go to Dashboard
                                    </Button>
                                </div>
                            </CardContent>
                        </Card>
                    </div>
                ) : (
                    <Card elevated className="gov-fade-in">
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <FileText className="w-5 h-5 text-navy-900" />
                                New Report
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <form onSubmit={handleSubmit} className="space-y-5">
                                {error && (
                                    <Alert variant="error" title="Submission failed">
                                        {error}
                                    </Alert>
                                )}

                                <Input
                                    name="title"
                                    label="Title"
                                    placeholder="Brief description of the issue"
                                    required
                                    minLength={5}
                                    maxLength={140}
                                />

                                <Textarea
                                    name="description"
                                    label="Description"
                                    placeholder="Describe the issue in detail — location, visible damage, risk to public"
                                    required
                                    minLength={10}
                                    maxLength={2000}
                                />

                                <div className="grid grid-cols-2 gap-4">
                                    <Input
                                        name="lat"
                                        label="Latitude"
                                        defaultValue="28.45952"
                                        required
                                        type="number"
                                        step="any"
                                    />
                                    <Input
                                        name="lng"
                                        label="Longitude"
                                        defaultValue="77.02663"
                                        required
                                        type="number"
                                        step="any"
                                    />
                                </div>

                                <Input name="ward" label="Ward" defaultValue="WARD-12" required />

                                <Input
                                    name="reporter_id"
                                    label="Your Citizen ID"
                                    defaultValue={actor}
                                    required
                                    hint="Your official civic identifier"
                                />

                                <Input
                                    name="category_hint"
                                    label="Category Hint (optional)"
                                    placeholder="e.g. pothole, garbage, streetlight"
                                />

                                <div className="space-y-1.5">
                                    <label className="block text-sm font-medium text-ink-700 tracking-wide">
                                        Photo (optional)
                                    </label>
                                    <div className="relative">
                                        <input
                                            name="image"
                                            type="file"
                                            accept="image/*"
                                            className="absolute inset-0 opacity-0 cursor-pointer z-10"
                                        />
                                        <div className="w-full h-20 bg-white border-2 border-dashed border-ink-300 rounded-sm flex items-center justify-center hover:border-bronze-500 hover:bg-cream-50 transition-colors">
                                            <div className="text-center">
                                                <Upload className="w-5 h-5 text-ink-400 mx-auto mb-1" />
                                                <p className="text-sm text-ink-500">Attach a photo</p>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div className="pt-4 border-t border-ink-100">
                                    <Button
                                        type="submit"
                                        variant="navy"
                                        size="lg"
                                        className="w-full"
                                        isLoading={isSubmitting}
                                        icon={<Sparkles className="w-4 h-4" />}
                                    >
                                        {isSubmitting ? "Triage in progress..." : "Submit & Triage with Gemini"}
                                    </Button>
                                    <p className="text-xs text-ink-500 mt-3 text-center">
                                        A structured AI call will classify, prioritize, and route your report.
                                    </p>
                                </div>
                            </form>
                        </CardContent>
                    </Card>
                )}
            </div>
        </AppShell>
    );
}