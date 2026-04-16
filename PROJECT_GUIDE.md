# Prism RAG — Complete Project Guide

> **For Sumith's presentation prep.** Every detail of the project explained in simple English, with a Q&A bank at the end covering every question sir might ask. Read this the day before and you can answer anything.

---

## Table of contents

1. [30-second elevator pitch](#1-30-second-elevator-pitch)
2. [The problem this solves](#2-the-problem-this-solves)
3. [What we built — nine big pieces](#3-what-we-built--nine-big-pieces)
4. [The tech stack — every tool, explained simply](#4-the-tech-stack--every-tool-explained-simply)
5. [How the whole thing fits together](#5-how-the-whole-thing-fits-together)
6. [The retrieval pipeline — what happens when you ask a question](#6-the-retrieval-pipeline--what-happens-when-you-ask-a-question)
7. [The seven answer modes](#7-the-seven-answer-modes)
8. [The five agent layers](#8-the-five-agent-layers)
9. [RBAC — the security model in plain English](#9-rbac--the-security-model-in-plain-english)
10. [Public Pipeline Lab](#10-public-pipeline-lab)
11. [Analytics + Audit dashboards](#11-analytics--audit-dashboards)
12. [Data models — what's stored where](#12-data-models--whats-stored-where)
13. [File structure walkthrough](#13-file-structure-walkthrough)
14. [Key decisions + trade-offs](#14-key-decisions--trade-offs)
15. [Testing strategy](#15-testing-strategy)
16. [How to run it](#16-how-to-run-it)
17. [Known limits + what's out of scope](#17-known-limits--whats-out-of-scope)
17.5. [**Viva traps — the 5 deliberate details you MUST nail**](#175-viva-traps--the-5-deliberate-details-you-must-nail)
18. [**Q&A — 50+ questions sir might ask, with answers**](#18-qa--50-questions-sir-might-ask-with-answers)
19. [15-minute demo script](#19-15-minute-demo-script)
20. [One-line summary you can say at the end](#20-one-line-summary-you-can-say-at-the-end)

---

## 1. 30-second elevator pitch

**Prism RAG is a document-aware chat platform where every user only sees answers from documents their role is allowed to read.** It combines vector search (meaning) and keyword search (exact words) to find relevant paragraphs, cites them like a research paper, and judges its own answers for faithfulness. On top of that, I added five agent behaviours so the system confirms ambiguous questions, shows its confidence, and routes restricted queries into an access-request flow.

**If sir asks "what did you build in one sentence":**
*"I built a retrieval-augmented chat system with four-level role-based access control enforced at the vector store, seven answer modes, and five agent layers that make the assistant feel personalized instead of robotic."*

---

## 2. The problem this solves

Companies have sensitive documents — HR policies, financial reports, security incidents, board minutes. A regular ChatGPT can't help with them because:

1. **It doesn't know the internal docs** — the model was trained on public data.
2. **It can't respect access control** — a guest user might accidentally see CEO salary.
3. **It hallucinates** — makes up facts that aren't in the documents.
4. **It blends different documents** — asks about HRMS, gets an answer mixing HRMS portal technical doc with HR policy handbook.

**Prism RAG fixes all four.** We load documents into a vector database, tag each one with a clearance level, enforce RBAC at the search layer (not just hidden in the UI — the model literally cannot see docs above the user's clearance), stream answers with citations, and ask the user to clarify when multiple docs could match.

---

## 3. What we built — nine big pieces

1. **Multi-role authentication** — 4 roles (guest / employee / manager / executive) with 4 clearance levels (PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED). JWT tokens carry the role claim.

2. **RAG chat with 7 answer modes** — instead of one generic "I'll try to answer" path, the system classifies every query into exactly one of seven modes (social, system, meta, grounded, disambiguate, general, refused/unknown) so the user always gets the right kind of response.

3. **Five agent layers** — extra UX behaviours on top of base RAG: doc disambiguation, intent mirror, confidence chip, thread-scoped memory, RBAC-transparent refusal with access request.

4. **Per-role visibility kill-switch** — beyond clearance levels, executives can hide any specific doc from any subset of non-exec roles. For example, a CONFIDENTIAL doc visible to manager but hidden from employee.

5. **Public Pipeline Lab at `/pipeline`** — no login needed. Anyone can paste a question and watch the entire pipeline run live: embedding heatmap, rank journey chart, stage-by-stage SSE events. A transparent teaching tool.

6. **ECharts analytics dashboard** — donut chart of answer modes, gauge of faithfulness, Sankey of user-to-mode, heatmap of query times. Executive-only.

7. **Audit log with KPI strip** — every query writes one row. Sparkline widgets for queries today, refused %, average latency, average faithfulness.

8. **Document upload + management** — anyone can upload docs; they land at the uploader's own clearance level by default (capped — a guest cannot upload a RESTRICTED doc). Executives can reclassify and set per-role hide-lists atomically (Qdrant payload + BM25 pickle rewritten in one transaction).

9. **Thread memory + chat history** — every conversation is saved, threads have auto-generated titles from the LLM, full replay including the disambiguation and intent state.

---

## 4. The tech stack — every tool, explained simply

### Frontend

| Tool | What it is (simple) | Why we chose it |
|---|---|---|
| **React 18 + TypeScript** | Library to build interactive web UIs; TypeScript catches bugs before running | Industry standard; TS gives safety on a multi-file project |
| **Vite** | Dev server that reloads the browser on code save | Much faster than webpack — starts in 1 second |
| **Tailwind CSS** | Write styles directly in HTML classes (`bg-blue-500`) instead of separate CSS files | Fast, consistent, no CSS name collisions |
| **framer-motion** | Animation library (fade-in, slide, hover effects) | Premium feel, one-line API |
| **lucide-react** | Icon library — thousands of SVG icons | Free, clean, tree-shakable |
| **ECharts 6** | Chart library — donut, gauge, Sankey, heatmap, bar, line | Richer than Chart.js, better for complex dashboards |
| **react-markdown** | Renders markdown in the chat bubble (bold, lists, code) | The LLM answers in markdown |

### Backend

| Tool | What it is (simple) | Why we chose it |
|---|---|---|
| **FastAPI** | Python web framework for building REST APIs | Fastest Python API framework, auto-generates OpenAPI docs, first-class async |
| **Uvicorn** | The server that runs FastAPI | ASGI server, handles async requests efficiently |
| **SQLModel** | Defines database tables as Python classes (combines SQLAlchemy + Pydantic) | Type-safe, less boilerplate than raw SQLAlchemy |
| **SQLite** | Single-file database | Zero-config; perfect for demo |
| **sse-starlette** | Streams events (Server-Sent Events) over HTTP | Lets the chat stream tokens live |

### AI / ML

| Tool | What it does | Why we chose it |
|---|---|---|
| **Qdrant** | Vector database — stores embeddings and searches by cosine similarity | Open-source, fast, supports payload filtering (we use it for RBAC) |
| **all-MiniLM-L6-v2** | Turns text into a 384-dimensional vector (embedding) | Small (90 MB), fast on CPU, strong quality |
| **BGE-reranker-base** | Cross-encoder — re-scores a shortlist of passages against the query | Precision-boost step; turns 10 candidates into a better top-5 |
| **rank_bm25** | Classic lexical search algorithm — keyword matching with term-frequency tricks | Catches exact matches (names, codes) that embeddings miss |
| **gpt-4o-mini** | Lightweight GPT-4 variant by OpenAI | Fast (3-5s), cheap, strong for grounded generation |

### Why these choices together?

- **Dense (embedding) + BM25 (keyword)** = hybrid retrieval. Dense catches meaning ("CEO pay" finds "executive compensation"); BM25 catches exact tokens (case IDs, names). You get both.
- **Rerank on top** = precision. After retrieving 10 candidates quickly, the heavy model re-scores them so the best 5 make it to the prompt.
- **RBAC at Qdrant** = security. The filter is applied BEFORE search, so the model never sees above-clearance chunks. No prompt injection can exfiltrate them.

---

## 5. How the whole thing fits together

```
Browser (React)
    │
    ├── /                    (Landing page — public)
    ├── /pipeline            (Pipeline Lab — public, no login)
    ├── /signin              (Login)
    └── /app                 (Protected — after login)
          ├── Chat           (Main interface)
          ├── Audit          (Exec-only)
          └── Analytics      (Exec-only)

           ↓ HTTP/SSE
FastAPI backend :8765
    │
    ├── /api/auth            (Login, JWT)
    ├── /api/chat            (Main chat — SSE stream)
    ├── /api/documents       (Upload/list/reclassify)
    ├── /api/threads         (Chat history)
    ├── /api/welcome         (Role-aware greeting payload)
    ├── /api/audit           (Exec-only audit log)
    ├── /api/access-request  (RBAC-blocked flow)
    └── /api/playground      (Public Pipeline Lab backend)

           ↓
Storage
    ├── SQLite   (Users, Documents, Threads, Turns, AuditLog)
    ├── Qdrant   (Vector index, RBAC payload — runs in Docker)
    └── BM25     (Per-doc pickled lexical indexes)

           ↓
External
    └── OpenAI API (gpt-4o-mini for generation, intent, faithfulness)
```

**The key idea:** The browser only talks to FastAPI. FastAPI does all the heavy lifting (retrieval, LLM calls, RBAC) and streams results back using Server-Sent Events so tokens appear live.

---

## 6. The retrieval pipeline — what happens when you ask a question

When you type "what is the CEO's salary?" into the chat, here is EVERY step:

### Step 1 — Rate limit check
We allow 60 chats/minute/user. Prevents abuse. Returns 429 if exceeded.

### Step 2 — Short-circuits (before retrieval)
The system checks if the message is:
- **Social** ("hi", "thanks") → returns a welcome card instantly
- **System intel** ("what queries have users run?") → pulls from audit log
- **Meta conversation** ("what did I ask earlier?") → answers from chat history

These three modes skip retrieval entirely.

### Step 3 — Cache lookup
SHA1 hash of (query + user's clearance + doc filter + settings). If we've seen this exact query before from a user with the same access, replay the cached answer. Saves latency.

### Step 4 — Intent classification (NEW — parallel LLM call)
We fire off an LLM call `_classify_intent()` that produces a one-sentence restatement: *"You're asking about the CEO's salary structure."* This runs in parallel with retrieval, so its latency is absorbed.

### Step 5 — Conversational contextualization
If the message is a follow-up ("tell me more", "and the employee one?"), an LLM call rewrites it into a self-contained question using chat history. Otherwise the message passes through unchanged.

### Step 6 — Multi-query (optional, off by default)
If enabled, the LLM generates 3 alternative phrasings of the query ("CEO pay", "executive compensation", "head-of-company salary") so retrieval catches wider recall. Each runs in parallel.

### Step 7 — Embed the query
MiniLM-L6-v2 turns the query text into a 384-dimensional vector. Takes ~20ms on CPU.

### Step 8 — RBAC filter is applied
Before any search, we build a Qdrant filter:
- `doc_level <= user.level` (clearance cap)
- `doc_id NOT IN disabled_for_roles[user.role]` (per-role hide-list)

This filter is attached to the Qdrant query — not applied after. Chunks above clearance are physically not returned.

### Step 9 — Dense search (Qdrant)
Cosine similarity between the query vector and all chunk vectors that passed the filter. Returns top-10.

### Step 10 — BM25 search (in-process, per-doc)
Each doc has its own pickled BM25 index. We load them (cached in memory), score the query against each, take top-10 across all allowed docs.

### Step 11 — RRF fusion
Reciprocal Rank Fusion: for each chunk, `score = Σ 1/(60 + rank_in_list_i)`. Fuses dense + BM25 rankings without needing to calibrate the two different score scales. Top-10 fused.

### Step 12 — Cross-encoder rerank (BGE)
BGE-reranker-base takes (query, chunk) pairs and produces a fine-grained relevance score. We rerank the top-10 and keep top-5.

### Step 13 — Relevance gate (two-path rule)
We check if the top chunk clears a bar:
- **Strong path**: RRF ≥ 0.024 OR rerank ≥ 0.30 → proceed to generation
- Below bar → corrective retry (Step 14) or fall through to mode decision

### Step 14 — Corrective RAG (one retry)
If the first pass was weak, an LLM rewrites the query with keyword expansion ("CEO pay" → "executive compensation salary band remuneration leadership") and retries retrieval once. If stronger → proceed; if not → fall through.

### Step 15 — AGENT: Disambiguation check
NEW layer. If top-K chunks span 2+ distinct docs with rerank scores within 20%, we DON'T generate. We return a **disambiguate** response with the candidate docs so the user picks. Example: "HRMS flow" could match HRMS Portal Technical Report OR HR Policy Handbook — we ask which.

### Step 16 — Final mode decision
Routing matrix:
- `disambig_candidates != None` → **disambiguate** mode
- `grounded_ok` → **grounded** mode (proceed to generate)
- Not a real query → **unknown**
- Bypass probe (search ignoring RBAC) finds a higher-clearance match → **refused** (L4 diagnostic) or **unknown** + `rbac_blocked` flag (non-L4)
- Otherwise → **general** mode (world knowledge answer)

### Step 17 — AGENT: Emit intent
Before streaming, we await the intent task (up to 2s) and emit an `intent` event so the frontend shows the "Understood as..." pill above the answer.

### Step 18 — Stream the answer
The LLM gets a system prompt + chat history + context block (the 5 reranked chunks with [Source N] labels) + the query. Tokens stream back over SSE to the browser. Streaming is important because it makes responses feel instant.

### Step 19 — Faithfulness judge
An LLM-as-judge call rates the answer against the sources on a 0-1 scale. This runs AFTER streaming so it doesn't block the user seeing the answer.

### Step 20 — AGENT: Compute confidence chip
Composite score: `int(round((top_rerank * 0.5 + faithfulness * 0.5) * 100))`. Clamped [5, 100]. Attached to the `done` event so frontend renders the colored chip.

### Step 21 — Post-hoc demotion (safety net)
If the LLM refused despite retrieved chunks ("I could not find this in the provided documents"), we re-run the bypass probe and demote: if a higher-clearance doc would have answered → unknown/refused; otherwise → general (re-stream with world-knowledge prompt).

### Step 22 — Persist + audit
One row in ChatTurn for the user message + one for the assistant reply. One row in AuditLog with everything: user, query, mode, retrieve/rerank/generate latencies, tokens, faithfulness, cited doc IDs. Thread `updated_at` touched.

### Step 23 — Emit `done`
Final SSE event carries: answer_mode, thread_id, latencies, tokens, faithfulness, confidence, rbac_blocked. Browser updates metadata on the message.

**Total typical latency:** 3-5 seconds for a grounded answer.

---

## 7. The seven answer modes

Every response is exactly one mode. Mode is decided by a chain of intent detectors BEFORE retrieval runs (for the early ones) or BY retrieval result (for the later ones).

### 1. Social
**Triggers:** "hi", "hello", "thanks", "what can you do?"
**Response:** Role-aware welcome card with your name, clearance badge, accessible tier counts, and suggestion chips.
**Latency:** ~1ms (no LLM, no retrieval).
**Why this mode exists:** Users greet the assistant. Treating "hi" as a document query feels broken.

### 2. System
**Triggers:** "show recent queries", "what activity is happening on the platform?"
**Response:** Streamed LLM answer using audit-log data as context, scoped by role (exec sees all users; non-exec sees only their own).
**Why:** Users legitimately ask about system usage. Routing this to doc retrieval would return nothing.

### 3. Meta
**Triggers:** "what was my first question?", "summarize our chat", "what did you tell me earlier?"
**Response:** Streamed answer using only chat history as context. No document retrieval.
**Why:** Conversation-level questions belong in chat memory, not docs.

### 4. Grounded (the main mode)
**Triggers:** A substantive query that retrieves meaningful chunks.
**Response:** RAG-generated answer with [Source N] inline citations, source cards below, faithfulness score, confidence chip, intent pill.
**Latency:** 3-5s.

### 5. Disambiguate (NEW — agent layer)
**Triggers:** Top-K reranked chunks span 2+ docs with scores within 20%.
**Response:** Picker card with candidate docs (label + 1-line hint). User clicks → retry scoped to that doc.
**Why:** Prevents the "blended-doc" correctness bug.

### 6. General
**Triggers:** No retrieval hits anywhere in the corpus (even ignoring RBAC — so we're sure there's no leak to protect).
**Response:** LLM answers from world knowledge with the disclaimer *"This isn't in the provided documents — answering from general knowledge."*
**Why:** Guest asks "what's the atomic weight of hydrogen" — the best response is a real answer, not "no confident answer".

### 7. Refused (L4) / Unknown (non-L4)
**Triggers:** Retrieval misses BUT the bypass probe (search ignoring RBAC) found a higher-clearance match.
**L4 response:** Diagnostic card — "A document matching this query exists above your clearance. Shown to executives for auditability."
**Non-L4 response:** Either bland "no confident answer" OR the richer **Access Request Banner** (when `rbac_blocked: true`) with a reason textarea + Submit button that writes an audit row.
**Why:** Security. If the system said "I can't tell you" to a guest, the guest would know such a doc exists — that's still leaking info about existence. Instead we return unknown uniformly so guest can't tell whether the doc exists or just doesn't.

---

## 8. The five agent layers

These are the features that make the chat feel like a real agent instead of a one-shot chatbot.

### Layer 1 — Clarify-before-answer (disambiguate mode)

**What it does:** When a query legitimately matches multiple docs, it pauses and asks which you meant.

**Real example from our demo corpus:** Upload two docs — `HR_Policy_Handbook.docx` and `HRMS_Portal_Production_Report.docx`. Ask "HRMS flow". Instead of blending both, the system returns a card:

> **Clarifying question**
> Your question could match these documents — pick one.
> • HRMS Portal Production Report · 3 chunks · score 0.87 — *"HRFlow is a multi-tenant HR Management System built on Django..."*
> • HR Policy Handbook · 2 chunks · score 0.79 — *"Employee leave policy: 18 days paid annual leave..."*

User clicks HRMS Portal → retry scoped to that doc only → clean answer.

**How it detects:** After rerank, group chunks by `doc_id`, keep max(rerank_score) per doc. If top two docs both have score ≥ 0.25 AND the gap between them is ≤ 20% of the top score → fire disambiguation.

**Where it lives:** `backend/src/api/routers/chat.py` — `_detect_doc_ambiguity()` function.

### Layer 2 — Intent Mirror

**What it does:** Shows a pill above every grounded answer that says *"Understood as: You're asking about the tech stack of the HRMS portal."* User can edit the restatement inline and re-run.

**Why it matters:** Builds trust. If the agent misreads "HRMS flow" as "How to flow HR?", you see it BEFORE the wrong answer, not after.

**How it's fast:** The intent LLM call fires in parallel with retrieval (`asyncio.create_task`). By the time retrieval finishes (~1-2s), intent is ready (~0.5-1s). No extra latency.

**Where it lives:** `_classify_intent()` in chat.py + `IntentMirror.tsx` component.

### Layer 3 — Confidence Chip

**What it does:** A small colored pill next to the answer showing a 0–100 score.

**Formula:** `confidence = int((top_rerank * 0.5 + faithfulness * 0.5) * 100)`, clamped to [5, 100].

**Color bands:**
- ≥80 Green "High confidence"
- 60-79 Blue "Confident"
- 40-59 Amber "Limited" + Broaden button
- <40 Red "Low confidence" + Broaden button

**Broaden button:** Re-runs the LAST query with `use_multi_query: true` for that call only. Flips to 3-query fan-out to catch content the first pass missed. Doesn't mutate global settings.

### Layer 4 — Thread-scoped memory

**What it does:** If you ask 2+ questions about the same doc, the system quietly scopes new queries to that doc. Shows a dismissable pill above the input: *"Following up in HRMS Portal Production Report · 3 recent answers [×]"*.

**Detection:** Frontend-only. Scans last 3 grounded assistant turns; if a doc is top-cited in ≥2 of them → auto-scope.

**Dismissal:** Click × once and that specific doc is blocked from re-triggering for this thread.

**Priority:** Explicit sidebar doc filters always win over thread scope.

### Layer 5 — RBAC-transparent refusal (Access Request)

**What it does:** When unknown/refused was triggered by RBAC (a higher-clearance doc matched), the card is no longer bland. It shows a lock icon and a "Request access" button. Clicking it opens a textarea for a reason, Submit writes an audit row.

**Why:** Gives the user an actionable path instead of a dead end. Executives can see the request later in the Audit tab.

**API:** `POST /api/access-request` with `{ query, reason? }` → writes AuditLog with `answer_mode = "access_request"`.

---

## 9. RBAC — the security model in plain English

### The four levels

| Level | Label | Roles with access | Example content |
|---|---|---|---|
| 1 | PUBLIC | guest, employee, manager, executive | Training materials, public handbooks |
| 2 | INTERNAL | employee, manager, executive | IT asset policy, engineering runbooks |
| 3 | CONFIDENTIAL | manager, executive | Q4 financials, product roadmap |
| 4 | RESTRICTED | executive | Salary bands, board minutes, incidents |

### The golden rule

**Filter at the vector store, not the prompt.**

Wrong way (what bad RAG systems do):
1. Retrieve all matching chunks
2. LLM generates answer
3. Check if user is allowed to see it, hide if not

Problem: the model saw the forbidden content. Prompt injection could exfiltrate it.

Our way:
1. Add Qdrant filter `doc_level <= user.level AND role NOT IN disabled_for_roles`
2. Retrieve — forbidden chunks never come back
3. LLM generates answer — never saw what it shouldn't see

**Proof it works:** `backend/tests/integration/test_rbac.py` — 25 tests run every query against every role, verify no chunk above clearance is ever returned.

### Per-role visibility kill-switch

Extra layer on top. Each document has a `disabled_for_roles: list[str]` field. Executive can publish a CONFIDENTIAL doc that manager sees but employee doesn't — without changing classification.

**"Atomic" update flow (be precise about what atomic means here):** When exec changes a doc's classification or hide-list:
1. Update SQLite `Document` row
2. Rewrite every chunk's `doc_level` payload in Qdrant (via `qm.Filter(...)` on `doc_id`)
3. Rewrite BM25 pickle metadata

All three happen in the same HTTP request handler with try/except rollback semantics — if any step fails, we roll back the SQLite write. From the user's perspective, either all three updated or none did.

**What "atomic" does NOT mean here:** it's NOT a true distributed ACID transaction across three different storage systems (SQLite + Qdrant + pickle file on disk). That would require a two-phase commit coordinator or an outbox pattern. For our demo-scale single-server deployment, atomic-at-the-request-boundary is the right trade-off. For production I'd add an outbox queue so all three stores converge even on partial failure.

---

## 10. Public Pipeline Lab

**The flagship demo.** At `/pipeline` — no login. Anyone can paste a question and watch every stage.

**What's on the page:**

1. **System Flow diagram (SVG)** — architectural map. 13 nodes, hover any for explanation. Active stage pulses as SSE events arrive.

2. **7-stage progress ribbon** — Embed → Dense → BM25 → RRF → Rerank → Generate → Judge. Particle animation flows along edges between active stages.

3. **Embedding fingerprint** — the actual 384-dim vector rendered as a diverging-color heatmap. Purple = positive value, orange = negative. Each cell is one dimension.

4. **Rank Journey bump chart** — every chunk's rank across Dense → BM25 → RRF → Rerank. Winning chunks get vivid distinct colors; false positives stay dashed grey. Shows WHY rerank matters.

5. **Per-stage cards** — actual retrieved hits with score bars. Each card has:
    - "What it does" (what the stage is)
    - "Why it matters" (pedagogy)
    - A `?` icon opening a theory deep-dive modal

6. **Compare mode** — toggle ON, run any query, see results side-by-side with rerank ON vs OFF. Teaches the value of reranking.

7. **Hover-on-chunk popovers** — full chunk text with query terms highlighted yellow.

**Why this is the demo centerpiece:** No other student's RAG shows the pipeline transparently. Sir can see exactly what embedding, BM25, RRF, rerank DO, not just hear you describe them.

**Backend endpoints:**
- `POST /api/playground/inspect` (SSE) — streams embed → dense → bm25 → rrf → rerank → token → done events
- `POST /api/playground/embed` — returns the live vector

---

## 11. Analytics + Audit dashboards

### Analytics (`/app/analytics` — exec only)

Built entirely from the audit log using ECharts:

- **Donut chart** — answer-mode distribution (grounded, refused, general, etc.). Center label shows total queries.
- **Gauge** — average faithfulness for grounded answers. Red < 0.5, amber 0.5-0.8, green ≥ 0.8.
- **Stacked area chart** — last 48 hours of activity, colored by mode.
- **Sankey diagram** — flows from username → answer mode. Shows who asks what.
- **Heatmap** — day-of-week × hour-of-day query density. When is the platform busiest?
- **Stacked horizontal bar** — average latency breakdown per user (retrieve / rerank / generate).
- **Horizontal bar** — top users by query count.

### Audit (`/app/audit` — exec only)

- **KPI strip with sparklines** — queries today, refused %, average latency, average faithfulness. Each with a 24h trend line.
- **Queryable table** — every query, every user. Search, filter, sort. Access requests show up here with `answer_mode = "access_request"`.

---

## 12. Data models — what's stored where

### SQLite (single file)

```
User
├── id, username, password_hash (bcrypt)
├── role: "guest" | "employee" | "manager" | "executive"
├── level: 1..4 (derived from role, cached)
└── title: free-form job title string

Document
├── doc_id (UUID), filename, mime, pages, chunks
├── doc_level: 1..4
├── classification: "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "RESTRICTED"
├── sections: list[str]
├── uploaded_by_username, uploaded_by_role
├── disabled_for_roles: list[str]  # per-role hide-list
└── created_at

ChatThread
├── id (12-char hex), user_id, title
├── created_at, updated_at

ChatTurn
├── id, thread_id, role: "user" | "assistant"
├── content (the message text)
├── sources_json (serialized list of source chunks OR {"candidates": [...]} for disambiguate)
├── refused, answer_mode, faithfulness
└── created_at

AuditLog
├── id, ts, user_id, username, user_level
├── query, refused, returned_chunks, allowed_doc_ids
├── answer_mode  # includes "access_request" for RBAC-blocked follow-ups
├── latency_retrieve_ms, latency_rerank_ms, latency_generate_ms, latency_total_ms
├── tokens_prompt, tokens_completion
├── cached, corrective_retries, faithfulness
```

### Qdrant (vector DB)

One collection, one point per chunk. Each point carries:
- `id`: UUID
- `vector`: 384-dim embedding
- `payload`:
  - `doc_id`, `filename`, `page`, `section`, `chunk_index`
  - `text` (the chunk content)
  - `doc_level` (1..4, enforced at filter time)

### BM25 pickles

One file per doc: `{doc_id}.pkl` — contains `BM25Okapi(tokenized_chunks)` + metadata mirror of doc_level for post-filter.

---

## 13. File structure walkthrough

```
backend/
├── src/
│   ├── api/
│   │   ├── app.py                       # FastAPI app factory, CORS, route mounts
│   │   └── routers/
│   │       ├── auth.py                  # /auth/login, /auth/me
│   │       ├── chat.py                  # /chat (SSE) — the big one (~1300 lines)
│   │       ├── documents.py             # /documents upload, list, visibility
│   │       ├── threads.py               # /threads CRUD
│   │       ├── audit.py                 # /audit (L4)
│   │       ├── welcome.py               # /welcome (role-aware greeting payload)
│   │       ├── playground.py            # /playground/inspect, /embed
│   │       ├── meta.py                  # /health
│   │       └── graph.py                 # /graph (dormant, page deleted)
│   ├── auth/
│   │   └── dependencies.py              # JWT decode, CurrentUser DI
│   ├── core/
│   │   ├── config.py                    # settings, env vars
│   │   ├── models.py                    # SQLModel tables (User, Document, Thread...)
│   │   ├── schemas.py                   # Pydantic request/response shapes
│   │   ├── prompts.py                   # All LLM prompts (SYSTEM, FAITHFULNESS, INTENT...)
│   │   ├── store.py                     # SQLite engine factory, doc visibility helper
│   │   ├── chat_cache.py                # Query cache (SHA1 keyed)
│   │   └── rate_limit.py                # 60/min chat rate limiter
│   └── pipelines/
│       ├── embedding_pipeline.py        # Qdrant client, embedder, ingestion
│       ├── retrieval_pipeline.py        # Dense + BM25 + RRF + rerank
│       ├── generation_pipeline.py       # LLM streaming + completion
│       └── loaders.py                   # PDF, DOCX, TXT, MD file loaders
├── tests/integration/
│   ├── test_rbac.py                     # 25 tests — no chunk above clearance leaks
│   ├── test_smart_rag.py                # 10 tests — all modes behave correctly
│   └── test_uploads.py                  # 3 tests — clearance-capped uploads
└── entrypoint/
    ├── serve.py                         # uvicorn runner
    ├── seed.py                          # seed 10 docs + 4 users on empty DB
    └── ingest.py                        # one-shot ingestion CLI

frontend/
└── src/
    ├── App.tsx                          # Routes
    ├── pages/
    │   ├── LandingPage.tsx              # Public landing
    │   ├── SignInPage.tsx               # Login form
    │   ├── ChatPage.tsx                 # Main protected chat
    │   ├── AuditLogPage.tsx             # Exec audit
    │   ├── AnalyticsPage.tsx            # Exec analytics (ECharts)
    │   └── PipelinePage.tsx             # PUBLIC /pipeline — the showcase
    ├── components/
    │   ├── Header.tsx, Sidebar.tsx, ThreadList.tsx
    │   ├── ChatInterface.tsx            # Main chat orchestration
    │   ├── ChatComposer.tsx             # Input textarea
    │   ├── MessageBubble.tsx            # Routes to right card per answer mode
    │   ├── DisambiguationCard.tsx       # Agent 1
    │   ├── IntentMirror.tsx             # Agent 2
    │   ├── ConfidenceChip.tsx           # Agent 3
    │   ├── AccessRequestBanner.tsx      # Agent 5
    │   ├── SourceCitationCard.tsx       # Renders [Source N] chip + text
    │   ├── RetrievalTrace.tsx           # Per-turn trace panel (behind chevron)
    │   ├── WelcomeCard.tsx              # Social-mode card
    │   ├── DocumentCard.tsx             # Knowledge-sidebar card + gear menu
    │   ├── VisibleToSelector.tsx        # Exec's "Visible to" picker
    │   ├── UploadDropzone.tsx           # Drag+drop upload
    │   └── SettingsDrawer.tsx           # Retrieval settings toggle drawer
    ├── hooks/
    │   ├── useChatStream.ts             # SSE parser + send() with all agent opts
    │   ├── useDocuments.ts              # Document list fetch + CRUD
    │   └── useThreads.ts                # Thread list fetch
    ├── store/
    │   └── appStore.ts                  # Zustand global state (user, settings, activeDocIds)
    ├── lib/
    │   ├── api.ts                       # Fetch wrappers, SSE handler, type exports
    │   └── auth.ts                      # JWT storage
    └── types/
        └── index.ts                     # TypeScript shared types

homework-basic/
├── rag_cli.py                           # Standalone CLI — RAG for any PDF
└── docker-compose.yml                   # Qdrant service

sir_documents/                           # Seed corpus (10 classified PDFs)
```

---

## 14. Key decisions + trade-offs

### Why hybrid retrieval (dense + BM25) instead of just embeddings?

**Reason:** Embeddings miss exact matches. Ask "SOC 2 audit report 2024 Q4" — BM25 finds the literal string; embeddings drift to "security compliance report". We need both.

### Why RRF instead of weighted averaging?

**Reason:** Dense and BM25 produce scores on incompatible scales (cosine 0-1 vs BM25 0-50). RRF fuses on RANK, not score — no calibration needed. Formula: `score = Σ 1/(60 + rank_i)`. Rank 1 everywhere = 2/61 ≈ 0.033. Rank 1 in one, 10 in the other = 1/61 + 1/70 ≈ 0.030. Tunable via the constant 60.

### Why rerank on top of RRF?

**Reason:** Dense and BM25 are first-stage retrieval — fast but coarse. Cross-encoder (BGE-reranker-base) is precision-focused: feeds (query, chunk) as a pair through a BERT-like model, outputs a fine-grained relevance score. Slower per-pair but we only rerank the top-10, so total cost is ~300ms.

### Why gpt-4o-mini instead of GPT-4 or a local LLM?

**Reason:** Latency. GPT-5 reasoning model took 17-40s per query (all those reasoning tokens). gpt-4o-mini gives us 3-5s for grounded, which feels instant. Also cheaper (~$0.15 per million input tokens). Local LLMs (Llama-3-8B on CPU) were 15s+ — too slow for interactive.

### Why SQLite instead of Postgres?

**Reason:** Zero-config demo. One file, no service to run. All our data (users, docs, threads, audit) fits easily. For production we'd migrate — SQLModel makes it a one-line engine swap.

### Why FastAPI instead of Django/Flask?

**Reason:** Async-first (we need it for SSE streaming), auto-generated OpenAPI docs, type-safe with Pydantic. Django is heavier; Flask requires more boilerplate for equivalent safety.

### Why Qdrant instead of Pinecone/Weaviate/Chroma?

**Reason:** Open-source, runs in Docker, rich payload filtering (our RBAC gate). Pinecone is paid. Weaviate was overkill. Chroma's filter support was weaker when we evaluated.

### Why React instead of Next.js/Svelte?

**Reason:** Vite + React gives us fast dev without SSR overhead. We don't need server-rendering — the app is behind auth. Svelte would work too, but React has better type support and more components on hand.

### Why Tailwind instead of CSS modules or styled-components?

**Reason:** Consistency (atomic classes), no CSS name collisions across 40+ components, fast to write. Tailwind's design tokens (`text-[13px]`, `bg-accent`) let us enforce a coherent spacing/typography system.

### Why light theme (not dark)?

**Reason:** Sumith explicitly switched from dark Enterprise to light premium SaaS after seeing the working app. Inspirations: Linear, Attio, Stripe. Dark felt heavy; light reads as polished.

### Why SSE instead of WebSocket for streaming?

**Reason:** SSE is HTTP-native, works through proxies, simpler client code (one event listener). We only need server-to-client streaming; WS's bidirectional channel is overkill.

### Why hybrid intent pipeline (5 short-circuits before RAG)?

**Reason:** Users don't only ask document questions. They greet, meta-ask, ask about the system. Routing ALL queries through retrieval produces bad UX ("I could not find that in the provided documents" for "hi"). We classify intent cheaply with string/regex first, LLM only for real queries.

### Why three timeouts on the intent LLM call?

- 4s inside `_classify_intent` — how long we wait for the LLM itself
- 2s at emission — how long we wait for the task to finish once we want to emit
- Combined fallback: if either trips, we just skip the pill. Never block the real answer.

---

## 15. Testing strategy

### Integration tests (38 passing, 1 skipped)

**test_rbac.py — 25 tests.** Runs each of 5 representative queries against each of 4 roles (20 combos) and verifies no returned chunk has `doc_level > user.level`. Plus 5 content-specific checks: "guest cannot see salary doc", "manager gets Q4 financials", "executive gets security incident".

**test_smart_rag.py — 10 tests.** One per answer mode. Verifies:
- `test_guest_out_of_corpus_query_returns_general_or_unknown` — "atomic weight of hydrogen" as guest
- `test_guest_rbac_blocked_query_never_returns_refused` — guest asking about CEO salary gets unknown (no leak via mode)
- `test_executive_grounded_query_returns_grounded` — exec gets proper cited answer
- `test_guest_hello_returns_social_with_welcome_payload` — social short-circuit works
- `test_meta_question_returns_social` — meta questions short-circuit
- …

**test_uploads.py — 3 tests.** Clearance-capped uploads — guest can't upload RESTRICTED, manager can upload CONFIDENTIAL with correct payload.

### How to run

```bash
cd backend
.venv/bin/python -m pytest tests/integration/ -v
```

Expected: `38 passed, 1 skipped in ~40s`.

### What's NOT automated

- **LLM quality tests** — we don't have a harness that verifies the LLM's ANSWER text. We test structure + mode, not prose quality. Faithfulness judge is our runtime signal.
- **Frontend tests** — no Jest/Vitest/Playwright setup. TypeScript catches structural bugs; we verify UX by running the app.

---

## 16. How to run it

### One-time setup

```bash
# 1. Qdrant (vector DB)
docker compose -f homework-basic/docker-compose.yml up -d qdrant

# 2. Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add OPENAI_API_KEY to .env

# 3. Seed 10 docs + 4 users
python -m entrypoint.seed --wipe

# 4. Frontend
cd ../frontend
npm install
```

### Every time

```bash
# Terminal 1: Qdrant (leave running)
docker compose -f homework-basic/docker-compose.yml up qdrant

# Terminal 2: Backend
cd backend && source .venv/bin/activate
python -m entrypoint.serve
# → http://127.0.0.1:8765

# Terminal 3: Frontend
cd frontend && npm run dev
# → http://localhost:5173
```

### Test accounts

| Username | Password | Role | Clearance |
|---|---|---|---|
| guest | guest_pass | Guest | L1 PUBLIC |
| employee | employee_pass | Employee | L2 INTERNAL |
| manager | manager_pass | Manager | L3 CONFIDENTIAL |
| exec | exec_pass | Executive | L4 RESTRICTED |

### Ports

- **5173** — Vite frontend
- **8765** — FastAPI backend (not 8000 — local Django servers block that)
- **6333** — Qdrant

---

## 17. Known limits + what's out of scope

- **Scanned PDFs (image-only)** — no OCR. Returns empty chunks.
- **Heavy tables / math** — flattened to text soup. Don't ask about complex formulas in tables.
- **Non-English content** — embeddings + reranker are English-only.
- **Multi-user concurrency** — SQLite can handle demo-scale but not production. Migrate to Postgres for prod.
- **Hot reload when docs change** — frontend polls /health + threads. Doc list refreshes when you click the Knowledge tab.
- **LLM cost** — every query = 1-3 OpenAI calls (intent, answer, faithfulness). Budget accordingly.
- **No finetuning** — we use off-the-shelf models. Domain-specific tuning would improve quality but adds significant infrastructure.

---

## 17.5 Viva traps — the 5 deliberate details you MUST nail

These are the five points most likely to catch you off-guard in a viva. Each one is a deliberate design choice that looks obvious in hindsight but is non-trivial to articulate under pressure. **Memorize these answers close to verbatim.**

### Trap 1 — The bypass probe (the hidden routing signal)

**If sir asks:** *"How do you decide between refused, unknown, and general when retrieval fails?"*

**Say this:**
> *"We run a second retrieval pass that IGNORES the RBAC filter — we call it the bypass probe. Its results NEVER reach the user; they're purely a routing signal. If the bypass probe finds a strong match, that means a higher-clearance doc would have answered this query. So for non-L4 users we return `unknown` (no metadata leak) and for L4 we return `refused` (the audit diagnostic). If the bypass probe ALSO finds nothing, then the question isn't answerable from any doc in the corpus at any clearance, so it's safe to fall back to world knowledge as `general`."*

**Why it's easy to forget:** The bypass probe isn't a user-visible feature. It runs silently and its output is thrown away. But it's the single most important decision in the answer-mode router.

**Where to point if asked to show code:** [backend/src/api/routers/chat.py](backend/src/api/routers/chat.py) — search for `bypass=True` — appears twice (once in primary mode decision, once in post-hoc demotion).

### Trap 2 — Why non-L4 gets "unknown" instead of "refused"

**If sir asks:** *"If you detect the query would have matched a restricted doc, why not just tell the user 'access denied'?"*

**Say this:**
> *"Because 'access denied' is itself a metadata leak. If a guest user saw 'refused' after asking about CEO salary, they'd know a doc matching that topic exists in the system — just at a clearance they don't have. That's leaking information about the EXISTENCE of restricted content. `unknown` is deliberately ambiguous: it could mean 'no doc matches your question at any level' OR 'a higher-clearance doc matches but you can't see it'. The user can't tell which. Zero information leaks. Only L4 users get the explicit `refused` diagnostic because they already have audit-level clearance — it's safe to tell them."*

**The sharpest possible version of this answer:**
> *"The mode name itself carries information. 'Refused' leaks existence. 'Unknown' doesn't. So we deliberately use 'unknown' for anyone who doesn't have clearance to learn that restricted content exists."*

**Why it's a trap:** Sir will almost certainly ask "why don't you just refuse?" — it sounds pedantic, but this is the whole security argument. Get it wrong and the RBAC story falls apart.

### Trap 3 — What "atomic" actually means in the visibility update

**If sir asks:** *"You said visibility updates are atomic across three stores — how is that atomic?"*

**Say this:**
> *"Good question — 'atomic' here means atomic-at-the-request-boundary, not a true distributed ACID transaction. The three stores are SQLite, Qdrant, and the BM25 pickle on disk — three completely different systems. What I do: wrap all three writes in a single request handler with try/except rollback. If any step fails, I roll back the SQLite change. From the user's perspective, either all three updated together or none did. For a demo-scale single-server deployment that's the right trade-off. For production I'd add an outbox pattern or a two-phase commit coordinator to get true distributed durability on partial failures."*

**Why it's a trap:** I used the word "atomic" in the README. A careful viva examiner will ask "atomic how?" and if you say "it's one transaction", that's wrong (SQLite + Qdrant + pickle can't be in one transaction). Being precise about this shows maturity.

### Trap 4 — Why gpt-4o-mini (with concrete numbers)

**If sir asks:** *"Why did you pick gpt-4o-mini? Why not GPT-4, GPT-5, or a local model?"*

**Say this:**
> *"I benchmarked three options on our corpus. GPT-5 reasoning model: 17 to 40 seconds per query — all those reasoning tokens pile up. Local Llama 3 8B on CPU: 15+ seconds. gpt-4o-mini on OpenAI: 3 to 5 seconds for a grounded answer. I also measured quality — gpt-4o-mini averages 0.85+ faithfulness on our TechNova corpus, which is higher than we need. The decision wasn't just 'use the cheapest' — I actually measured. Interactive UX demands sub-5-second responses; anything above that feels broken. Until local models close that gap, gpt-4o-mini is the right call."*

**Why this matters:** Mentioning the concrete 17-40s / 15s / 3-5s numbers unprompted shows you actually benchmarked. Most students pick a model based on tutorials — you picked based on data. That's a maturity signal.

### Trap 5 — Thread-scoped memory is FRONTEND-ONLY (backend is stateless)

**If sir asks:** *"How does the backend know when to scope queries to one doc?"*

**Say this:**
> *"It doesn't. Thread-scoped memory is entirely frontend. The React code in ChatInterface.tsx scans the last 3 grounded assistant messages, counts which document was top-cited in each, and if the same doc appears in ≥2 of them, it auto-includes that doc_id in the next chat request. The backend just sees a standard `doc_ids: ['abc123']` filter in the ChatRequest body and respects it like any other. The backend is stateless about thread scope — all the memory logic lives in the UI, so it can be turned off client-side without touching the API."*

**Why this is subtle:** Thread-scope FEELS like server-side memory when you use it. It's natural to assume the backend tracks "this user's been asking about HRMS, I'll bias toward that doc". It doesn't. The frontend does all the work and just sends a normal filter. This design keeps the backend simpler and the memory layer opt-in.

**Bonus:** If sir asks "why did you do it in the frontend?", answer: *"Three reasons. One: the backend already accepts a doc_ids filter, so we reuse existing machinery instead of building a new state store. Two: the logic is trivial to tune or disable client-side without redeploying the API. Three: it keeps the backend stateless about UI concerns — memory is a presentation-layer decision."*

---

## 18. Q&A — 50+ questions sir might ask, with answers

These are ready-to-say answers. Read them aloud once before the demo so the words come naturally.

### Conceptual — What is this?

**Q: What is this project in one sentence?**
A: It's a retrieval-augmented chat system with four-level role-based access control enforced at the vector store, seven answer modes, and five agent layers that make the assistant feel personalized.

**Q: What problem does it solve?**
A: Enterprise document Q&A with three guarantees: the model never sees documents above the user's clearance, ambiguous questions are clarified instead of blended, and every answer has inline citations plus a self-assessed confidence score.

**Q: Why do we need RAG at all — can't the LLM just answer?**
A: The LLM was trained on public internet data. It doesn't know our internal HR policy, Q4 financials, or security incidents. RAG lets us ground the model in our own documents so it answers factually instead of hallucinating.

**Q: What does RAG stand for?**
A: Retrieval-Augmented Generation. Retrieve relevant documents first, then generate the answer using those documents as context.

**Q: What's the difference between retrieval and generation?**
A: Retrieval finds the relevant paragraphs from a document library. Generation writes the natural-language answer using those paragraphs. Two different models: a cheap embedder for retrieval, a stronger LLM for generation.

### Architecture

**Q: Walk me through the architecture.**
A: Three tiers. The browser (React) talks only to the FastAPI backend over HTTP and Server-Sent Events for streaming. The backend orchestrates everything — authentication, retrieval, LLM calls, database writes. Storage is three pieces: Qdrant for vectors, SQLite for relational data (users, documents, threads, audit), and per-doc BM25 pickles for keyword search. External: OpenAI's gpt-4o-mini for generation.

**Q: Why FastAPI not Django or Flask?**
A: FastAPI is async-first — it handles SSE streaming natively without extra work. It auto-generates OpenAPI docs from type hints. It's the fastest Python web framework. Django would be overkill for our API; Flask would need more boilerplate for the same type safety.

**Q: Why React over Next.js?**
A: Vite + React gives fast dev without the overhead of server-side rendering. We don't need SSR — the protected app lives behind auth. Next.js would add complexity we don't need.

**Q: Why SQLite not Postgres?**
A: Zero-configuration. One file, no service to start. For demo scale this is perfect. SQLModel makes the migration to Postgres a one-line engine swap if we ever need it.

### Retrieval pipeline

**Q: Walk me through what happens when I ask "What is the CEO salary?"**
A: Nine stages. One: rate-limit check. Two: is it a greeting or meta question — no. Three: cache lookup — miss. Four: an LLM call fires in parallel to classify intent. Five: embed the query into a 384-dim vector. Six: apply the RBAC filter — if the user is guest, RESTRICTED docs like Salary Structure are filtered out at Qdrant. Seven: dense search plus BM25 search in parallel. Eight: RRF fuses the two rankings. Nine: BGE reranker scores the top 10, keeps top 5. Then if the top match is strong, the LLM generates an answer citing those 5 chunks. If not, we try a query rewrite and one more retrieval pass. After streaming, the faithfulness judge rates the answer 0-1 and we compute a confidence chip.

**Q: What's an embedding?**
A: A way to turn text into a list of numbers — specifically 384 numbers in our case. Two pieces of text with similar meaning get similar lists. We compare using cosine similarity — the angle between the two vectors.

**Q: What's BM25?**
A: A classical keyword-search algorithm from the 90s, based on term-frequency and inverse-document-frequency with length normalization. It catches exact matches — document IDs, product names, rare technical terms — that embeddings can miss.

**Q: Why use both dense and BM25?**
A: They fail on different queries. Dense misses exact strings like "CVE-2024-3094". BM25 misses synonyms — it doesn't know "CEO pay" and "executive compensation" are the same thing. Combining them catches both.

**Q: What's RRF?**
A: Reciprocal Rank Fusion. For each chunk, sum 1 over (60 plus its rank) from each list. You fuse rankings instead of scores, so you don't need to calibrate dense-score vs BM25-score. It's simple, fast, and works well empirically.

**Q: Why rerank after retrieval?**
A: Dense and BM25 are coarse — they're first-stage retrieval. The cross-encoder sees (query, chunk) as a pair and produces a precision score. We only rerank the top 10, so total cost is about 300ms, but the precision gain is big — wrong chunks in top 10 get pushed out of top 5.

**Q: What's a cross-encoder?**
A: A model that takes TWO pieces of text as input and outputs a relevance score. Unlike an embedder (which encodes each text independently), a cross-encoder sees both at once, so it can capture fine-grained interactions. Slower per pair but much more accurate.

**Q: What model is the embedder?**
A: sentence-transformers/all-MiniLM-L6-v2. Small at 90 MB, fast on CPU, 384 dimensions. Widely considered a strong default.

**Q: What model is the reranker?**
A: BAAI/bge-reranker-base. 278 million parameters, optimized for passage reranking. Runs on CPU in a few hundred milliseconds for a batch of 10 pairs.

**Q: What model generates answers?**
A: OpenAI's gpt-4o-mini. We tried GPT-5 — too slow, 17 to 40 seconds per query because of reasoning tokens. We tried local Llama 3 on CPU — also too slow. gpt-4o-mini gives us 3 to 5 seconds, which feels instant to the user.

### Security + RBAC

**Q: Explain RBAC in simple terms.**
A: Role-based access control. Four roles — guest, employee, manager, executive — and four clearance levels. Each document has a level; each user has a level. A user can only see documents at or below their level. That's the base rule. On top, executives can hide specific documents from specific roles without changing the level.

**Q: Where is RBAC enforced? UI or backend?**
A: At the vector store. The Qdrant filter runs `doc_level <= user.level AND user.role NOT IN disabled_for_roles` BEFORE the search. Chunks above clearance never come back to Python at all. The model physically cannot see what the user isn't allowed to see. This means prompt injection cannot exfiltrate restricted content.

**Q: Prove it works.**
A: 25 integration tests. Each runs a query under each of the four roles and verifies no chunk above the user's clearance leaves Qdrant. Plus specific tests like `test_guest_cannot_see_salary`, `test_manager_gets_q4_financials`, `test_employee_cannot_see_security_incident`.

**Q: What if the LLM cites a doc the user shouldn't see?**
A: Impossible. Only allowed chunks were ever in the prompt. The LLM cannot cite a chunk it never received.

**Q: What about metadata leaks? If a guest asks about CEO salary and gets "I can't tell you", they know such a doc exists.**
A: Good catch. We return "unknown" instead of "refused" to non-L4 users. "unknown" could mean either "the answer isn't in the corpus" OR "there's a higher-clearance doc you can't see" — the user can't tell which. L4 users get the explicit "refused" diagnostic for auditability. The new agent layer 5 goes further — if RBAC was the blocker, the user sees an access-request card and can request access explicitly.

**Q: Can a user upload above their clearance?**
A: No. Upload is clearance-capped. A guest can only upload PUBLIC documents. Tested in `test_guest_upload_above_clearance_rejected`. The executive is the only one who can create RESTRICTED content.

### Answer modes

**Q: Why seven modes? Isn't one mode enough?**
A: Real users don't only ask document questions. They greet ("hi"), thank, meta-ask ("summarize our chat"), ask about the system ("what queries has my team run?"), ask off-topic ("what's the atomic weight of hydrogen?"). Treating all of these as grounded RAG produces nonsense answers. Each mode has its own detector that runs before retrieval so we route to the right handler.

**Q: Walk me through the mode decision.**
A: First three short-circuits: is it a greeting → social; is it a system-intel question → system; is it a meta question about chat history → meta. If none, run retrieval. If retrieval passes the relevance bar → grounded. If top chunks span multiple docs with similar scores → disambiguate. If retrieval fails AND a bypass probe finds no higher-clearance match → general (safe world-knowledge answer). If retrieval fails AND a higher-clearance doc matches → refused for L4, unknown for non-L4.

**Q: What's the bypass probe?**
A: A second retrieval pass that ignores the RBAC filter. We use it ONLY to detect whether the user's question could have been answered by a higher-clearance doc. The results never reach the user. It's a routing signal that decides between "unknown" (higher doc exists, don't leak) and "general" (nothing anywhere, safe to answer from world knowledge).

**Q: Why fall back to general knowledge instead of refusing?**
A: User experience. If a guest asks "what's the atomic weight of hydrogen" and we refuse because it's not in the corpus, that's a bad assistant. We fall back to world knowledge with an explicit disclaimer: "This isn't in the provided documents — answering from general knowledge." That's safe because we verified nothing in the corpus (at any clearance) could have answered it.

### Agent layers

**Q: What's the disambiguation layer and why?**
A: When a query could legitimately match multiple documents — for example "HRMS flow" matches both the HRMS Portal technical doc and the HR Policy Handbook — we stop instead of blending. We return a picker card with both candidates and one-line descriptions. The user clicks the one they meant; the query re-runs scoped to that single doc. Prevents the correctness bug where the LLM mixes content from two unrelated docs into one confusing answer.

**Q: How do you detect ambiguity?**
A: After rerank, group top chunks by doc_id, keep each doc's best rerank score. If two or more docs have score ≥ 0.25 AND the gap between the top two is less than 20% of the top score, fire. Otherwise the top doc is clearly winning and we just answer.

**Q: What's the intent mirror?**
A: A small pill above every grounded answer that says "Understood as: <LLM restatement of your query>". Builds trust by showing the agent's interpretation BEFORE the answer streams. User can click the pencil, edit the interpretation, and re-run. The intent LLM call fires in parallel with retrieval — no extra latency.

**Q: What's the confidence chip?**
A: A colored pill next to the answer showing a 0-100 score. Composite of the top rerank score and the faithfulness judge score. Four bands: green ≥80, blue 60-79, amber 40-59, red below 40. Amber and red also show a "Broaden" button that re-runs the query with multi-query fan-out for that call only — catches content the first pass missed without mutating global settings.

**Q: What's thread-scoped memory?**
A: If you ask 2 or more questions about the same document, the system quietly scopes your next queries to that document. Shows a dismissable pill above the chat input. Feels natural — once you're clearly investigating one doc, you don't have to keep re-specifying it. Click the X if you want to broaden again. **Important:** this is frontend-only — the backend is stateless about scope. The React code scans recent turns and includes the doc_id in the next request's filter. See Viva Trap 5 for the full explanation.

**Q: What's the access-request layer?**
A: When an unknown or refused was triggered by RBAC (a higher-clearance doc matched), the bland "no answer" card is replaced by an access-request banner. Users click "Request access", type a reason, submit. An audit row is written that executives can review in the audit tab. Turns a dead end into an actionable path.

### Pipeline Lab

**Q: What's the Pipeline Lab?**
A: A public no-login page at /pipeline where anyone can paste a query and watch the entire RAG pipeline run live. It shows the embedding vector as a heatmap, each retrieval stage's hits, a rank-journey bump chart showing how chunks move through dense, BM25, RRF, and rerank, and the streamed generation. It's a transparent teaching tool — other RAG projects are black boxes; we show the mechanism.

**Q: Why is it public?**
A: Visible proof. Sir doesn't need to sign in to see the system work. The Pipeline Lab is the flagship demo — it's what makes our project stand out. And it uses exec-level visibility internally, which is safe because the corpus is TechNova synthetic data, not real restricted content.

**Q: What's the rank-journey chart?**
A: A bump chart showing each chunk's rank across four stages: Dense, BM25, RRF, Rerank. Chunks that stay in the top 5 all the way through get vivid distinct colors; chunks that started high but fell out are dashed grey. Teaches you exactly WHY reranking matters — you can see the stage where losers fell and winners survived.

### Data + persistence

**Q: What's in the SQLite database?**
A: Five tables. User (username, password hash, role). Document (metadata, classification, per-role hide-list). ChatThread (per-conversation). ChatTurn (every user and assistant message). AuditLog (every query with latency and token counts). All accessed through SQLModel — same schema for Python objects and the database.

**Q: What's stored in Qdrant?**
A: One collection, one point per chunk. Each point has a 384-dim vector and a payload with doc_id, filename, page, section, chunk_index, text, and doc_level. The doc_level is the RBAC gate — Qdrant's filter uses it to exclude above-clearance chunks before returning results.

**Q: How do you chunk a document?**
A: Section-aware with fallback. We split on markdown-style headings if present, otherwise on paragraph boundaries with a target size around 500 tokens and 50-token overlap. Each chunk carries its original section + page so citations are precise.

**Q: How do you handle DOCX page counts?**
A: DOCX files store the real page count in docProps/app.xml under the `<Pages>` tag. We read that and split the text across N pseudo-pages at paragraph boundaries. Without this fix, one paragraph got counted as one page — a 9-page doc reported 280 pages.

### Testing + quality

**Q: How do you know it works?**
A: 38 integration tests cover the core guarantees. 25 for RBAC — every role, every query, no leak. 10 for smart-RAG routing — each answer mode fires correctly. 3 for upload clearance capping.

**Q: Do you test the LLM's answer quality?**
A: Not in automated tests — LLM output is hard to assert on. Runtime we use the faithfulness judge: every grounded answer is scored 0-1 by a second LLM call against the sources. Scores below 0.5 flag an unfaithful answer.

**Q: What's faithfulness and how is it computed?**
A: An LLM-as-judge call. The prompt: "Score how faithful the ANSWER is to the SOURCES from 0.0 to 1.0. 1.0 = every claim supported. 0.0 = hallucinations." Returns a float. We persist it on every grounded turn and show it in analytics. Helps us flag when the model went off the rails.

### Latency + performance

**Q: How fast is a query?**
A: 3-5 seconds end-to-end for a grounded query. Breakdown: embed ~20ms, Qdrant search ~40ms, BM25 ~50ms, rerank ~300ms, LLM streaming start ~800ms, full answer ~2s, faithfulness judge ~1s. The answer starts streaming at ~1 second — feels instant.

**Q: How do you handle slow LLM calls?**
A: Three ways. One: streaming — the user sees tokens as they arrive, not a 5-second wait. Two: parallelism — intent classification runs concurrently with retrieval. Three: caching — identical query + role + doc-filter gets replayed instantly.

**Q: What happens if the LLM times out?**
A: Each LLM call has a timeout with a safe fallback. Intent timeout → skip the pill. Contextualize timeout → use the original query. Corrective timeout → skip the retry. Faithfulness timeout → leave it as -1 (not scored). We never block the real answer on an auxiliary call.

### Production readiness

**Q: Is this production-ready?**
A: Close, but not 100%. Production would need: Postgres instead of SQLite (SQLite is fine for single-server demos, not multi-server), real secrets management (vault instead of .env), proper logging + observability (OpenTelemetry), dockerized deployment, CI/CD, load testing, rate limiting per IP not just per user, and audit log retention policy. Everything else — the RAG pipeline, the RBAC filter, the agent layers, the test suite — is production-quality already.

**Q: How would you scale this to 10,000 users?**
A: The stateless API scales horizontally behind a load balancer. Qdrant has a cluster mode. Move SQLite to Postgres. Put Redis in front of the chat cache. Move BM25 pickles to a shared object store. The biggest scaling cost would be the OpenAI bill — we'd add heavier caching and consider a self-hosted LLM for routine queries.

### Personal + process

**Q: Did you build this all yourself?**
A: I designed the architecture, AI pair-programmed every feature with Claude, and understand every line of the codebase. I can walk you through any file, any function, any decision. Happy to open anything you want to inspect.

**Q: What was hardest?**
A: Making the agent layers feel coherent together. Adding disambiguation on top of RAG is easy; making disambiguation, intent mirror, confidence, thread-scope, and access-request all render in the right order in the right card without visual chaos was a multi-pass integration. The `MessageBubble.tsx` component routes to different sub-cards based on answer mode — getting that state machine right took careful design.

**Q: What would you do differently?**
A: I'd write the frontend state types before building any UI. The ChatMessage type grew organically and had to be retrofitted when each agent layer was added. Starting with a union type like `ChatMessage = GroundedMsg | DisambiguateMsg | SocialMsg | ...` would have been cleaner. Also I'd add a small frontend unit-test layer — just enough to catch state-transition bugs.

**Q: What did you learn?**
A: Three things. One: RBAC belongs at the data layer, not the prompt. Two: intent classification before retrieval is the difference between a "just works" chat and a "sometimes says weird things" chat. Three: visible UI artifacts beat silent heuristics every time — the user believes confidence when they see a chip, not when it's in a log.

---

## 19. 15-minute demo script

Rehearse this aloud twice before the demo so the transitions feel natural.

**Minute 0-1 — Landing page**
*"This is Prism RAG. Before I sign in, let me show you the part that's public."*
Click "Try the Pipeline Lab" in the nav.

**Minute 1-4 — Pipeline Lab** (the wow)
*"This runs without any authentication. Anyone can see how the system works internally. I'll paste a question."*
Paste: `What is the on-call rotation policy?`
*"Watch the system flow diagram pulse as each stage completes. Here's the embedding vector — 384 numbers rendered as a heatmap. The diverging colors show positive vs negative values. Now the dense search returned 10 candidates. BM25 also ran. RRF fused them. Then the reranker produced the top 5. You can see the rank-journey chart — these are the winning chunks in color, the false positives in dashed grey."*
Point at a card. *"Each stage has a Why-it-matters explanation and a theory deep-dive modal if you want the formula."*

**Minute 4-5 — Sign in as exec**
Navigate to /signin, log in as exec/exec_pass.
*"The public Pipeline Lab used exec-level visibility. The real app is behind auth and enforces role-based access control."*

**Minute 5-7 — Grounded chat with all 5 agent layers**
Type: `What is the tech stack of the HRMS portal?`
*"Watch the intent pill appear — 'Understood as: You're asking about the technical stack of the HRMS portal'. That reassures me the agent understood me."*
Answer streams. *"The answer cites [Source 1] and [Source 2]. Below, there's a confidence chip — 85 out of 100, green. If it were amber or red, I'd see a Broaden button."*

Type a second question about the same doc: `What modules does it have?`
*"Notice the scope chip above the composer — 'Following up in HRMS Portal Production Report'. The system detected I'm investigating one doc and quietly scoped new queries to it. I can dismiss it with the X."*

**Minute 7-9 — Disambiguation**
Upload HR Policy Handbook if not already there.
Type: `HRMS flow`
*"Now I'm asking something that could match two different documents. Watch."*
Disambiguation card appears.
*"The system refused to blend the two docs. It's asking me which one I meant, with a one-line hint from each. I'll pick HRMS Portal."*
Click. Answer streams scoped to that doc.
*"Clean answer, strictly from the doc I picked. No cross-contamination."*

**Minute 9-11 — RBAC visible proof**
Sign out. Sign in as `guest`.
*"Guest has the lowest clearance — PUBLIC level 1 only."*
Type: `What is the CEO salary?`
*"Watch the access-request card."*
Unknown card with lock icon + Request access button. Click it, type a reason, submit.
*"The request is logged in the audit trail. A manager can review it."*

**Minute 11-13 — Analytics as exec**
Sign out. Sign in as `exec`.
Navigate to `/app/analytics`.
*"Executive analytics. Donut of answer-mode distribution — you can see disambiguate, grounded, general, unknown, refused. Gauge of average faithfulness. Sankey of who-asks-what. Heatmap of when queries happen. All pulled from the audit log."*

Navigate to `/app/audit`.
*"Audit table — every query, every user. The access request I just submitted shows up here with answer_mode = access_request."*

**Minute 13-14 — Knowledge management**
Go to Chat, open Knowledge sidebar, click the gear on a doc.
*"As exec I can reclassify this document or set per-role visibility. For example, I can publish a CONFIDENTIAL doc to manager but hide it from employee — without changing its level. The system atomically rewrites the Qdrant payload and BM25 pickle metadata, so retrieval picks up the change instantly."*

**Minute 14-15 — Close**
*"That's Prism RAG. Seven answer modes, five agent layers, four-level RBAC enforced at the vector store, a public Pipeline Lab anyone can try, executive analytics + audit, and 38 passing integration tests. The full source is on GitHub. Any questions?"*

---

## 20. One-line summary you can say at the end

*"It's RAG with guardrails — the model only sees what your role allows, the system asks instead of guessing, and every answer comes with a confidence score you can challenge."*

---

## Appendix — Cheat sheet

**Model names (commit to memory):**
- Embedder: `sentence-transformers/all-MiniLM-L6-v2` (384 dims)
- Reranker: `BAAI/bge-reranker-base` (278M params)
- Generator: `gpt-4o-mini` (OpenAI)

**Corpus numbers:**
- 13 documents, 145 chunks (seeded TechNova corpus)
- 38 integration tests passing, 1 skipped

**Ports:**
- Frontend :5173
- Backend :8765 (NOT 8000 — Django servers block it)
- Qdrant :6333

**Agent-layer tuning constants:**
- Disambig score gap: 0.20
- Disambig min top score: 0.25
- Intent LLM timeout: 4s / emission 2s
- Confidence bands: 40 / 60 / 80
- Thread scope lookback: 3 turns, min 2 hits

**Relevance thresholds (RRF-first two-path rule):**
- Strong: RRF ≥ 0.024 OR rerank ≥ 0.30
- Don't drop below RRF 0.024 — calibrated on the TechNova corpus

**If sir catches you off-guard:**
Say *"Great question — let me open the code and show you."* Then navigate to the file. Showing the code is always better than guessing.

**The 5 viva traps — one-line reminders:**
1. **Bypass probe** runs retrieval IGNORING RBAC to decide unknown vs general. Results never shown to user.
2. **"Unknown" not "refused"** for non-L4 = deliberately ambiguous so existence of restricted docs doesn't leak.
3. **"Atomic"** means atomic-at-the-request-boundary, not distributed ACID. Three separate stores, try/except rollback.
4. **gpt-4o-mini** chosen after benchmarking: GPT-5 = 17-40s, Llama 3 CPU = 15s, gpt-4o-mini = 3-5s. Quality ≥ 0.85 faith.
5. **Thread scope is frontend-only.** Backend is stateless; the React code scans recent turns and includes doc_id in the next request filter.

---

**You got this. Rehearse section 19 out loud twice. Skim section 18 once. Memorize section 17.5 COLD — those 5 are the traps sir will probe.**
