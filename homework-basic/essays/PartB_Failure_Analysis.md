# Part B — Failure Analysis of a Naïve HR-Bot RAG

> **Note to self:** this is a working draft with the technical scaffolding.
> Rewrite in my own voice before submitting — sir grades whether *I* wrote it.
> Target: 500–700 words, four distinct failure modes.

---

## Setup (2–3 sentences)

Imagine a first-pass HR chatbot for TechNova: a single vector index over every
PDF in the HR drive, a top-3 cosine retrieval, and a prompt that says *"answer
the question using this context."* It looks fine in a one-off demo, but the
moment real employees use it, four distinct failure modes appear. Each one
maps to a specific fix we studied in Session 2.

---

## Failure 1 — The bot confidently invents a policy that does not exist

Dense embeddings alone are semantic: if the employee asks *"what is the
paternity-leave policy?"* and TechNova only has a maternity-leave section,
the dense retriever returns the *closest* chunk regardless of whether it
actually answers the question. The LLM, prompted only with "use this context,"
synthesises a plausible-sounding paternity policy that is pure fabrication.

**Fix (from Session 2):** a **grounded prompt** that explicitly instructs the
model to say *"I don't know"* if the sources do not contain the answer, plus
**inline `[Source N]` citations** so the user can verify each claim.
The `[Source N]` constraint changes the incentive: the model can no longer
hallucinate without also inventing a citation, which is easy to spot.

## Failure 2 — Keyword queries fail because the embedding model does not know the jargon

Employees search for internal acronyms, ticket IDs, section numbers, and
tool names (*"ADR-041"*, *"the T5 onboarding checklist"*). A general-purpose
embedding model like MiniLM has never seen those tokens during training, so
all ID-shaped strings collapse to roughly the same vector. Dense retrieval
misses the exact document every time.

**Fix:** **hybrid retrieval** — run dense *and* BM25 in parallel and fuse with
Reciprocal Rank Fusion. BM25 is an exact-term model, so it recovers precisely
the cases dense embeddings miss. This is the behaviour my CLI demonstrates:
on RFC 7519, queries like *"section 4.1.1"* are a BM25 win and queries like
*"how is the signature validated"* are a dense win. A bot without BM25 is
blind to half its users.

## Failure 3 — Stale answers from outdated documents

HR policies change. Last year's travel-reimbursement rate is still sitting in
the index, and cosine similarity does not care which version is newer. The bot
cheerfully returns the 2023 policy to a 2026 query. Worse, the older document
is often *longer* and more specific, so it frequently outranks the current one.

**Fix:** **metadata filtering and freshness-aware re-ranking** — every chunk
carries a `updated_at` timestamp in its payload, and retrieval filters to the
latest version or, at minimum, boosts recent documents in the final ranking.
A cross-encoder re-ranker trained to prefer recent authoritative text is the
stronger version of the same idea.

## Failure 4 — The bot leaks confidential information

The worst failure. An intern asks *"what is the CEO's salary?"* and the bot
retrieves the executive-compensation PDF and summarises it. The naïve system
has no notion of who is asking — every chunk is retrievable by every user.
Putting a disclaimer in the prompt (*"do not reveal confidential info"*) is
not a fix, because the LLM already saw the confidential chunk in its context;
with a clever prompt-injection it will leak.

**Fix:** **RBAC enforced at the vector-store filter layer, not in the prompt.**
Each chunk carries a `doc_level` label derived from the document header
(`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`). Retrieval filters
`doc_level <= user.level` in the `where` clause of the query. The LLM
*physically never sees* any chunk above the user's clearance, so no prompt
injection can exfiltrate it. This is exactly the design I built for HW2.

---

## Closing line (1 sentence)

Each of these four fixes — grounded prompts, hybrid retrieval, freshness
filtering, and DB-layer access control — is a small architectural decision,
but together they are the difference between a demo and a system an HR
department could actually deploy.
