# scientific domain — arXiv survey on efficient LLM inference

## Source

- **Paper:** "A Survey on Efficient Inference for Large Language Models"
- **Authors:** Zixuan Zhou, Xuefei Ning, Ke Hong, Tianyu Fu, Jiaming Xu, Shiyao Li, Yuming Lou, Luning Wang, Zhihang Yuan, Xiuhong Li, Shengen Yan, Guohao Dai, Xiao-Ping Zhang, Huazhong Yang, Yuhan Dong, Yu Wang
- **arXiv ID:** 2404.14294 (v3, 19 Jul 2024)
- **Category:** cs.CL
- **License:** arXiv default (free to download + read for research; attribution required for quotes)
- **PDF URL:** https://arxiv.org/pdf/2404.14294
- **File:** `doc/efficient_inference_survey.pdf` (36 pages, 1.3MB)
- **Accessed:** 2026-04-22

## Why this paper

Non-tabular scientific survey. Has structural variety to test all 5 difficulty
tiers: concrete numbers (70B params, 140 GB VRAM, 100 ms/token), enumerable
taxonomy (3 optimization levels), comparison table (Table 1), multi-step
reasoning (hardware math: 140 GB / 80 GB A100 = 2 GPUs minimum).

Note: the arXiv URL `https://arxiv.org/pdf/2404.14294` was originally expected
to point to Phi-3 Technical Report based on old memory. That ID actually maps
to this efficient-inference survey. For this harness's purposes
(verifying Finding 1 replicates) paper choice is functionally irrelevant — we
need a non-tabular PDF, and this is one.

## Queries drawn from pages 1-5 only

This keeps ground truth verifiable. If future expansion covers later sections
(Sec. 4-6 specific techniques, Sec. 7 applications), add queries incrementally
with their own page-range citations.

## Out of scope

- Figure-only facts (figures 1-4 reference diagrams; no text-retrievable content)
- Equation-specific content (Eq. 1-4) — our retrieval doesn't handle LaTeX math well
- References section — would require cross-paper lookup
