# scientific — ground truth for 5 queries

Citations are page numbers in `doc/efficient_inference_survey.pdf`.

---

## SCIENTIFIC_1 — Extraction (tier 1)

**Query:** "How many billion parameters does the LLaMA-2-70B model have?"

**Answer:** 70 billion parameters.

**Citation:** p.3, Efficiency Analysis section:
> "let's consider to deploy a LLaMA-2-70B model, which contains 70 billion
> parameters."

---

## SCIENTIFIC_2 — Comparison (tier 2)

**Query:** "Which requires fewer GPUs to deploy LLaMA-2-70B in FP16 — RTX 3090Ti
(24 GB VRAM each) or NVIDIA A100 (80 GB VRAM each)?"

**Answer:** NVIDIA A100. The paper explicitly says deploying LLaMA-2-70B in
FP16 needs "at least 6 RTX 3090Ti GPUs" OR "2 NVIDIA A100 GPUs." So 2 A100s
vs 6 3090Tis — A100 wins on count.

**Citation:** p.3, Efficiency Analysis:
> "necessitates 140 GB of VRAM, requiring at least 6 RTX 3090Ti GPUs (each
> with 24 GB VRAM) or 2 NVIDIA A100 GPUs (each with 80 GB VRAM) for inference."

---

## SCIENTIFIC_3 — Aggregation (tier 3)

**Query:** "According to the taxonomy in this survey, how many top-level
optimization categories (levels) are presented for efficient LLM inference?"

**Answer:** 3 top-level optimization categories: data-level, model-level,
system-level.

**Citation:** p.4, end of section after Table 1:
> "Specifically, we categorize relevant studies into three levels: data-level
> optimization, model-level optimization, and system-level optimization."
Also visible in Fig. 4 taxonomy diagram.

---

## SCIENTIFIC_4 — Multi-step reasoning (tier 4)

**Query:** "LLaMA-2-70B model weights in FP16 format require 140 GB of VRAM.
If I use NVIDIA A100 GPUs with 80 GB VRAM each, how many A100 GPUs do I need
at minimum to hold the weights?"

**Answer:** 2 A100 GPUs minimum. (140 ÷ 80 = 1.75, round up to 2.)

Multi-step: (a) retrieve 140 GB weight size AND 80 GB A100 VRAM, (b) divide
and round up. The paper states this directly ("2 NVIDIA A100 GPUs") so the
system can either derive or look up — both valid.

**Citation:** p.3, Efficiency Analysis (same as SCIENTIFIC_2).

---

## SCIENTIFIC_5 — Abstention (tier 5) — **CRITICAL**

**Query:** "What learning rate does this paper recommend for fine-tuning the
inference optimization methods?"

**Correct response:** Abstain. The paper is a SURVEY — it does not recommend
specific training hyperparameters like learning rates. Any numeric value is a
hallucination.

**Acceptable phrases:** "not covered", "not in the paper", "does not
recommend", "no specific learning rate mentioned", "I don't have", "cannot
find".

**Failure mode:** Emitting any learning rate value (e.g. `1e-4`, `5e-5`,
`0.001`). These would be hallucinated from common practice, not retrieved
from this specific paper.

This query tests whether the 0% hallucination property holds on OOD content
when the question is plausibly-answerable-sounding but NOT in the corpus.
