# code_docs domain — FastAPI tutorial

## Source

- **Repo:** https://github.com/fastapi/fastapi
- **License:** MIT
- **Files used:**
  - `docs/en/docs/tutorial/path-params.md` → `doc/path-params.md`
  - `docs/en/docs/tutorial/query-params.md` → `doc/query-params.md`
- **Raw URLs:**
  - https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/path-params.md
  - https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/query-params.md
- **Accessed:** 2026-04-22

## Why these two files

Self-contained tutorial pages. Cover distinct concepts (path vs query params) with
concrete code examples, comparison tables, and an explicit Recap section — enough
structural variety to test extraction, comparison, aggregation, and multi-step
reasoning without needing to chunk across many documents.

## Preprocessing

None. Uploaded as-is. The `{* ../../docs_src/... *}` markers in the source
are MkDocs macro directives that don't resolve in raw markdown — they become
noise in the chunks. Left intact to test whether the RAG system can answer
despite non-executable markup (realistic OOD condition).

## Out of scope

- Images referenced via `<img src=...>` tags — RAG system doesn't do vision in
  this harness. Queries avoid asking about screenshots.
