# HW1 — Qdrant CLI RAG (Session 2, Basic)

A single-file Python CLI that indexes a PDF into Qdrant, runs dense (all-MiniLM-L6-v2)
and BM25 retrieval side-by-side with scores, fuses them with Reciprocal Rank Fusion,
assembles a grounded prompt with `[Source N]` citations, and (optionally) calls
`gpt-4o-mini` for the final answer.

## Document
**RFC 7519 — JSON Web Tokens** (auto-downloaded to `data/rfc7519_jwt.pdf`, ~30 pages).
Chosen because an IETF RFC has both exact-term hooks (`section 4.1.1`, `exp`, `RS256`)
where BM25 shines, and explanatory prose where dense embeddings shine — so all three
required screenshots fall out naturally on one document. It is also meta-relevant:
HW2 uses JWT for authentication.

## Chunking choice — 500 chars / 100 overlap
Matches the Session-2 lab notebook default. 500 chars ≈ 80–100 tokens: large enough
to hold one self-contained claim (a claim definition, a validation rule), small enough
that retrieval hits the specific rule instead of a whole section. 20% overlap protects
sentences that straddle a boundary without doubling the index size.

## Dense vs BM25 observations (verified on this PDF)
- **Dense wins** on paraphrased / semantic queries — e.g. *"How is a JWT signature validated?"*
  lands precisely on section 7.2 ("Validating a JWT", page 14). The model knows
  *validated* ≈ *verified* and retrieves the validation flow; BM25 scatters across
  any chunk containing the word "signature".
- **BM25 wins** on proper-noun and literal-token queries — e.g. *"Sakimura"* (one
  of the authors) lands the "Authors' Addresses" chunk on page 30 at rank 1. Dense
  cosine is near-random (≈0.14) because a rare proper noun carries no semantic
  signal the embedding model has ever seen.
- **Both agree** on canonical definition questions — *"What is the exp claim?"*
  is chunk #45 (section 4.1.4) as rank 1 from *both* retrievers, so RRF fusion
  locks it in. This is the case where hybrid retrieval is *free insurance*: no
  regression over either single retriever, guaranteed best result.

## Run it
```bash
./setup.sh              # venv + deps + PDF download + Qdrant on :6333
source .venv/bin/activate
python rag_cli.py       # interactive loop, type "quit" to exit
```

Set `OPENAI_API_KEY` in `.env` (or share with `backend/.env`) to enable generation.

Flags: `--chunk 500 --overlap 100 --top-k 3 --rebuild`.

## Deliverables in this folder
- `rag_cli.py` — the CLI (~300 lines, single file on purpose).
- `screenshots/` — dense-wins, bm25-wins, both-agree (capture after first run).
- `essays/PartB_Failure_Analysis.md` — 500–700-word HR-bot failure analysis.
- `essays/PartC_Access_Control.md` — 300–400-word ethical reflection.
