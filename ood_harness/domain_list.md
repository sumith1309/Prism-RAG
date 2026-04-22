# OOD harness — 8 domain sourcing plan

Each domain: 1 starter document + 5 queries (one per difficulty tier).
Public / free sources only. No IP conflicts.

---

## 1. Medical / clinical

**Source:** PubMed Central (open-access papers) OR FDA drug approval letters
(https://www.accessdata.fda.gov/scripts/cder/daf/)

**Starter doc candidate:** Any recent clinical trial paper (Phase 3 RCT) from
PMC. Pick one with numeric primary/secondary endpoints.

**Queries (template — fill after picking doc):**
1. Extraction: "What was the primary endpoint of the trial?"
2. Comparison: "Which treatment arm had higher response rate?"
3. Aggregation: "Total patients enrolled across all arms?"
4. Multi-step: "If response rate was X% and we enrolled Y patients, how many responders?"
5. Abstention: "What is the FDA approval status as of [future-date]?" (not in paper)

---

## 2. Legal contracts

**Source:** CUAD dataset (Hugging Face: `theatticusproject/cuad-qa`) — 510
public commercial contracts with annotated clauses.

**Starter doc candidate:** Any service agreement or license agreement from CUAD.

**Queries:**
1. Extraction: "What is the governing law clause?"
2. Comparison: "Is this contract's termination notice longer or shorter than 30 days?"
3. Aggregation: "How many indemnification clauses are referenced?"
4. Multi-step: "If auto-renewal is yes and notice period is X, what's the
   earliest termination date after effective date Y?"
5. Abstention: "Has this contract been renewed in 2025?" (not in contract text)

---

## 3. Scientific papers

**Source:** arXiv (https://arxiv.org) — pick any 2024-2025 AI/ML paper with
experimental tables.

**Starter doc candidate:** A recent LLM benchmarks paper (e.g. MMLU, MATH, HumanEval
results tables) — has clean numeric ground truth.

**Queries:**
1. Extraction: "What was the model's accuracy on HumanEval?"
2. Comparison: "Did the proposed method outperform baseline on MMLU?"
3. Aggregation: "Average score across all 5 benchmarks?"
4. Multi-step: "Which benchmark showed the largest relative improvement
   (proposed - baseline) / baseline?"
5. Abstention: "What are the authors' plans for v2 of the model?" (not in paper)

---

## 4. Financial filings

**Source:** SEC EDGAR (https://www.sec.gov/edgar/) — free public 10-K filings.

**Starter doc candidate:** A recent 10-K for a mid-cap company (~50 pages, avoid
mega-caps that are too long to chunk cleanly for a starter).

**Queries:**
1. Extraction: "What was total revenue for fiscal year?"
2. Comparison: "Did gross margin improve or decline year-over-year?"
3. Aggregation: "Total R&D spend across the 3 years disclosed?"
4. Multi-step: "If revenue grew X% and costs grew Y%, what's the operating
   margin change?"
5. Abstention: "What is the current stock price?" (not in 10-K)

---

## 5. Personal documents

**Source:** Self-generated — create a synthetic set of 5 docs representing a
fictional person (resume, rent agreement, medical record, tax return, credit
card statement). Use ChatGPT to generate believable contents in 15 minutes.

**Starter doc candidate:** A synthetic resume for "Priya Sharma, Senior Data
Analyst, 8 years experience" with specific companies / dates / skills.

**Queries:**
1. Extraction: "What is the most recent role?"
2. Comparison: "Which tenure was longer — company A or company B?"
3. Aggregation: "Total years of experience?"
4. Multi-step: "If salary grew 15% per role across 4 roles, and first salary
   was X, what's current?"
5. Abstention: "What is the person's current marital status?" (not in resume)

---

## 6. Code documentation

**Source:** Pick ONE popular open-source project's docs. Candidates: Django
docs, React docs, FastAPI docs, NumPy docs.

**Starter doc candidate:** FastAPI's "Tutorial" section (single HTML page or
markdown file) — well-structured with clear code examples.

**Queries:**
1. Extraction: "How do you define a path parameter in FastAPI?"
2. Comparison: "What's the difference between `Query` and `Path` parameters?"
3. Aggregation: "How many HTTP methods are supported in the tutorial?"
4. Multi-step: "If I want to validate an integer path param between 1-1000,
   which classes/params do I combine?"
5. Abstention: "What's the roadmap for FastAPI 1.0?" (not in docs)

---

## 7. News archives

**Source:** Kaggle's "All the News" dataset OR BBC News archive (free public).

**Starter doc candidate:** A single 1500-word feature article with clear facts
(e.g. a tech-company acquisition announcement with dates, amounts, executives).

**Queries:**
1. Extraction: "What was the acquisition price?"
2. Comparison: "Was this deal larger than the company's previous acquisition?"
3. Aggregation: "How many executives are named in the article?"
4. Multi-step: "If the deal closes in Q3 and integration takes 18 months, when
   does integration complete?"
5. Abstention: "How did the stock market react the next day?" (not in this article)

---

## 8. Multilingual (Hindi starter, add more later)

**Source:** Indian government bilingual policy docs (digitalindia.gov.in, PIB
press releases) OR Wikipedia Hindi for general knowledge.

**Starter doc candidate:** A Hindi-language policy document (e.g. Digital India
scheme overview) OR a Hindi Wikipedia article on a concrete topic.

**Queries (query asked in Hindi OR English; answer in the same language as
query when possible):**
1. Extraction: "What is the scheme's official launch date?" / "योजना की आधिकारिक शुरुआत कब हुई?"
2. Comparison: [two dates / two budgets]
3. Aggregation: [total beneficiaries]
4. Multi-step: [budget × years]
5. Abstention: [something not in the doc]

---

## Fill order (recommended)

1. **Start with domain 6 (FastAPI docs)** — easiest to source, cleanest format,
   lets you test end-to-end plumbing before harder domains.
2. **Then domain 3 (arXiv paper)** — PDF handling, tables, familiar territory.
3. **Then domain 4 (SEC 10-K)** — your business-analytics strength.
4. **Then domain 8 (Hindi)** — biggest failure risk → earliest signal.
5. **Then 1, 2, 5, 7** — progressively more adversarial.

## What a "populated" domain looks like

Each domain folder (`domains/<name>/`) should contain:
- `source.md` — where the doc came from, license, access date, any preprocessing
- `doc/` — the actual PDF / markdown / text file(s)
- `queries.json` — 5 queries with full `expected` blocks (same schema as
  `../../golden_queries.json`)
- `ground_truth.md` — human-readable reasoning behind each expected answer

Once populated, the domain gets added to the top-level `ood_queries.json`
manifest and the runner picks it up automatically.
