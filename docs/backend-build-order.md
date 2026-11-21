# CivicResolve — Backend Build Order

RULES
- One file per step. Write it, run it, test it, then move on.
- Every phase ends at a CHECKPOINT that must pass before the next phase starts.
- Backend only. No frontend until Phase 12 passes.
- domain/ stays pure: no DB, no network, no file I/O. It is 100% unit-testable.
- Gemini never computes a verdict. policy.py does. Gemini never sets a status.

---

## PHASE 0 — Runnable skeleton

01. backend/requirements.txt
    Pinned deps: fastapi, uvicorn, pydantic v2, pydantic-settings, sqlalchemy 2,
    aiosqlite, google-genai, structlog, tenacity, pillow, exifread, piexif,
    imagehash, scikit-learn, sse-starlette, apscheduler, python-multipart, pytest.

02. backend/pyproject.toml
    Ruff + pytest config. Line length, async mode, test paths.

03. backend/.env.example
    The env contract. Every threshold lives here, nothing hardcoded later.

04. backend/app/core/config.py
    pydantic-settings Settings class. Model names, SLA seconds, geo tolerance,
    min repair minutes, pHash threshold, cosine threshold, quota caps.

05. backend/app/core/logging.py
    structlog JSON logs. trace_id in a contextvar so every log line is joinable.

06. backend/app/core/errors.py
    AppError hierarchy + stable codes. Global handlers emitting RFC 9457
    Problem Details with trace_id and retryable flag.

07. backend/app/core/ids.py
    Human-readable ID generators: WRD-1071, AST-0042, ATT-0007, EVT-000043.

08. backend/app/core/middleware.py
    trace_id injection, request timing header, GZip compression.

09. backend/app/main.py
    App factory. Wires logging, errors, middleware. Exposes /healthz and /readyz.

    CHECKPOINT 0: uvicorn boots. /healthz returns 200. A deliberately raised
    AppError returns the correct JSON envelope with a trace_id.

---

## PHASE 1 — Pure domain logic (no server, no DB)

10. backend/app/domain/enums.py
    Status (Reported/In Progress/Resolved), SubStatus, Urgency P1-P4, Category,
    LinkVerdict, ActorType, EventType, Department. Single source of truth.

11. backend/app/domain/schemas.py
    Pydantic contracts: TriageResult, PublicImpact, DepartmentRec, LinkResult,
    ForensicReport, ClosureSubmit, DecisionIn, PassportEvent. Written before
    models so the agent layer can bind response_schema to them directly.

12. backend/app/domain/priority.py
    Pure function: 0.45*urgency + 0.30*impact + 0.25*history_risk.
    Escalation rule: reopens >= 2 or failed closures >= 3 bumps one band.

13. backend/tests/test_priority.py
    Asserts the worked example: 79.9 with history, 54.9 without. P2 -> P1.

14. backend/app/domain/state_machine.py
    Legal transition table + guard function. Encodes the hard rule: Resolved
    is reachable ONLY via citizen acceptance or logged reviewer override.

15. backend/tests/test_state_machine.py
    Asserts admin cannot jump In Progress -> Resolved. Asserts every illegal
    transition raises. This file is the protocol's safety net.

16. backend/app/domain/policy.py
    chain_sufficient(). Short-circuits on reuse, any FAIL, >1 INCONCLUSIVE,
    or missing mandatory evidence. No model call, no I/O, deterministic.

17. backend/tests/test_policy.py
    Act 3 inputs -> False. Act 5 inputs -> True. Branch coverage 100%.

    CHECKPOINT 1: pytest passes with zero infrastructure. The three numbers
    from the worked example are now executable assertions.

---

## PHASE 2 — Persistence and the tamper-evident log

18. backend/app/domain/models.py
    SQLAlchemy 2.0 tables: assets, complaints, closure_attempts, evidence_files,
    decisions, events, notifications. Indexes on (asset_id, status) and (ward, created_at).

19. backend/app/core/db.py
    Async engine, SQLite WAL pragma, session factory, create_all, dependency.

20. backend/app/modules/assets/hash_chain.py
    canonical_json + sha256(prev_hash + payload). append_event() and
    verify_chain(). No UPDATE or DELETE path exists anywhere.

21. backend/tests/test_hash_chain.py
    Append 5 events, verify passes. Mutate event 2's payload, verify fails
    and reports the exact broken sequence number.

22. backend/app/core/lifespan.py
    Startup: create tables, idempotent seed hook, start APScheduler.
    Shutdown: drain scheduler, close engine.

    CHECKPOINT 2: DB file created on boot. Hash chain detects tampering.

---

## PHASE 3 — Storage and deterministic tools (still no AI)

23. backend/app/storage/base.py
    StoragePort protocol: save, read, thumbnail. Local now, S3/R2 later.

24. backend/app/storage/local.py
    Content-addressed writes (sha256 filename = free dedup). Server-side
    thumbnails. Original file preserved untouched for EXIF forensics.

25. backend/app/tools/exif_tool.py
    Safe EXIF extraction: DateTimeOriginal, GPS, Make, Model, Software,
    thumbnail mismatch. Never raises on a corrupt file; returns absence.

26. backend/app/tools/geo_tool.py
    Haversine distance in metres. Pure math, no dependency.

27. backend/app/tools/phash_tool.py
    pHash/dHash compute + BK-tree index for Hamming nearest-neighbour lookup
    instead of scanning the whole ward corpus.

28. backend/app/tools/dup_text_tool.py
    Normalize (case, punctuation, whitespace preserved typos) + TF-IDF cosine.
    Cached ward matrix, invalidated on new closure.

29. backend/app/tools/asset_history.py
    Prior closures, reopen count, failed attempts, verified-repair recency.
    Feeds priority.py's history_risk.

30. backend/tests/test_forensics.py  (part 1 — tools only)
    Asserts 5.3 m for the good photo, Hamming 2 for the reused photo,
    cosine 1.00 for the "motarable" remark across 6 tickets.

    CHECKPOINT 3: every deterministic number from the worked example reproduces.

---

## PHASE 4 — Agent layer (swappable runtime)

31. backend/app/agents/prompts.py
    Triage prompt and Auditor prompt. Auditor is forbidden from deciding
    closure and forbidden from guessing whether an image is AI-generated.
    Abstention is explicitly rewarded.

32. backend/app/agents/gemini_client.py
    Async google-genai wrapper. Hard timeouts, tenacity backoff on 429/5xx,
    circuit breaker, daily quota counter, fallback model.

33. backend/app/agents/ports.py
    TriageAgent and AuditorAgent Protocols. Both return the same Pydantic
    models regardless of runtime. This is the swap seam.

34. backend/app/agents/gemini_direct.py
    Default runtime. One structured call each, temperature 0,
    response_schema bound to TriageResult / AuditorResult.

35. backend/app/agents/registry.py
    AGENT_RUNTIME=direct|adk|langgraph selects the implementation. Nothing
    else in the codebase changes when you swap.

    CHECKPOINT 4: a real Gemini call returns a valid TriageResult. Pull the
    network cable: triage degrades gracefully, never crashes, never fails open.

---

## PHASE 5 — Intake (required features 1-4 go green)

36. backend/app/modules/assets/service.py
    Match a report to an existing asset by geo radius, or create a new one.
    Locks defect_claim and evidence_required_for_closure at intake time.

37. backend/app/modules/intake/service.py
    Orchestrates: validate -> match asset -> Gemini triage -> compute priority
    -> persist complaint -> append event -> write outbox row.

38. backend/app/modules/intake/router.py
    POST /api/complaints. Multipart: title, description, location, category,
    optional image. Image must be genuinely optional.

39. backend/app/api/router.py
    Aggregates module routers under /api. Extended at every later phase.

    CHECKPOINT 5: curl POST creates a complaint carrying category, urgency,
    public_impact and department. Features 1, 2, 3, 4 satisfied.

---

## PHASE 6 — Tracking and admin (all six required features green)

40. backend/app/modules/complaints/service.py   [NEW MODULE — add to tree]
    List with filters (ward, status, department, urgency), priority-sorted.
    Detail with timeline. Admin status transitions via state_machine only.

41. backend/app/modules/complaints/router.py     [NEW MODULE — add to tree]
    GET /api/complaints, GET /api/complaints/{id}, PATCH /api/complaints/{id}/status.

42. backend/app/modules/assets/passport.py
    Projects the event log into a readable timeline: reports, attempts,
    forensics, rejections, overrides, reopens.

43. backend/app/modules/assets/router.py
    GET /api/assets/{id}/passport, GET /api/assets/{id}/verify-chain.

    CHECKPOINT 6: ALL SIX REQUIRED FEATURES WORK VIA API. This is the
    screening-insurance milestone. Do not proceed until this is true.

---

## PHASE 7 — Forensics pipeline (the differentiator)

44. backend/app/forensics/temporal.py
    L1. Capture vs complaint vs server time. min_repair_minutes floor.
    Missing EXIF is DEFICIENT, never FAIL on its own.

45. backend/app/forensics/geospatial.py
    L2. Distance to asset centroid vs tolerance. Absent GPS -> DEFICIENT.
    Reported as claimed presence, never verified attendance.

46. backend/app/forensics/provenance.py
    L5a. C2PA manifest, EXIF Software tags, missing camera model,
    thumbnail mismatch. Defaults to INCONCLUSIVE. No AI-generation guessing.

47. backend/app/forensics/reuse.py
    L5b. pHash against this asset's prior closures and the ward corpus.
    Highest-yield signal in the system.

48. backend/app/forensics/duplication.py
    L6. Exact-normalized match including shared typos + cosine >= threshold.
    Returns the matched ticket IDs, not just a boolean.

49. backend/app/forensics/visual.py
    L3 + L4 through the AuditorAgent. Downgrades any verdict lacking a
    cited visible observation to INCONCLUSIVE.

50. backend/app/forensics/pipeline.py
    Runs deterministic links, then the single visual call, assembles the
    ForensicReport, calls policy.chain_sufficient, builds the deficiency list.

51. backend/tests/test_forensics.py  (part 2 — full pipeline)
    Act 3 -> FAIL/DEFICIENT/REUSE/MATCH, chain False.
    Act 5 -> all PASS, chain True.

    CHECKPOINT 7: the fake closure is caught and the honest closure passes,
    reproducibly, on the same inputs, every run.

---

## PHASE 8 — Closure protocol

52. backend/app/modules/closure/evidence.py
    Validates and stores the evidence bundle. Rejects browser-reencoded
    uploads that lost EXIF with a clear, actionable error.

53. backend/app/modules/closure/service.py
    Submit attempt -> run pipeline -> apply state machine -> append event
    -> write outbox. Increments attempt counter; >=3 triggers escalation.

54. backend/app/modules/closure/router.py
    POST /api/complaints/{id}/closure-attempts
    POST /api/closure-attempts/{id}/decision  (citizen accept / reject + reason)
    Both idempotent.

    CHECKPOINT 8: Resolved is unreachable without citizen acceptance.
    Rejection produces the specific deficiency list and a permanent event.

---

## PHASE 9 — Review, quorum and SLA

55. backend/app/modules/review/service.py
    Escalation queue, reviewer override with mandatory logged justification,
    quorum rule for multi-reporter assets, protection for officers facing
    a bad-faith rejection.

56. backend/app/modules/review/sla.py
    APScheduler job. 72h production, 60s demo. Timeout escalates to a
    reviewer. Never auto-closes, never leaves a ticket stuck forever.

57. backend/app/modules/review/router.py
    GET /api/escalations, POST /api/escalations/{id}/review.

    CHECKPOINT 9: ghosting citizen escalates within 60s in demo mode.
    Chain PASS + citizen reject routes to a reviewer, not to a dead end.

---

## PHASE 10 — Notifications

58. backend/app/modules/notify/outbox.py
    Writes the notification row inside the SAME transaction as the state
    change. Guarantees no silent status updates.

59. backend/app/modules/notify/channels/base.py
    Channel protocol. in_app now, email later, nothing else changes.

60. backend/app/modules/notify/channels/in_app.py
    Persists notifications, computes unread counts.

61. backend/app/modules/notify/sse.py
    Per-actor SSE stream via EventSourceResponse. One-way push, auto-reconnect.

62. backend/app/modules/notify/service.py
    Outbox dispatcher. Marks delivered, retries, fan-out to channels.

63. backend/app/modules/notify/router.py
    GET /api/notifications, GET /api/stream.

64. backend/app/modules/notify/channels/email.py   [P2]
    Resend adapter. Optional. Skip if time is short.

    CHECKPOINT 10: a status change reaches the subscribed client as an SSE
    event within a second, and survives a reconnect.

---

## PHASE 11 — Hardening and demo data

65. backend/app/core/security.py
    Per-IP rate limits, idempotency keys, hard daily Gemini cap with a
    graceful quota response. Public repo + public deployment = abuse target.

66. backend/app/modules/demo/router.py
    POST /api/demo/reset. Restores the seeded ward between judge runs.

67. backend/scripts/inject_exif.py
    Injects GPS, DateTimeOriginal and camera model into seed JPEGs via piexif.
    Seed photos stay JPEG — WebP conversion would strip EXIF and break the demo.

68. backend/fixtures/demo_trace.json
    The Act 1-7 worked example, encoded as data.

69. backend/scripts/seed.py
    Builds the ward from the fixture: 1 chronic asset, 7 reports, 6 reused
    closure remarks, the fake attempt and the honest attempt. Idempotent.

    CHECKPOINT 11: fresh boot produces the exact demo state. Reset works.

---

## PHASE 12 — Prove it and ship it

70. backend/tests/conftest.py
    Async client fixture, in-memory DB, Gemini stub with recorded responses.
    (Write this early if you prefer; it must exist before test_api_flow.)

71. backend/tests/test_api_flow.py
    End-to-end Act 1 -> Act 7 over HTTP, including the reopen and the
    tamper-detection call. This is the demo, automated.

72. backend/eval/labels.json
    ~30 labelled closure attempts: honest, wide-angle, stale, reused,
    edited, overstated.

73. backend/eval/run.py
    Measures false-positive rate on HONEST closures, recall per fraud class,
    abstention rate, triage accuracy, p95 latency, cost per closure.

74. backend/Dockerfile + backend/.dockerignore
    Hugging Face Spaces compatible. Non-root user, port 7860, secrets from env.

75. backend/app/agents/adk_agent.py     [P2]
    Google ADK runtime for the Auditor only. Same tools, same result schemas.

76. backend/app/agents/langgraph_agent.py  [P2]
    Alternative runtime. Proof that the port actually swaps.

    CHECKPOINT 12: pytest green. eval/results.json contains MEASURED numbers.
    Deployed backend responds on a public URL. Backend done — start frontend.

---

## CUT LIST (if under 48 hours)
Drop 64 (email), 75, 76 (alt runtimes), 72-73 shrink to 15 cases.
Never drop Phases 0, 1, 2, 5, 6, 7, 8. Those are the product.

## TREE ADDITION NEEDED
backend/app/modules/complaints/__init__.py
backend/app/modules/complaints/service.py
backend/app/modules/complaints/router.py