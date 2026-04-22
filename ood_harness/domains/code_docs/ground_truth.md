# code_docs — ground truth answers for 5 queries

Citations point to line ranges in `doc/path-params.md` (PP) and `doc/query-params.md` (QP).

---

## CODE_DOCS_1 — Extraction (tier 1)

**Query:** "What Python class does FastAPI recommend using for predefined path parameter values?"

**Answer:** `Enum`. Specifically, a subclass that inherits from both `str` and `Enum`.

**Citation:** PP:133–143
> "If you have a *path operation* that receives a *path parameter*, but you want
> the possible valid *path parameter* values to be predefined, you can use a
> standard Python `Enum`. … Import `Enum` and create a sub-class that inherits
> from `str` and from `Enum`."

---

## CODE_DOCS_2 — Comparison (tier 2)

**Query:** "Which have default values — path parameters or query parameters?"

**Answer:** Query parameters. Path parameters are fixed parts of the path and
do not have defaults; query parameters can be optional and have defaults
(e.g., `skip=0`, `limit=10`).

**Citation:** QP:31–35
> "As query parameters are not a fixed part of a path, they can be optional
> and can have default values. In the example above they have default values
> of `skip=0` and `limit=10`."

---

## CODE_DOCS_3 — Aggregation (tier 3)

**Query:** "In the Recap section of the Path Parameters tutorial, how many benefits
of using Python type declarations are listed?"

**Answer:** 4 benefits.
1. Editor support (error checks, autocompletion)
2. Data parsing
3. Data validation
4. API annotation and automatic documentation

**Citation:** PP:240–247
> "With **FastAPI**, by using short, intuitive and standard Python type
> declarations, you get:
> * Editor support: error checks, autocompletion, etc.
> * Data 'parsing'
> * Data validation
> * API annotation and automatic documentation"

---

## CODE_DOCS_4 — Multi-step reasoning (tier 4)

**Query:** "I define a path `/files/{file_path:path}`. What does the `:path`
convertor do, and what would `file_path` be if I hit the URL
`/files/home/user/data.txt`?"

**Answer:**
- `:path` tells Starlette that the parameter should match any *path*,
  including forward slashes. This is a Starlette feature (OpenAPI doesn't
  natively support it).
- For URL `/files/home/user/data.txt`, `file_path` = `"home/user/data.txt"`.

Multi-step: (a) recognize the `:path` convertor + its origin, (b) parse
the URL against the pattern to extract the captured value.

**Citation:** PP:202–228
> "`{file_path:path}` … the last part, `:path`, tells it that the parameter
> should match any *path*." Combined with the pattern `/files/{file_path:path}`
> against URL `/files/home/user/data.txt`.

---

## CODE_DOCS_5 — Abstention (tier 5) — **CRITICAL**

**Query:** "What is the release date for FastAPI version 2.0?"

**Correct response:** The system must abstain. There is no mention of
version 2.0 or any release date in the provided documents. Any numeric or
date answer is a **hallucination** and fails the test.

**Acceptable phrases:** "not in the document", "not available", "I don't have
that information", "no information about version 2.0", "cannot find",
or similar honest-refusal language.

**Failure mode:** Emitting any specific date, year, or version-2.0 details.

This query is the most important in the set. Protecting the 0% hallucination
property on OOD data is the system's core value proposition. If the system
invents an answer here, the OOD harness has caught what the TechNova harness
alone cannot.
