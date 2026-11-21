# CivicResolve

**From complaint to verified closure — with an evidence chain, not a dropdown.**

An AI-powered civic grievance platform built on Google Gemini. Citizens report issues in seconds; Gemini classifies, prioritizes and routes them; departments resolve them by submitting an **evidence chain** that is forensically audited before the issue can ever display as `Resolved`.

> Every civic app can tell you a complaint was closed. CivicResolve can tell you **whether it was actually fixed** — and it keeps that record permanently, per physical asset.

**[Live Demo](https://your-deployed-url)** · **[GitHub](https://github.com/arubara2021/civicresolve)** · Built with **[Google Gemini](https://ai.google.dev/)** and **[Google Antigravity](https://antigravity.google/)**

---

## Table of contents

- [CivicResolve](#civicresolve)
  - [Table of contents](#table-of-contents)
  - [Why this exists](#why-this-exists)
  - [What it does](#what-it-does)
  - [Screenshots](#screenshots)
  - [Challenge compliance matrix](#challenge-compliance-matrix)
  - [The two differentiators](#the-two-differentiators)
    - [1. Civic Asset Passport — the record is the asset, not the ticket](#1-civic-asset-passport--the-record-is-the-asset-not-the-ticket)
    - [2. The evidentiary standard is fixed at intake — before anyone knows who repairs it](#2-the-evidentiary-standard-is-fixed-at-intake--before-anyone-knows-who-repairs-it)
  - [Architecture](#architecture)
  - [Gemini: exact roles and schemas](#gemini-exact-roles-and-schemas)
    - [Call #1 — Intake triage](#call-1--intake-triage)
    - [Call #2 — Visual forensics (Links 3 and 4 only)](#call-2--visual-forensics-links-3-and-4-only)
    - [Deterministic links (code, not AI)](#deterministic-links-code-not-ai)
  - [Closure policy engine](#closure-policy-engine)
  - [Status state machine](#status-state-machine)
  - [Data model](#data-model)
  - [API surface](#api-surface)
  - [Tech stack](#tech-stack)
  - [Setup](#setup)
  - [Evaluation approach](#evaluation-approach)
  - [Limitations and threat model](#limitations-and-threat-model)
  - [Real-world deployment path](#real-world-deployment-path)
  - [Scope discipline](#scope-discipline)
  - [Built with Google Antigravity](#built-with-google-antigravity)
  - [Sources](#sources)
  - [Team](#team)
  - [License](#license)

---

## Why this exists

Intake is a real problem: citizens don't know which department owns a pothole, can't describe it in administrable terms, and can't see what happened next. CivicResolve solves that with Gemini triage.

But there is a second failure, documented in 2026, that intake-only systems inherit:

- **Gurugram, July 2026.** The municipal corporation terminated two assistant sanitary inspectors. One edited original site photographs with AI tools and uploaded the fabricated "after" image to the grievance portal to obtain closure of a garbage complaint that was never attended. A second used a GPS-spoofing app (`Fly GPS`) to mark field attendance while at home. Detection came from the portal's software flagging **metadata tampering**, followed by a field inspection and a personal hearing. ([Indian Express](https://indianexpress.com/article/cities/delhi/gurgaon-mcg-officials-terminated-ai-fake-photos-garbage-cleanup-gps-spoofing-attendance-10767943/), [Business Today](https://www.businesstoday.in/technology/artificial-intelligence/story/think-ai-can-hide-the-truth-how-2-gurugram-municipal-workers-lost-their-jobs-over-digital-fraud-540865-2026-07-03))
- **Panchkula, October 2026.** Residents reported pothole complaints on Haryana's *Mhari Sadak* app closed with **identical remarks — including identical spelling errors — and identical photographs that still showed damaged roads.** Complainants noted the closure photos were broad street views, not close-ups of the repair. ([Times of India](https://timesofindia.indiatimes.com/city/chandigarh/panchkula-pothole-complaints-closed-but-roads-still-damaged/articleshow/135126878.cms))

Three failure modes, one root cause: **closure is a status field, not an evidentiary claim.** A dropdown can be changed from a desk. A repair cannot.

CivicResolve keeps the full intake workflow the challenge asks for, and adds the missing half: *resolution has to be proven, and the proof is contestable.*

**Design stance:** this protects honest field officers as much as it exposes dishonest ones. An officer who actually fixed the road gets a timestamped, geo-verified, citizen-accepted record that no one can dispute later. Today they get the same green tick as the person who faked it.

---

## What it does

**Citizen**
- Report an issue: title, description, location (map pin / GPS), category, optional photo.
- Gemini instantly returns category, urgency, public-impact score, and the responsible department — plus a plain-language summary of what was filed.
- Track it on a dashboard: `Reported → In Progress → Resolved`, with a live sub-status.
- When a department claims resolution, review the **Closure Forensics Report** and **Accept** or **Reject with a deficiency list**.

**Department / Admin**
- Triage queue sorted by computed priority (not arrival order), filterable by ward, category, department, urgency.
- Assign, update status, manage complaints.
- To close: submit closure evidence (after-photo, optional before/after pair, work-order reference, closure remarks). The system audits the chain and returns a per-link verdict.
- If the chain fails, get a **specific, actionable deficiency list** — not a vague rejection.

**Independent reviewer**
- Handles disputes, unresponsive citizens, and suspected malicious rejections. Every override requires a logged justification.

**Everyone**
- Open the **Civic Asset Passport**: the permanent history of one physical location across all complaints, departments, closure attempts, rejections and overrides.

---

## Screenshots

*(To be populated with application screenshots upon final deployment)*

| Screen | What it shows |
|---|---|
| **Citizen report form** | Citizen report form after Gemini triage — category, urgency, public-impact score, department, and the evidence standard that closure must later meet |
| **Admin triage queue** | Admin triage queue sorted by computed priority, with asset-history risk weighting visible on chronic-failure assets |
| **Closure forensics report** | Closure Forensics Report on a rejected closure — six evidentiary links, per-link verdicts, and the auto-generated deficiency list |
| **Citizen rejection** | Citizen adjudication screen — Accept / Reject decision with reason capture |
| **Verified resolution** | Verified closure — all links PASS, citizen acceptance logged, asset marked `Resolved · citizen-accepted` |
| **Asset passport** | Civic Asset Passport — hash-chained timeline of every complaint, closure attempt, rejection and override on a single physical asset |

---

## Challenge compliance matrix

| Expected feature | Status | Where |
|---|---|---|
| Citizen issue reporting (title, description, location, category, optional image) | ✅ | `/report` → `POST /api/complaints` |
| AI-powered classification (Gemini → category) | ✅ | `triage.py` → `category` |
| Priority detection (urgency **+ potential public impact**) | ✅ | `triage.py` → `urgency`, `public_impact`; `priority.py` → history-weighted score |
| Department recommendation | ✅ | `triage.py` → `department` + alternates + confidence |
| Issue tracking dashboard (`Reported`, `In Progress`, `Resolved`) | ✅ | `/dashboard` — canonical labels, verification sub-status beneath |
| Admin dashboard (review, update statuses, manage) | ✅ | `/admin` — assign, progress, bulk actions, closure submission |
| **Expected outcome:** working end-to-end web app, submission → AI triage → tracking → resolution | ✅ | Full end-to-end loop, runnable on a fresh clone |
| Google Gemini | ✅ | Two structured-output calls: intake triage + visual forensics |
| Google Antigravity | ✅ | Built in Antigravity; agent walkthroughs committed under `docs/antigravity/` |

**Status vocabulary is the challenge's vocabulary.** `Reported`, `In Progress`, `Resolved` are the primary states. Verification detail lives in a sub-status badge (`In Progress · pending verification`, `Resolved · citizen-accepted`). Nothing is renamed.

---

## The two differentiators

### 1. Civic Asset Passport — the record is the asset, not the ticket

Tickets are temporary. A pothole at a junction is permanent. Every complaint, closure attempt, forensic report, citizen rejection and reviewer override is appended to the **asset's** history.

This makes patterns visible that a ticket table structurally cannot show:

- one road segment "resolved" 6 times and re-reported 7 → **chronic failure**, not bad luck;
- one closure text reused across 6 assets in a ward → **bulk-closure signature**;
- one officer ID with a repeated deficiency pattern → **training or audit need**, surfaced at ward level.

The log is **append-only and hash-chained**: each event stores `prev_hash` and `sha256(prev_hash + canonical_json(payload))`. Edit any historical row and the chain breaks visibly. History is tamper-*evident*, not silently rewritable.

### 2. The evidentiary standard is fixed at intake — before anyone knows who repairs it

This is the load-bearing design decision. The intake Gemini call doesn't just classify; it emits:

- `defect_claim` — the specific physical condition being reported ("unfilled pothole ~40cm wide in the left wheel path"), and
- `evidence_required_for_closure` — the proof that will be demanded later (geo-tagged close-up of the repaired zone, timestamp after work completion, work-order reference).

The bar is set **at report time**, published to the citizen, and stored on the asset. It cannot be quietly lowered at closure time by whoever is closing the ticket. That single ordering removes the most common form of closure gaming: a plausible sentence attached to a weak photograph, judged against no pre-set standard.

**And the passport feeds the mandatory priority feature:**

```
priority_score = 0.45 * urgency_weight
              + 0.30 * public_impact_score
              + 0.25 * asset_history_risk

asset_history_risk = f(failed_closure_attempts, reopen_count, days_open, verified_repair_recency)

ESCALATE one urgency band if failed_closure_attempts >= 3 OR reopen_count >= 2
```

A repeatedly-failed repair outside a school is the highest public-impact case in the dataset — and only an asset-level record can see it. Priority detection is required by the challenge; the passport makes it actually intelligent.

---

## Architecture

```
Citizen UI ──┐
Admin UI  ───┼──> Flask API ──> SQLite (assets, complaints, attempts, events)
Reviewer  ───┘        │
                      ├──> Gemini call #1: INTAKE TRIAGE
                      │      category · urgency · public_impact · department
                      │      defect_claim · evidence_required_for_closure
                      │
                      ├──> DETERMINISTIC FORENSICS (no LLM)
                      │      L1 temporal · L2 geospatial · L5 provenance/reuse · L6 duplication
                      │
                      ├──> Gemini call #2: VISUAL FORENSICS
                      │      L3 evidentiary sufficiency · L4 claim–evidence reconciliation
                      │
                      └──> POLICY ENGINE (pure code)
                             chain_sufficient → state machine → citizen decision
```

**Hard rule: Gemini never decides closure.** It reports observations with reasons and may abstain. Deterministic checks are computed in code. The verdict is assembled by an auditable policy engine, and the final acceptance belongs to the citizen (or a logged reviewer override).

Why: an LLM asked to compute a timestamp delta or a GPS distance is slower, costlier and less reliable than three lines of Python — and un-auditable. Keeping arithmetic in code is what makes the report defensible.

---

## Gemini: exact roles and schemas

Two calls. `temperature=0`, structured output enforced via `response_schema`. Model set by env (`GEMINI_MODEL_TRIAGE`, `GEMINI_MODEL_FORENSICS`) — a fast Flash-class model for triage, the strongest vision-capable model your key supports for forensics.

### Call #1 — Intake triage

Input: title, description, category hint, coordinates, optional image, ward context.

```json
{
  "category": "pothole | garbage_overflow | streetlight_failure | water_leakage | road_damage | drainage | other",
  "category_confidence": 0.0,
  "urgency": "P1 | P2 | P3 | P4",
  "urgency_reason": "string",
  "public_impact": {
    "score": 0,
    "factors": ["school_within_100m", "arterial_road", "injury_risk", "sanitation_health_risk"],
    "affected_population": "low | medium | high"
  },
  "department": {
    "primary": "string",
    "confidence": 0.0,
    "alternates": ["string"]
  },
  "defect_claim": "the specific physical condition to be eliminated",
  "evidence_required_for_closure": [
    "geo_tagged_closeup_of_repaired_zone",
    "capture_timestamp_after_work_completion",
    "work_order_reference"
  ],
  "min_repair_minutes": 120,
  "citizen_summary": "plain language, <= 40 words",
  "safety_flags": ["open_manhole", "live_wire"]
}
```

`min_repair_minutes` is category-specific and clamped to a sane floor/ceiling in code — a physically implausible repair window is a *deficiency flag*, never an accusation on its own.

### Call #2 — Visual forensics (Links 3 and 4 only)

Input: before image, after image, `defect_claim`, department closure text, asset context. **The model is never asked "is this AI-generated?"** — a VLM asked that returns confident noise (see [threat model](#limitations-and-threat-model)).

```json
{
  "visual_sufficiency": {
    "verdict": "PASS | FAIL | INCONCLUSIVE",
    "framing": "close_up | mid_range | wide_street_view",
    "defect_zone_visible": true,
    "reason": "string, must reference what is visible in the frame"
  },
  "claim_evidence": {
    "verdict": "SUPPORTED | PARTIAL | CONTRADICTED | INCONCLUSIVE",
    "claims": [
      {
        "claim": "pothole filled with bitumen",
        "verdict": "CONTRADICTED",
        "observation": "patch visible but crack network remains across the repair zone"
      }
    ]
  },
  "observed_condition": "string",
  "additional_deficiencies": ["string"],
  "confidence": 0.0
}
```

Abstention is a first-class, rewarded outcome. Every verdict must cite a visible observation; unsupported verdicts are downgraded to `INCONCLUSIVE` by the policy engine.

### Deterministic links (code, not AI)

| Link | Implementation | Output |
|---|---|---|
| **L1 Temporal** | EXIF `DateTimeOriginal` vs `complaint.created_at` vs server upload time; delta < `min_repair_minutes`; identical closure timestamps across tickets | `PASS / FAIL / DEFICIENT` |
| **L2 Geospatial** | EXIF GPS → haversine distance to asset centroid, tolerance 50 m; absent tags → deficiency. Reported as **claimed presence**, not verified visit | `PASS / FAIL / DEFICIENT` |
| **L5 Provenance & reuse** | C2PA / Content Credentials manifest (present / absent / invalid signature); EXIF `Software` tags (Photoshop, Generative Fill, GIMP…); missing camera make/model; EXIF-vs-server time mismatch; embedded-thumbnail vs full-frame mismatch; **pHash of "after" vs "before" and vs the ward photo corpus** (Hamming ≤ 8 → reuse) | `PASS / FLAG / INCONCLUSIVE` |
| **L6 Duplication** | Normalized exact match **including shared typos** + TF-IDF/embedding cosine ≥ 0.92 against the ward closure corpus; returns matched ticket IDs | `PASS / MATCH` |

L5 is deliberately **provenance-and-reuse forensics**, not "AI-image detection". It mirrors how the real Gurugram case was actually caught — metadata tampering — and pHash reuse detection is the single highest-yield, lowest-cost signal for the Panchkula pattern.

---

## Closure policy engine

Pure, testable, no model in the loop:

```python
def chain_sufficient(report, asset):
    if report.provenance.reuse_detected:            return False   # reused photo
    if any(link.verdict == "FAIL" for link in report.required_links): return False
    if report.inconclusive_count > 1:               return False
    if not report.mandatory_evidence_present:       return False   # set at intake
    return all(link.verdict == "PASS" for link in report.required_links)
```

`required_links` and `mandatory_evidence_present` come from the asset's intake standard, per category. Output:

```json
{
  "chain_sufficient_for_closure": false,
  "links": { "temporal": "FAIL", "geospatial": "DEFICIENT", "visual_sufficiency": "FAIL",
             "claim_evidence": "CONTRADICTED", "provenance": "INCONCLUSIVE", "duplication": "MATCH" },
  "deficiency_list": [
    "Geo-tagged close-up of the repaired zone (current frame is a wide street view)",
    "Capture timestamp after work completion (submitted 47 min after report; minimum 120 min)",
    "Work-order reference",
    "Closure remarks identical to 6 other ward closures — submit site-specific remarks"
  ],
  "matched_tickets": ["WRD-1042", "WRD-1044", "WRD-1051", "WRD-1055", "WRD-1060", "WRD-1063"]
}
```

The report is **evidence, not judgement**. It goes to the citizen, who decides.

---

## Status state machine

Primary states are the challenge's states. Sub-states carry the integrity protocol.

```
Reported
   └─(admin assigns / starts work)──────────────> In Progress
                                                     │
                        (closure evidence submitted) ├─> In Progress · pending verification
                                                     │        │
                                     chain FAIL ─────┘        └─ chain PASS ─> awaiting citizen
                                                                                   │
        citizen REJECT ──> In Progress · disputed <───────────────────────────────┤
        citizen ACCEPT ──> Resolved · citizen-accepted <──────────────────────────┤
        citizen SILENT (SLA) ──> In Progress · escalated ──> reviewer decision    │
                                                                                   │
        Resolved ──(re-report within 30 days)──> In Progress · reopened ──────────┘
```

**Rules that close the obvious holes:**

| Hole | Rule |
|---|---|
| Citizen never responds → ticket stuck forever | SLA timer (72 h prod / 60 s demo) → **independent reviewer**, never auto-close, never auto-resolve |
| Citizen rejects a genuinely good repair (extortion, grudge) | `chain PASS + citizen REJECT` → reviewer adjudicates; override requires logged justification |
| 40 people report one pothole — who accepts? | Reporter holds acceptance; multi-reporter assets require a **quorum of 2 nearby verified reporters**, else reviewer |
| Admin marks `Resolved` from a dropdown | Not exposed. `Resolved` is reachable only via citizen acceptance or logged reviewer override |
| Failed closure silently vanishes | Every attempt is appended to the asset passport, hash-chained, publicly visible |
| Retry spam | Attempt counter; ≥3 failed attempts auto-escalates urgency and notifies ward supervisor |
| Officer doxxing / defamation | Public passport shows **officer IDs and ward-level attribution**, never names. Named attribution is role-gated to reviewers |

---

## Data model

```
assets            id, type, geo_lat, geo_lng, radius_m, ward, normalized_label,
                  defect_claim, evidence_standard_json, created_at
complaints        id, asset_id, reporter_id, title, description, category, urgency,
                  public_impact, department, priority_score, status, sub_status,
                  reopen_count, created_at, sla_deadline
closure_attempts  id, complaint_id, officer_id, remarks, work_order_ref,
                  submitted_at, chain_sufficient, forensic_report_json
evidence_files    id, attempt_id, kind (before|after), storage_path, phash,
                  exif_json, c2pa_status, server_received_at
decisions         id, attempt_id, actor_type (citizen|reviewer), actor_id,
                  decision, reason, created_at
events            id, asset_id, seq, type, payload_json, prev_hash, event_hash
```

`events` is append-only. No UPDATE or DELETE path exists in the codebase.

---

## API surface

```
POST   /api/complaints                      create + Gemini triage
GET    /api/complaints?ward=&status=&dept=   list / filter
GET    /api/complaints/:id                   detail + timeline
PATCH  /api/complaints/:id/status            admin: Reported → In Progress, assign
POST   /api/complaints/:id/closure-attempts  submit evidence → forensics run
POST   /api/closure-attempts/:id/decision    citizen accept / reject (+reason)
POST   /api/escalations/:id/review           reviewer override (+justification)
POST   /api/complaints/:id/reopen            re-report → asset history risk ↑
GET    /api/assets/:id/passport              full hash-chained history
GET    /api/assets/:id/verify-chain          recompute hash chain integrity
GET    /api/dashboard                        citizen + admin views
```

---

## Tech stack

- **Frontend:** Next.js + Tailwind + shadcn/ui, Leaflet for asset maps
- **Backend:** Flask (SQLAlchemy), pure-Python policy engine
- **DB:** SQLite — zero setup, ships with seeded demo data
- **AI:** Google Gemini via `google-genai`, structured output, `temperature=0`
- **Forensics:** `Pillow`, `exifread`/`piexif`, `ImageHash` (pHash/dHash), `c2pa-python`, `scikit-learn` (TF-IDF cosine)
- **Built in:** Google Antigravity

---

## Setup

```bash
git clone https://github.com/arubara2021/civicresolve
cd civicresolve

# backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # add GEMINI_API_KEY
flask --app app db-init
python seed.py            # synthetic demo ward: 1 asset, 7 complaints, 6 reused closure texts

# frontend
cd web && npm install && npm run dev
```

```env
GEMINI_API_KEY=...
GEMINI_MODEL_TRIAGE=gemini-2.5-flash
GEMINI_MODEL_FORENSICS=<strongest vision model your key supports>
DEMO_SLA_SECONDS=60
MIN_REPAIR_MINUTES_DEFAULT=120
GEO_TOLERANCE_METERS=50
PHASH_HAMMING_THRESHOLD=8
DUP_TEXT_COSINE_THRESHOLD=0.92
```

> **All seeded data is synthetic.** Wards, assets, officer IDs and photographs are fabricated for demonstration and labelled as such in the UI. No real municipal records, no real officials.

---

## Evaluation approach

The system is designed so that the *cost of the system* — falsely accusing an honest officer — is treated as a first-class metric, not an afterthought. The eval harness (`eval/run.py`) uses a labelled set of synthetic closure attempts across six classes: honest, wide-angle-only, stale-photo, reused-photo, edited-photo, and overstated-remarks.

The metrics the harness is built to report:

| Metric | Why it matters |
|---|---|
| False-positive rate on honest closures | The real cost of the system. Target ≤ 10%. |
| Recall per fraud class | Which failure modes are actually caught, and which are missed. |
| Abstention rate | How often the model correctly says `INCONCLUSIVE` instead of guessing. |
| Triage category accuracy vs human labels | Quality of the mandatory Gemini classification feature. |
| Department routing accuracy | Quality of the mandatory Gemini department recommendation feature. |
| p95 forensics latency / cost per closure | Operational viability of the audit step. |

The design deliberately prioritizes **abstention over false accusation**: `INCONCLUSIVE` is a rewarded outcome when the evidence genuinely doesn't support a verdict, and unsupported verdicts from the model are downgraded to `INCONCLUSIVE` by the policy engine before they ever reach a citizen.

---

## Limitations and threat model

Stated plainly, because a security claim you can't defend is worse than no claim.

- **We raise the cost of faking closure; we do not make it impossible.** Unilateral closure remains possible *outside* this system — a municipality can always close a ticket in its own portal. What we guarantee is that inside CivicResolve, closure leaves a permanent, contestable, evidence-backed trace.
- **EXIF is strippable and spoofable.** Most upload pipelines and messaging apps strip metadata. Mitigation: in-app capture with server-side receive time; missing metadata is a **deficiency**, not proof of fraud.
- **Mock-GPS apps are trivially available** — the second Gurugram case used one. A geotag is therefore reported as **claimed presence**, never verified attendance. Real presence verification needs device attestation or carrier/network corroboration: out of scope.
- **We do not claim to detect AI-generated images by looking at them.** SynthID verification is a consumer flow in the Gemini app / Detector portal with daily quotas, not a backend API; it only identifies content made or edited by Google's AI tools; and Google explicitly notes that **small edits may not carry a detectable watermark** — precisely the Gurugram case, a real photo edited. ([Google](https://support.google.com/gemini/answer/16722517)) So L5 uses provenance, metadata integrity and perceptual-hash reuse, and defaults to `INCONCLUSIVE`.
- **VLMs can misjudge fine repair quality.** Hence: verdicts must cite visible observations, abstention is allowed, the model never issues the closure decision, and a human always holds acceptance or override.
- **A private app cannot remove a statutory power.** Closure authority in Indian municipal systems is vested in the ULB. CivicResolve is deployable as a verification layer, not as a replacement of record.
- **Privacy:** public views expose officer IDs and ward aggregates only. Faces and plates blurred on ingest. Named attribution is reviewer-gated and logged.

---

## Real-world deployment path

**Ships today, no legal change required** — anywhere a single operator owns the workflow and can mandate verified sign-off: residential townships, university campuses, hospitals, industrial parks, facility-management firms. Same primitive, real buyer, immediate value: **verified field-service closeout / SLA proof.** That is a global market, not a niche civic app.

**Public municipal adoption** — realistically an internal QA and audit overlay, sold on three incentives:

1. protects honest officers with dispute-proof records of their own work;
2. cuts reopen volume and repeat truck rolls (a fake closure costs a second dispatch);
3. produces audit-ready evidence for oversight bodies.

**Known blockers, stated honestly:** statutory closure authority sits with the ULB; there is no open API into existing portals such as *Mhari Sadak* or CPGRAMS, so integration is the real bottleneck — not the AI; and the buyer is the party being constrained, which is why the pitch must lead with officer protection and cost savings.

**This submission is a working protocol demonstration on synthetic data, not a deployed municipal system.** That is a deliberate scope choice, and the adoption path above is the plan.

---

## Scope discipline

**Built:** intake + triage, priority with history risk, both dashboards, asset passport with hash-chained log, four forensic links, pHash reuse, deficiency lists, citizen acceptance, reviewer override, SLA escalation, reopen loop, eval harness.

**Deliberately not built:** GPS-trace analysis, generative-image detection, multi-city analytics, SSO/RBAC beyond three demo roles, native mobile app, live portal integration.

**Next:** in-app capture with device attestation → C2PA-signed capture → quorum verification at scale → integration adapters for existing portals → multilingual voice reporting.

---

## Built with Google Antigravity

Developed in Google Antigravity using agent-assisted implementation. Agent walkthroughs, task plans and verification artifacts are committed under `docs/antigravity/` — including the agent-generated test run for the closure policy engine.

---

## Sources

- Indian Express — *AI to fake clean-ups, GPS to skip work: Two Gurgaon civic officials fired*, 2 July 2026. https://indianexpress.com/article/cities/delhi/gurgaon-mcg-officials-terminated-ai-fake-photos-garbage-cleanup-gps-spoofing-attendance-10767943/
- Business Today — *How 2 Gurugram municipal workers lost their jobs over digital fraud*, 3 July 2026. https://www.businesstoday.in/technology/artificial-intelligence/story/think-ai-can-hide-the-truth-how-2-gurugram-municipal-workers-lost-their-jobs-over-digital-fraud-540865-2026-07-03
- Times of India — *Panchkula pothole complaints closed but roads still damaged*, 23 October 2026. https://timesofindia.indiatimes.com/city/chandigarh/panchkula-pothole-complaints-closed-but-roads-still-damaged/articleshow/135126878.cms
- Google — *Verify AI-generated images, videos and audio* (SynthID scope, quotas, small-edit limitation). https://support.google.com/gemini/answer/16722517

---

## Team

Arun — [@arubara2021](https://github.com/arubara2021)

## License

MIT