import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "CivicResolve — Verified Civic Grievance Resolution",
  description:
    "AI-assisted civic grievance intake with evidence-verified closure. The record is the asset, not the ticket.",
  keywords: ["civic", "grievance", "municipal", "forensics", "evidence", "AI"],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}