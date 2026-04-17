"""
Prism RAG Evaluation Script
============================
Evaluates the live Prism RAG backend on 4 RAGAS metrics + RBAC compliance.

Modes:
  python rag_evaluator.py --create-dataset           # generate TechNova ground-truth
  python rag_evaluator.py                            # full RAGAS eval (needs OPENAI_API_KEY)
  python rag_evaluator.py --lightweight              # heuristic eval (no OpenAI needed)
  python rag_evaluator.py --rbac                     # RBAC compliance matrix (all 4 roles)
  python rag_evaluator.py --rbac --lightweight       # RBAC + heuristic combined
  python rag_evaluator.py --format html              # styled HTML report
  python rag_evaluator.py --ci --rbac --lightweight  # CI gate: exit 1 if thresholds breached

Install:
  pip install httpx
  # For full RAGAS eval: pip install ragas langchain-openai datasets
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 1. CONFIGURATION & CONSTANTS
# ---------------------------------------------------------------------------

@dataclass
class EvalConfig:
    base_url: str = "http://127.0.0.1:8765"
    dataset_path: str = "evaluation_dataset.json"
    output_path: str = "rag_eval_results.json"
    judge_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    per_question_details: bool = True
    max_retries: int = 3
    timeout_seconds: int = 120
    rbac_mode: bool = False
    lightweight_mode: bool = False
    output_format: str = "json"  # "json" or "html"
    ci_mode: bool = False
    ci_min_faithfulness: float = 0.75
    ci_rbac_pass_rate: float = 1.0


SEED_USERS = {
    "guest":    {"password": "guest_pass",    "role": "guest",     "level": 1},
    "employee": {"password": "employee_pass", "role": "employee",  "level": 2},
    "manager":  {"password": "manager_pass",  "role": "manager",   "level": 3},
    "exec":     {"password": "exec_pass",     "role": "executive", "level": 4},
}

FILENAME_LEVEL = {
    "TechNova_Training_Compliance.pdf": 1,
    "TechNova_IT_Asset_Policy.pdf": 2,
    "TechNova_OnCall_Runbook.pdf": 2,
    "TechNova_Platform_Architecture.pdf": 2,
    "TechNova_Product_Roadmap_2026.pdf": 3,
    "TechNova_Q4_Financial_Report.pdf": 3,
    "TechNova_Vendor_Contracts.pdf": 3,
    "TechNova_Board_Minutes_Q4.pdf": 4,
    "TechNova_Salary_Structure.pdf": 4,
    "TechNova_Security_Incident_Report.pdf": 4,
}

LEVEL_LABEL = {1: "PUBLIC", 2: "INTERNAL", 3: "CONFIDENTIAL", 4: "RESTRICTED"}


# ---------------------------------------------------------------------------
# 2. BACKEND CLIENT
# ---------------------------------------------------------------------------

def login(username: str, password: str, base_url: str) -> str:
    """Authenticate and return a Bearer token."""
    import httpx
    r = httpx.post(f"{base_url}/api/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def check_connectivity(config: EvalConfig) -> str:
    """Try logging in as exec. Returns token or exits with a clear message."""
    import httpx
    try:
        token = login("exec", "exec_pass", config.base_url)
        print(f"  Connected to {config.base_url}")
        return token
    except httpx.ConnectError:
        print(f"\nBackend not running at {config.base_url}.")
        print("  Start with: cd backend && python -m entrypoint.serve")
        sys.exit(1)
    except Exception as e:
        print(f"\nLogin failed: {e}")
        sys.exit(1)


def query_rag(question: str, token: str, config: EvalConfig) -> dict:
    """
    Call the Prism backend via SSE and collect all events.

    Returns a dict with answer, contexts, sources, answer_mode, latency,
    faithfulness, citation_check, and error status.
    """
    import httpx

    result = {
        "answer": "",
        "contexts": [],
        "sources": [],
        "answer_mode": "",
        "latency_ms": {},
        "faithfulness": -1.0,
        "citation_check": None,
        "cached": False,
        "corrective_retries": 0,
        "error": None,
    }

    timeout = httpx.Timeout(connect=10, read=60, write=10, pool=10)

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                f"{config.base_url}/api/chat",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json={
                    "query": question,
                    "use_rerank": True,
                    "use_faithfulness": True,
                    "use_corrective": True,
                    "top_k": 8,
                },
            ) as response:
                response.raise_for_status()
                cur_event = ""
                for raw_line in response.iter_lines():
                    if not raw_line:
                        cur_event = ""
                        continue
                    line = raw_line if isinstance(raw_line, str) else raw_line.decode()

                    if line.startswith("event:"):
                        cur_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        if not data_str:
                            continue
                        try:
                            payload = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Dispatch on event type
                        if cur_event == "token":
                            result["answer"] += payload.get("delta", "")

                        elif cur_event == "sources":
                            sources = payload.get("sources", [])
                            result["sources"] = sources
                            result["contexts"] = [s.get("text", "") for s in sources]

                        elif cur_event == "answer_reset":
                            # Post-hoc demotion: clear answer AND sources
                            result["answer"] = ""
                            result["contexts"] = []
                            result["sources"] = []

                        elif cur_event == "citation_check":
                            result["citation_check"] = payload

                        elif cur_event == "done":
                            result["answer_mode"] = payload.get("answer_mode", "")
                            result["latency_ms"] = payload.get("latency_ms", {})
                            result["faithfulness"] = payload.get("faithfulness", -1.0)
                            result["cached"] = payload.get("cached", False)
                            result["corrective_retries"] = payload.get("corrective_retries", 0)
                            # citation_check is always in done (may be null for non-grounded)
                            if payload.get("citation_check") and result["citation_check"] is None:
                                result["citation_check"] = payload["citation_check"]

                        elif cur_event == "error":
                            result["error"] = payload.get("message", "unknown error")

    except Exception as e:
        error_type = type(e).__name__
        result["error"] = f"{error_type}: {e}"

    return result


# ---------------------------------------------------------------------------
# 3. TECHNOVA GROUND-TRUTH DATASET
# ---------------------------------------------------------------------------

def create_technova_dataset(path: str = "evaluation_dataset.json") -> list:
    """Generate 30 TechNova evaluation questions spanning all RBAC levels."""
    dataset = [
        # ── L1 PUBLIC: Training & Compliance (3 questions) ────────────
        {
            "question": "What mandatory training must all TechNova employees complete?",
            "ground_truth": "All employees must complete annual compliance training covering data protection, workplace safety, and code of conduct.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "TechNova_Training_Compliance.pdf",
            "expected_mode": "grounded",
            "category": "compliance",
        },
        {
            "question": "What are the consequences for not completing mandatory compliance training at TechNova?",
            "ground_truth": "Failure to complete mandatory training may result in disciplinary action, including suspension of system access and potential termination.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "TechNova_Training_Compliance.pdf",
            "expected_mode": "grounded",
            "category": "compliance",
        },
        {
            "question": "How often is compliance training renewed at TechNova?",
            "ground_truth": "Compliance training is renewed annually. Employees receive reminders 30 days before their certification expires.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "TechNova_Training_Compliance.pdf",
            "expected_mode": "grounded",
            "category": "compliance",
        },
        # ── L2 INTERNAL: IT, OnCall, Architecture (5 questions) ───────
        {
            "question": "What is TechNova's hardware replacement policy for IT assets?",
            "ground_truth": "IT assets are replaced on a 3-year cycle. Employees can request early replacement if the device impacts productivity, subject to manager approval.",
            "ground_truth_contexts": [],
            "min_level": 2,
            "target_doc": "TechNova_IT_Asset_Policy.pdf",
            "expected_mode": "grounded",
            "category": "it_policy",
        },
        {
            "question": "What is TechNova's policy on personal devices connecting to the corporate network?",
            "ground_truth": "Personal devices must be registered with IT, have approved antivirus software, and comply with the mobile device management policy before accessing the corporate network.",
            "ground_truth_contexts": [],
            "min_level": 2,
            "target_doc": "TechNova_IT_Asset_Policy.pdf",
            "expected_mode": "grounded",
            "category": "it_policy",
        },
        {
            "question": "What is the on-call rotation schedule at TechNova?",
            "ground_truth": "On-call rotations are weekly, with primary and secondary responders. Engineers are on-call for one week every 4-6 weeks depending on team size.",
            "ground_truth_contexts": [],
            "min_level": 2,
            "target_doc": "TechNova_OnCall_Runbook.pdf",
            "expected_mode": "grounded",
            "category": "oncall",
        },
        {
            "question": "What is the escalation procedure for a P1 incident at TechNova?",
            "ground_truth": "P1 incidents require immediate page to the on-call engineer, escalation to the engineering manager within 15 minutes, and an incident bridge opened within 30 minutes.",
            "ground_truth_contexts": [],
            "min_level": 2,
            "target_doc": "TechNova_OnCall_Runbook.pdf",
            "expected_mode": "grounded",
            "category": "oncall",
        },
        {
            "question": "Describe TechNova's platform architecture and the main services.",
            "ground_truth": "TechNova's platform is a microservices architecture with API gateway, authentication service, data pipeline, and frontend services deployed on cloud infrastructure.",
            "ground_truth_contexts": [],
            "min_level": 2,
            "target_doc": "TechNova_Platform_Architecture.pdf",
            "expected_mode": "grounded",
            "category": "architecture",
        },
        # ── L3 CONFIDENTIAL: Roadmap, Financial, Vendor (5 questions) ─
        {
            "question": "What are TechNova's planned product features for 2026?",
            "ground_truth": "The 2026 roadmap includes AI-powered analytics, enhanced security features, and international market expansion with multi-language support.",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "TechNova_Product_Roadmap_2026.pdf",
            "expected_mode": "grounded",
            "category": "roadmap",
        },
        {
            "question": "What is the timeline for TechNova's product roadmap milestones in 2026?",
            "ground_truth": "Key milestones are planned for Q1 (beta launch), Q2 (GA release), Q3 (enterprise features), and Q4 (international rollout).",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "TechNova_Product_Roadmap_2026.pdf",
            "expected_mode": "grounded",
            "category": "roadmap",
        },
        {
            "question": "Summarize TechNova's Q4 revenue and financial performance.",
            "ground_truth": "Q4 financial performance showed revenue growth with key metrics including gross margin improvement and operating expense management.",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "TechNova_Q4_Financial_Report.pdf",
            "expected_mode": "grounded",
            "category": "financial",
        },
        {
            "question": "What were TechNova's major expenses in Q4?",
            "ground_truth": "Major Q4 expenses included R&D investment, sales and marketing spend, and infrastructure costs for platform scaling.",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "TechNova_Q4_Financial_Report.pdf",
            "expected_mode": "grounded",
            "category": "financial",
        },
        {
            "question": "What are the key terms in TechNova's vendor contracts?",
            "ground_truth": "Vendor contracts include SLA requirements, data processing agreements, liability caps, and renewal terms with performance-based pricing.",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "TechNova_Vendor_Contracts.pdf",
            "expected_mode": "grounded",
            "category": "vendor",
        },
        # ── L4 RESTRICTED: Board, Salary, Security (5 questions) ──────
        {
            "question": "What were the key decisions from TechNova's Q4 board meeting?",
            "ground_truth": "The Q4 board meeting covered strategic decisions including budget approval, executive appointments, and M&A discussions.",
            "ground_truth_contexts": [],
            "min_level": 4,
            "target_doc": "TechNova_Board_Minutes_Q4.pdf",
            "expected_mode": "grounded",
            "category": "board",
        },
        {
            "question": "What strategic initiatives did the board approve for next year?",
            "ground_truth": "The board approved initiatives including market expansion, technology investment, and organizational restructuring plans.",
            "ground_truth_contexts": [],
            "min_level": 4,
            "target_doc": "TechNova_Board_Minutes_Q4.pdf",
            "expected_mode": "grounded",
            "category": "board",
        },
        {
            "question": "What are the salary bands for engineering roles at TechNova?",
            "ground_truth": "Engineering salary bands are structured by level with defined ranges for each tier from junior to principal engineer.",
            "ground_truth_contexts": [],
            "min_level": 4,
            "target_doc": "TechNova_Salary_Structure.pdf",
            "expected_mode": "grounded",
            "category": "salary",
        },
        {
            "question": "How does TechNova's compensation compare across departments?",
            "ground_truth": "Compensation varies by department with engineering and product roles at the higher end, supported by equity and bonus structures.",
            "ground_truth_contexts": [],
            "min_level": 4,
            "target_doc": "TechNova_Salary_Structure.pdf",
            "expected_mode": "grounded",
            "category": "salary",
        },
        {
            "question": "Describe the November security incident and remediation steps at TechNova.",
            "ground_truth": "The security incident involved unauthorized access, was detected by monitoring systems, and remediation included credential rotation, access review, and infrastructure hardening.",
            "ground_truth_contexts": [],
            "min_level": 4,
            "target_doc": "TechNova_Security_Incident_Report.pdf",
            "expected_mode": "grounded",
            "category": "security",
        },
        # ── RBAC probes (4 questions) — verify access denial ──────────
        {
            "question": "What is the CEO's total compensation package including equity?",
            "ground_truth": "[RBAC PROBE] This question targets L4 restricted salary data.",
            "ground_truth_contexts": [],
            "min_level": 4,
            "target_doc": "TechNova_Salary_Structure.pdf",
            "expected_mode": "grounded",
            "category": "rbac_probe",
        },
        {
            "question": "What was discussed about executive bonuses in the board minutes?",
            "ground_truth": "[RBAC PROBE] This question targets L4 restricted board minutes.",
            "ground_truth_contexts": [],
            "min_level": 4,
            "target_doc": "TechNova_Board_Minutes_Q4.pdf",
            "expected_mode": "grounded",
            "category": "rbac_probe",
        },
        {
            "question": "What is the 2026 product roadmap timeline and budget?",
            "ground_truth": "[RBAC PROBE] This question targets L3 confidential roadmap data.",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "TechNova_Product_Roadmap_2026.pdf",
            "expected_mode": "grounded",
            "category": "rbac_probe",
        },
        {
            "question": "What are the financial projections in TechNova's Q4 report?",
            "ground_truth": "[RBAC PROBE] This question targets L3 confidential financial data.",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "TechNova_Q4_Financial_Report.pdf",
            "expected_mode": "grounded",
            "category": "rbac_probe",
        },
        # ── Out-of-corpus (3 questions) ───────────────────────────────
        {
            "question": "What is TechNova's policy on remote work from Antarctica?",
            "ground_truth": "This information is not available in the TechNova document corpus.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "",
            "expected_mode": "general",
            "category": "out_of_corpus",
        },
        {
            "question": "How does quantum computing affect TechNova's encryption standards?",
            "ground_truth": "This information is not available in the TechNova document corpus.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "",
            "expected_mode": "general",
            "category": "out_of_corpus",
        },
        {
            "question": "What is the airspeed velocity of an unladen swallow?",
            "ground_truth": "This question is completely unrelated to TechNova's document corpus.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "",
            "expected_mode": "general",
            "category": "out_of_corpus",
        },
        # ── Social (2 questions) ──────────────────────────────────────
        {
            "question": "Hello",
            "ground_truth": "[SOCIAL] Greeting — should trigger social mode.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "",
            "expected_mode": "social",
            "category": "social",
        },
        {
            "question": "What can you do?",
            "ground_truth": "[SOCIAL] Capability query — should trigger social mode.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "",
            "expected_mode": "social",
            "category": "social",
        },
        # ── Edge cases (3 questions) ──────────────────────────────────
        {
            "question": "Tell me everything about TechNova",
            "ground_truth": "TechNova is a technology company with policies covering IT, compliance, architecture, and more.",
            "ground_truth_contexts": [],
            "min_level": 1,
            "target_doc": "",
            "expected_mode": "grounded",
            "category": "edge_broad",
        },
        {
            "question": "What are TechNova's training requirements, IT asset policy, and on-call procedures?",
            "ground_truth": "A compound question spanning training compliance, IT asset management, and on-call rotation procedures.",
            "ground_truth_contexts": [],
            "min_level": 2,
            "target_doc": "",
            "expected_mode": "grounded",
            "category": "edge_compound",
        },
        {
            "question": "Compare TechNova's Q4 financial performance with the product roadmap investments.",
            "ground_truth": "Q4 financials and roadmap investments are related through R&D budget allocation and projected returns.",
            "ground_truth_contexts": [],
            "min_level": 3,
            "target_doc": "",
            "expected_mode": "grounded",
            "category": "edge_cross_doc",
        },
    ]

    with open(path, "w") as f:
        json.dump(dataset, f, indent=2)

    print(f"  Created {len(dataset)} evaluation questions at: {path}")
    print(f"    L1 PUBLIC:      3 grounded")
    print(f"    L2 INTERNAL:    5 grounded")
    print(f"    L3 CONFIDENTIAL:5 grounded")
    print(f"    L4 RESTRICTED:  5 grounded")
    print(f"    RBAC probes:    4")
    print(f"    Out-of-corpus:  3")
    print(f"    Social:         2")
    print(f"    Edge cases:     3")
    print(f"\n  Edit ground_truth fields with real answers from your PDFs for best RAGAS accuracy.\n")
    return dataset


def load_dataset(path: str) -> list:
    """Load the evaluation dataset from JSON."""
    if not Path(path).exists():
        print(f"  Dataset not found at '{path}'. Creating...")
        return create_technova_dataset(path)
    with open(path) as f:
        data = json.load(f)
    print(f"  Loaded {len(data)} evaluation pairs from {path}")
    return data


# ---------------------------------------------------------------------------
# 4. EVALUATION RUNNERS
# ---------------------------------------------------------------------------

def collect_rag_responses(dataset: list, token: str, config: EvalConfig) -> list:
    """Run each question through the RAG pipeline and collect responses."""
    enriched = []
    total = len(dataset)

    print(f"\n{'='*60}")
    print(f"  Running {total} queries through Prism RAG...")
    print(f"{'='*60}\n")

    for i, item in enumerate(dataset, 1):
        question = item["question"]
        print(f"  [{i:2d}/{total}] {question[:65]}{'...' if len(question) > 65 else ''}")

        start = time.time()
        result = query_rag(question, token, config)
        elapsed = time.time() - start

        enriched.append({
            **item,
            "answer": result["answer"],
            "contexts": result["contexts"],
            "sources": result["sources"],
            "answer_mode": result["answer_mode"],
            "latency_ms": result["latency_ms"],
            "latency_seconds": round(elapsed, 3),
            "faithfulness": result["faithfulness"],
            "citation_check": result["citation_check"],
            "cached": result["cached"],
            "corrective_retries": result["corrective_retries"],
            **({"error": result["error"]} if result["error"] else {}),
        })

        mode = result["answer_mode"] or "?"
        n_ctx = len(result["contexts"])
        faith = result["faithfulness"]
        faith_str = f"faith={faith:.2f}" if faith >= 0 else "faith=n/a"
        err = " ERROR" if result["error"] else ""
        print(f"           [{mode}] {n_ctx} chunks, {elapsed:.1f}s, {faith_str}{err}")

    succeeded = sum(1 for e in enriched if "error" not in e)
    print(f"\n  Done: {succeeded}/{total} succeeded\n")
    return enriched


# ── RBAC compliance ───────────────────────────────────────────────────────

def check_chunk_leak(sources: list, user_level: int) -> list:
    """Check if any returned source chunk comes from a doc above user's clearance."""
    violations = []
    for src in sources:
        filename = src.get("filename", "")
        doc_level = FILENAME_LEVEL.get(filename, 1)
        if doc_level > user_level:
            violations.append({
                "filename": filename,
                "doc_level": doc_level,
                "user_level": user_level,
                "chunk_preview": src.get("text", "")[:100],
            })
    return violations


def check_rbac_compliance(result: dict, user_level: int, question_meta: dict) -> dict:
    """Two-column pass/fail: RBAC (security) vs Quality (retrieval)."""
    expected_mode = question_meta["expected_mode"]
    min_level = question_meta["min_level"]
    actual_mode = result["answer_mode"]

    # --- RBAC pass (security) ---
    leak_violations = check_chunk_leak(result.get("sources", []), user_level)
    rbac_pass = len(leak_violations) == 0

    if user_level < min_level and user_level < 4:
        # Non-exec below clearance: must NOT see "refused" (leaks doc existence)
        rbac_pass = rbac_pass and actual_mode != "refused"

    # --- Quality pass (retrieval) ---
    if user_level >= min_level:
        # Authorized user — should get expected mode
        quality_pass = actual_mode == expected_mode
    elif expected_mode in ("general", "social"):
        # Out-of-corpus / social — mode should match for any role
        quality_pass = actual_mode == expected_mode
    else:
        # User below clearance — "unknown" is the expected outcome
        quality_pass = actual_mode == "unknown"

    violation = ""
    if not rbac_pass:
        if leak_violations:
            violation = f"CHUNK LEAK: {leak_violations[0]['filename']} (L{leak_violations[0]['doc_level']}) to L{user_level} user"
        else:
            violation = f"non-L4 user saw '{actual_mode}' mode (expected 'unknown')"
    elif not quality_pass:
        if user_level >= min_level:
            violation = f"authorized user expected '{expected_mode}', got '{actual_mode}'"
        elif expected_mode in ("general", "social"):
            violation = f"expected '{expected_mode}', got '{actual_mode}'"
        else:
            violation = f"sub-clearance user (L{user_level}<L{min_level}) expected 'unknown', got '{actual_mode}'"

    return {
        "rbac_pass": rbac_pass,
        "quality_pass": quality_pass,
        "leaked_chunks": leak_violations,
        "violation": violation,
    }


def run_rbac_evaluation(dataset: list, config: EvalConfig) -> dict:
    """Run every question as all 4 roles. Returns compliance matrix."""
    roles = ["guest", "employee", "manager", "exec"]

    # Login all users
    tokens = {}
    for username, creds in SEED_USERS.items():
        tokens[username] = login(username, creds["password"], config.base_url)
    print(f"  Logged in as: {', '.join(roles)}")

    total = len(dataset) * len(roles)
    print(f"\n{'='*60}")
    print(f"  RBAC Compliance Test: {len(dataset)} questions x {len(roles)} roles = {total} queries")
    print(f"{'='*60}\n")

    matrix = []
    all_failures = []
    rbac_passed = 0
    rbac_failed = 0
    quality_passed = 0
    quality_failed = 0
    total_leaks = 0
    # Root-cause counters for quality misses
    authorized_total = 0       # queries where user has clearance
    authorized_quality_pass = 0
    miss_retrieval_failure = 0  # authorized user got general/unknown (retrieval missed)
    miss_sub_clearance = 0      # sub-clearance user got grounded from public chunks (correct behavior)
    miss_mode_mismatch = 0      # other mode mismatches (disambiguate, etc.)
    idx = 0

    for item in dataset:
        question = item["question"]
        q_short = question[:55] + ("..." if len(question) > 55 else "")
        print(f"  Q: {q_short}")

        row = {
            "question": question,
            "min_level": item["min_level"],
            "target_doc": item.get("target_doc", ""),
            "expected_mode": item["expected_mode"],
            "category": item.get("category", ""),
            "results": {},
        }

        for username in roles:
            idx += 1
            level = SEED_USERS[username]["level"]
            result = query_rag(question, tokens[username], config)
            compliance = check_rbac_compliance(result, level, item)

            row["results"][username] = {
                "mode": result["answer_mode"],
                "rbac_pass": compliance["rbac_pass"],
                "quality_pass": compliance["quality_pass"],
                "leaked_chunks": compliance["leaked_chunks"],
                "violation": compliance["violation"],
            }

            if compliance["rbac_pass"]:
                rbac_passed += 1
            else:
                rbac_failed += 1
            if compliance["quality_pass"]:
                quality_passed += 1
            else:
                quality_failed += 1
            total_leaks += len(compliance["leaked_chunks"])

            # Root-cause tracking
            min_level = item["min_level"]
            actual_mode = result["answer_mode"]
            expected_mode = item["expected_mode"]
            if level >= min_level:
                authorized_total += 1
                if compliance["quality_pass"]:
                    authorized_quality_pass += 1
                elif actual_mode in ("general", "unknown"):
                    miss_retrieval_failure += 1
                else:
                    miss_mode_mismatch += 1
            elif not compliance["quality_pass"]:
                if actual_mode == "grounded":
                    miss_sub_clearance += 1  # answered from public chunks
                else:
                    miss_mode_mismatch += 1

            if not compliance["rbac_pass"] or not compliance["quality_pass"]:
                all_failures.append({
                    "question": question,
                    "user": username,
                    "level": level,
                    "expected_mode": item["expected_mode"],
                    "actual_mode": result["answer_mode"],
                    "rbac_pass": compliance["rbac_pass"],
                    "quality_pass": compliance["quality_pass"],
                    "violation": compliance["violation"],
                })

            # Status indicators
            r_icon = "+" if compliance["rbac_pass"] else "X"
            q_icon = "+" if compliance["quality_pass"] else "-"
            mode = result["answer_mode"] or "?"
            print(f"     {username:8s} (L{level}): [{mode:8s}] rbac={r_icon} quality={q_icon}")

            time.sleep(1)  # Rate limit: 60/min/user

        matrix.append(row)
        print()

    # Print summary
    auth_rate = authorized_quality_pass / max(authorized_total, 1)
    print(f"{'='*60}")
    print(f"  RBAC COMPLIANCE SUMMARY")
    print(f"{'='*60}")
    print(f"  Total tests:     {total}")
    print(f"  RBAC passed:     {rbac_passed}/{total} {'(CLEAN)' if rbac_failed == 0 else 'FAILURES FOUND'}")
    print(f"  Quality passed:  {quality_passed}/{total}")
    print(f"  Chunk leaks:     {total_leaks} {'(NONE)' if total_leaks == 0 else 'CRITICAL'}")
    print(f"\n  Authorized-user quality: {authorized_quality_pass}/{authorized_total} ({auth_rate:.1%})")
    print(f"\n  Quality miss root causes:")
    print(f"    Retrieval failures (authorized user, got general/unknown): {miss_retrieval_failure}")
    print(f"    Sub-clearance grounded (answered from public chunks):     {miss_sub_clearance}")
    print(f"    Mode mismatch (disambiguate, etc.):                      {miss_mode_mismatch}")

    if all_failures:
        # Only show security failures and retrieval failures (skip sub-clearance noise)
        security_failures = [f for f in all_failures if not f["rbac_pass"]]
        retrieval_failures = [f for f in all_failures if f["rbac_pass"] and f["quality_pass"] is False
                              and f["level"] >= FILENAME_LEVEL.get(f.get("target_doc", ""), f.get("min_level", 1))
                              if f.get("actual_mode") in ("general", "unknown")]
        if security_failures:
            print(f"\n  SECURITY FAILURES:")
            for f in security_failures:
                print(f"    {f['user']}(L{f['level']}): {f['question'][:50]}...")
                print(f"             {f['violation']}")
        if retrieval_failures:
            print(f"\n  RETRIEVAL FAILURES (authorized user got wrong mode):")
            for f in retrieval_failures:
                print(f"    {f['user']}(L{f['level']}): {f['question'][:50]}...")
                print(f"             {f['violation']}")

    return {
        "summary": {
            "total_tests": total,
            "rbac_passed": rbac_passed,
            "rbac_failed": rbac_failed,
            "quality_passed": quality_passed,
            "quality_failed": quality_failed,
            "chunk_leaks": total_leaks,
            "authorized_total": authorized_total,
            "authorized_quality_pass": authorized_quality_pass,
            "authorized_quality_rate": round(auth_rate, 3),
            "miss_retrieval_failure": miss_retrieval_failure,
            "miss_sub_clearance": miss_sub_clearance,
            "miss_mode_mismatch": miss_mode_mismatch,
        },
        "failures": all_failures,
        "matrix": matrix,
        "chunk_leak_audit": {
            "total_checked": total,
            "leaks_found": total_leaks,
        },
    }


# ── Lightweight evaluation ────────────────────────────────────────────────

def run_lightweight_evaluation(enriched_data: list) -> dict:
    """
    Heuristic eval using backend-native signals + word overlap.
    Works WITHOUT RAGAS or OpenAI.
    """
    print(f"\n{'='*60}")
    print(f"  LIGHTWEIGHT EVALUATION")
    print(f"{'='*60}\n")

    results = []
    for item in enriched_data:
        if "error" in item:
            continue

        question = item["question"].lower()
        answer = item["answer"].lower()
        contexts = " ".join(item.get("contexts", [])).lower()
        ground_truth = item["ground_truth"].lower()

        # Heuristic: answer relevancy (word overlap with question)
        stop = {"what", "how", "why", "is", "the", "a", "an", "of", "to", "in",
                "for", "do", "does", "can", "are", "at", "and", "or", "this", "that"}
        q_words = set(question.split()) - stop
        a_words = set(answer.split())
        relevancy = len(q_words & a_words) / max(len(q_words), 1)

        # Heuristic: faithfulness (answer words found in context)
        content_stop = {"the", "a", "an", "is", "are", "was", "were", "it",
                        "to", "of", "in", "for", "and", "or", "be", "has", "have"}
        a_content = set(answer.split()) - content_stop
        faith_heuristic = sum(1 for w in a_content if w in contexts) / max(len(a_content), 1) if a_content else 0.0

        # Heuristic: ground truth overlap
        gt_words = set(ground_truth.split()) - content_stop
        gt_overlap = len(gt_words & a_words) / max(len(gt_words), 1) if gt_words else 0.0

        # Backend-native signals
        backend_faith = item.get("faithfulness", -1.0)
        cite_check = item.get("citation_check")
        # Only count citation score when citations actually exist (total > 0)
        cite_score = cite_check.get("score", -1) if cite_check and cite_check.get("total", 0) > 0 else -1

        results.append({
            "question": item["question"],
            "answer_mode": item.get("answer_mode", ""),
            "relevancy_heuristic": round(relevancy, 3),
            "faithfulness_heuristic": round(faith_heuristic, 3),
            "ground_truth_overlap": round(gt_overlap, 3),
            "backend_faithfulness": round(backend_faith, 3) if backend_faith >= 0 else None,
            "citation_score": round(cite_score, 3) if cite_score >= 0 else None,
            "latency_seconds": item.get("latency_seconds", -1),
        })

    if not results:
        print("  No valid responses to evaluate.")
        return {"lightweight_results": []}

    # Aggregate
    def avg(key):
        vals = [r[key] for r in results if r[key] is not None and r[key] >= 0]
        return round(sum(vals) / len(vals), 3) if vals else None

    # Mode distribution
    mode_dist = {}
    for r in results:
        m = r.get("answer_mode", "unknown")
        mode_dist[m] = mode_dist.get(m, 0) + 1

    # Latency stats
    latencies = [r["latency_seconds"] for r in results if r["latency_seconds"] > 0]
    latency_stats = {}
    if latencies:
        latencies_sorted = sorted(latencies)
        latency_stats = {
            "mean": round(sum(latencies) / len(latencies), 3),
            "min": round(min(latencies), 3),
            "max": round(max(latencies), 3),
            "p95": round(latencies_sorted[int(len(latencies_sorted) * 0.95)], 3),
        }

    # Backend latency breakdown
    backend_latency = {"retrieve": [], "rerank": [], "generate": [], "total": []}
    for item in enriched_data:
        lms = item.get("latency_ms", {})
        for k in backend_latency:
            v = lms.get(k)
            if v is not None and v > 0:
                backend_latency[k].append(v)

    backend_latency_stats = {}
    for k, vals in backend_latency.items():
        if vals:
            vals_sorted = sorted(vals)
            backend_latency_stats[k] = {
                "mean_ms": round(sum(vals) / len(vals)),
                "p50_ms": round(vals_sorted[len(vals_sorted) // 2]),
                "p95_ms": round(vals_sorted[int(len(vals_sorted) * 0.95)]),
            }

    print(f"  Relevancy (heuristic):      {avg('relevancy_heuristic')}")
    print(f"  Faithfulness (heuristic):    {avg('faithfulness_heuristic')}")
    print(f"  Ground truth overlap:        {avg('ground_truth_overlap')}")
    print(f"  Backend faithfulness (avg):  {avg('backend_faithfulness')}")
    print(f"  Citation accuracy (avg):     {avg('citation_score')}")

    print(f"\n  Answer mode distribution:")
    for mode, count in sorted(mode_dist.items(), key=lambda x: -x[1]):
        bar = "#" * count
        print(f"    {mode:12s} {bar} ({count})")

    if latency_stats:
        print(f"\n  Latency: mean={latency_stats['mean']}s, p95={latency_stats['p95']}s")

    if backend_latency_stats:
        print(f"\n  Pipeline latency breakdown:")
        for stage, stats in backend_latency_stats.items():
            print(f"    {stage:10s}  mean={stats['mean_ms']}ms  p50={stats['p50_ms']}ms  p95={stats['p95_ms']}ms")

    return {
        "lightweight_results": results,
        "aggregate": {
            "relevancy_heuristic": avg("relevancy_heuristic"),
            "faithfulness_heuristic": avg("faithfulness_heuristic"),
            "ground_truth_overlap": avg("ground_truth_overlap"),
            "backend_faithfulness": avg("backend_faithfulness"),
            "citation_score": avg("citation_score"),
        },
        "answer_mode_distribution": mode_dist,
        "latency": latency_stats,
        "backend_latency": backend_latency_stats,
    }


# ── Full RAGAS evaluation ────────────────────────────────────────────────

def run_ragas_evaluation(enriched_data: list, config: EvalConfig) -> dict:
    """Run RAGAS metrics on grounded responses. Requires OpenAI."""
    try:
        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        )
        from ragas import EvaluationDataset, SingleTurnSample
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
    except ImportError:
        print("\n  RAGAS not installed. Install with:")
        print("    pip install ragas langchain-openai datasets")
        sys.exit(1)

    # Filter to grounded-mode responses only
    valid = [d for d in enriched_data if d.get("answer_mode") == "grounded" and "error" not in d]
    if not valid:
        print("  No grounded responses to evaluate with RAGAS.")
        return {}

    print(f"\n{'='*60}")
    print(f"  RAGAS EVALUATION ({len(valid)} grounded responses)")
    print(f"  Judge model: {config.judge_model}")
    print(f"  Note: N={len(valid)} — moderate sample, metric variance ~0.05")
    print(f"{'='*60}\n")

    samples = []
    for item in valid:
        sample = SingleTurnSample(
            user_input=item["question"],
            response=item["answer"],
            retrieved_contexts=item["contexts"],
            reference=item["ground_truth"],
            **({"reference_contexts": item["ground_truth_contexts"]}
               if item.get("ground_truth_contexts") else {}),
        )
        samples.append(sample)

    eval_dataset = EvaluationDataset(samples=samples)

    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    judge_llm = LangchainLLMWrapper(ChatOpenAI(model=config.judge_model))
    judge_embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=config.embedding_model)
    )

    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    results = evaluate(
        dataset=eval_dataset,
        metrics=metrics,
        llm=judge_llm,
        embeddings=judge_embeddings,
    )

    return results


# ---------------------------------------------------------------------------
# 5. OUTPUT FORMATTING & DIAGNOSIS
# ---------------------------------------------------------------------------

def format_score(score: float) -> str:
    if score >= 0.8:
        return f"[GOOD]  {score:.3f}"
    elif score >= 0.6:
        return f"[OK]    {score:.3f}"
    else:
        return f"[LOW]   {score:.3f}"


def format_results(ragas_results, enriched_data: list, config: EvalConfig,
                   lightweight_results: Optional[dict] = None,
                   rbac_results: Optional[dict] = None) -> dict:
    """Format and display all evaluation results."""

    print(f"\n{'='*60}")
    print(f"  PRISM RAG EVALUATION RESULTS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    output = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "base_url": config.base_url,
            "mode": "rbac" if config.rbac_mode else ("lightweight" if config.lightweight_mode else "ragas"),
            "judge_model": config.judge_model if not config.lightweight_mode else "n/a",
            "num_questions": len(enriched_data),
        },
    }

    # RAGAS aggregate scores
    aggregate = {}
    if ragas_results and hasattr(ragas_results, "get"):
        metric_names = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
        for metric in metric_names:
            score = ragas_results.get(metric)
            if score is not None:
                aggregate[metric] = round(score, 4)
                label = metric.replace("_", " ").title()
                print(f"  {label:.<35} {format_score(score)}")

        valid_scores = [v for v in aggregate.values()]
        if valid_scores:
            overall = sum(valid_scores) / len(valid_scores)
            aggregate["overall"] = round(overall, 4)
            print(f"\n  {'Overall':.<35} {format_score(overall)}")

        # RAGAS vs backend faithfulness comparison
        ragas_vs_backend = []
        try:
            df = ragas_results.to_pandas()
            grounded = [d for d in enriched_data if d.get("answer_mode") == "grounded" and "error" not in d]
            for i, row in df.iterrows():
                if i < len(grounded):
                    r_faith = row.get("faithfulness", 0)
                    b_faith = grounded[i].get("faithfulness", -1)
                    if b_faith >= 0:
                        ragas_vs_backend.append({
                            "question": grounded[i]["question"][:80],
                            "ragas_faithfulness": round(r_faith, 3),
                            "backend_faithfulness": round(b_faith, 3),
                            "delta": round(abs(r_faith - b_faith), 3),
                        })
        except Exception:
            pass

        if ragas_vs_backend:
            avg_delta = sum(r["delta"] for r in ragas_vs_backend) / len(ragas_vs_backend)
            print(f"\n  RAGAS vs Backend faithfulness: avg delta = {avg_delta:.3f}")
            output["ragas_vs_backend"] = ragas_vs_backend

        # Per-question breakdown
        per_question = []
        if config.per_question_details:
            try:
                df = ragas_results.to_pandas()
                print(f"\n{'_'*60}")
                print(f"  Per-question breakdown:")
                print(f"{'_'*60}")
                for i, row in df.iterrows():
                    q = row.get("user_input", "")[:50]
                    f_val = round(row.get("faithfulness", 0), 3)
                    r_val = round(row.get("answer_relevancy", 0), 3)
                    p_val = round(row.get("context_precision", 0), 3)
                    c_val = round(row.get("context_recall", 0), 3)
                    per_question.append({
                        "question": row.get("user_input", ""),
                        "faithfulness": f_val,
                        "answer_relevancy": r_val,
                        "context_precision": p_val,
                        "context_recall": c_val,
                    })
                    print(f"\n  Q: {q}{'...' if len(q) >= 50 else ''}")
                    print(f"     Faith={f_val:.3f}  Rel={r_val:.3f}  Prec={p_val:.3f}  Rec={c_val:.3f}")
            except Exception:
                pass

        output["aggregate_scores"] = aggregate
        output["per_question_ragas"] = per_question

    # Lightweight results
    if lightweight_results:
        output["lightweight"] = lightweight_results

    # Backend-native metrics
    grounded_items = [d for d in enriched_data if d.get("answer_mode") == "grounded" and "error" not in d]
    if grounded_items:
        faiths = [d["faithfulness"] for d in grounded_items if d.get("faithfulness", -1) >= 0]
        cites = [d["citation_check"]["score"] for d in grounded_items
                 if d.get("citation_check") and d["citation_check"].get("total", 0) > 0]
        cached = sum(1 for d in enriched_data if d.get("cached"))

        output["backend_metrics"] = {
            "avg_faithfulness": round(sum(faiths) / len(faiths), 3) if faiths else None,
            "citation_accuracy": round(sum(cites) / len(cites), 3) if cites else None,
            "cache_hit_rate": round(cached / len(enriched_data), 3) if enriched_data else 0,
        }

    # Mode distribution
    mode_dist = {}
    for d in enriched_data:
        m = d.get("answer_mode", "unknown")
        mode_dist[m] = mode_dist.get(m, 0) + 1
    output["answer_mode_distribution"] = mode_dist

    # RBAC matrix
    output["rbac_matrix"] = rbac_results

    # Raw responses
    output["raw_responses"] = enriched_data

    # Diagnosis
    print(f"\n{'='*60}")
    print(f"  DIAGNOSIS")
    print(f"{'='*60}\n")
    diagnose(aggregate, lightweight_results, rbac_results)

    return output


def diagnose(scores: dict, lightweight: Optional[dict] = None,
             rbac: Optional[dict] = None):
    """Print actionable recommendations based on scores."""
    recommendations = []

    faith = scores.get("faithfulness", 1)
    if faith < 0.7:
        recommendations.append(
            "LOW FAITHFULNESS — LLM generates claims not in the context.\n"
            "    -> Tighten the system prompt: 'Only answer from provided context.'\n"
            "    -> Reduce temperature to 0.0-0.1\n"
            "    -> The anti-inference prompt hardening may need strengthening"
        )

    relevancy = scores.get("answer_relevancy", 1)
    if relevancy < 0.7:
        recommendations.append(
            "LOW ANSWER RELEVANCY — Answers don't address the questions well.\n"
            "    -> Check if retrieved context is noisy (fix retrieval first)\n"
            "    -> The compound decomposition may be splitting incorrectly\n"
            "    -> Try adjusting the system prompt"
        )

    precision = scores.get("context_precision", 1)
    if precision < 0.7:
        recommendations.append(
            "LOW CONTEXT PRECISION — Retrieved chunks include irrelevant content.\n"
            "    -> Reduce chunk size (currently 500, try 300-400)\n"
            "    -> The bge-reranker-large should help — verify it's loaded\n"
            "    -> Check chunk enrichment (contextual retrieval prefix)"
        )

    recall = scores.get("context_recall", 1)
    if recall < 0.7:
        recommendations.append(
            "LOW CONTEXT RECALL — Retrieval misses relevant information.\n"
            "    -> Increase top_k (currently 8, try 10-12)\n"
            "    -> Enable multi-query mode for broader recall\n"
            "    -> Check table-aware chunking for tabular data"
        )

    # Lightweight-specific
    if lightweight:
        agg = lightweight.get("aggregate", {})
        bf = agg.get("backend_faithfulness")
        if bf is not None and bf < 0.7:
            recommendations.append(
                f"LOW BACKEND FAITHFULNESS ({bf:.3f}) — Built-in verifier scores low.\n"
                "    -> The LLM may be hallucinating beyond the provided chunks\n"
                "    -> Check citation verification for fabricated references"
            )

    # RBAC-specific
    if rbac:
        summary = rbac.get("summary", {})
        if summary.get("rbac_failed", 0) > 0:
            recommendations.append(
                f"RBAC SECURITY FAILURE — {summary['rbac_failed']} tests failed.\n"
                "    -> Check chunk leak audit for leaked documents\n"
                "    -> Verify Qdrant doc_level filter is applied correctly\n"
                "    -> Non-L4 users should NEVER see 'refused' mode"
            )
        if summary.get("chunk_leaks", 0) > 0:
            recommendations.append(
                f"CRITICAL: {summary['chunk_leaks']} CHUNK LEAKS DETECTED.\n"
                "    -> Restricted documents are being returned to unauthorized users\n"
                "    -> This is a security vulnerability — fix immediately"
            )

    if not recommendations:
        print("  All metrics look healthy.")
        if scores:
            print("  To push further, focus on the lowest-scoring metric.")
    else:
        for rec in recommendations:
            print(f"  {rec}\n")


# ---------------------------------------------------------------------------
# 6. HTML REPORT GENERATOR
# ---------------------------------------------------------------------------

def generate_html_report(output: dict, path: str):
    """Generate a styled single-file HTML report."""
    ts = output.get("timestamp", "")
    config = output.get("config", {})
    aggregate = output.get("aggregate_scores", {})
    lightweight = output.get("lightweight", {})
    backend = output.get("backend_metrics", {})
    mode_dist = output.get("answer_mode_distribution", {})
    rbac = output.get("rbac_matrix")
    ragas_vs = output.get("ragas_vs_backend", [])
    lw_agg = lightweight.get("aggregate", {}) if lightweight else {}
    lw_latency = lightweight.get("backend_latency", {}) if lightweight else {}

    def score_color(val):
        if val is None:
            return "#999"
        if val >= 0.8:
            return "#16a34a"
        if val >= 0.6:
            return "#ca8a04"
        return "#dc2626"

    def score_card(label, val):
        if val is None:
            display = "N/A"
            color = "#999"
        else:
            display = f"{val:.3f}"
            color = score_color(val)
        return f'<div class="card"><div class="card-val" style="color:{color}">{display}</div><div class="card-label">{label}</div></div>'

    # Build score cards
    cards_html = ""
    if aggregate:
        for k in ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "overall"]:
            if k in aggregate:
                cards_html += score_card(k.replace("_", " ").title(), aggregate[k])
    elif lw_agg:
        for k, label in [("backend_faithfulness", "Backend Faithfulness"),
                          ("citation_score", "Citation Accuracy"),
                          ("relevancy_heuristic", "Relevancy (heuristic)"),
                          ("ground_truth_overlap", "GT Overlap")]:
            cards_html += score_card(label, lw_agg.get(k))

    # Backend metrics
    backend_html = ""
    if backend:
        for k, v in backend.items():
            if v is not None:
                label = k.replace("_", " ").title()
                backend_html += f'<div class="stat">{label}: <b>{v:.3f}</b></div>'

    # Mode distribution bars
    mode_html = ""
    max_count = max(mode_dist.values()) if mode_dist else 1
    for mode, count in sorted(mode_dist.items(), key=lambda x: -x[1]):
        pct = count / max_count * 100
        mode_html += f'<div class="bar-row"><span class="bar-label">{mode}</span><div class="bar" style="width:{pct}%">{count}</div></div>'

    # Latency breakdown
    latency_html = ""
    if lw_latency:
        for stage, stats in lw_latency.items():
            mean = stats.get("mean_ms", 0)
            p95 = stats.get("p95_ms", 0)
            latency_html += f'<tr><td>{stage}</td><td>{mean}ms</td><td>{stats.get("p50_ms", 0)}ms</td><td>{p95}ms</td></tr>'

    # RBAC matrix table
    rbac_html = ""
    if rbac:
        summary = rbac.get("summary", {})
        rbac_html += f'<div class="section"><h2>RBAC Compliance</h2>'
        rbac_html += f'<div class="stats-row">'
        rbac_html += f'<div class="stat">Tests: <b>{summary.get("total_tests", 0)}</b></div>'
        leak_count = summary.get("chunk_leaks", 0)
        rbac_color = "#16a34a" if summary.get("rbac_failed", 0) == 0 else "#dc2626"
        rbac_html += f'<div class="stat" style="color:{rbac_color}">RBAC Pass: <b>{summary.get("rbac_passed", 0)}/{summary.get("total_tests", 0)}</b></div>'
        rbac_html += f'<div class="stat">Quality Pass: <b>{summary.get("quality_passed", 0)}/{summary.get("total_tests", 0)}</b></div>'
        auth_total = summary.get("authorized_total", 0)
        auth_pass = summary.get("authorized_quality_pass", 0)
        auth_rate = summary.get("authorized_quality_rate", 0)
        auth_color = score_color(auth_rate)
        rbac_html += f'<div class="stat" style="color:{auth_color}">Authorized Quality: <b>{auth_pass}/{auth_total} ({auth_rate:.0%})</b></div>'
        leak_color = "#16a34a" if leak_count == 0 else "#dc2626"
        rbac_html += f'<div class="stat" style="color:{leak_color}">Chunk Leaks: <b>{leak_count}</b></div>'
        rbac_html += '</div>'
        # Root-cause breakdown
        miss_ret = summary.get("miss_retrieval_failure", 0)
        miss_sub = summary.get("miss_sub_clearance", 0)
        miss_other = summary.get("miss_mode_mismatch", 0)
        rbac_html += f'<div class="stats-row" style="font-size:0.8rem;color:#64748b;margin-top:0.5rem">'
        rbac_html += f'<div>Quality miss root causes: retrieval failures={miss_ret}, sub-clearance grounded={miss_sub}, mode mismatch={miss_other}</div>'
        rbac_html += '</div>'

        # Matrix table
        rbac_html += '<table class="matrix"><thead><tr><th>Question</th><th>Level</th><th>Guest (L1)</th><th>Employee (L2)</th><th>Manager (L3)</th><th>Exec (L4)</th></tr></thead><tbody>'
        for row in rbac.get("matrix", []):
            q = row["question"][:45] + ("..." if len(row["question"]) > 45 else "")
            rbac_html += f'<tr><td title="{row["question"]}">{q}</td><td>L{row["min_level"]}</td>'
            for role in ["guest", "employee", "manager", "exec"]:
                r = row["results"].get(role, {})
                mode = r.get("mode", "?")
                rp = r.get("rbac_pass", True)
                qp = r.get("quality_pass", True)
                if not rp:
                    cell_class = "cell-fail"
                    icon = "X"
                elif not qp:
                    cell_class = "cell-warn"
                    icon = "~"
                else:
                    cell_class = "cell-pass"
                    icon = "+"
                rbac_html += f'<td class="{cell_class}" title="{r.get("violation", "")}">{icon} {mode}</td>'
            rbac_html += '</tr>'
        rbac_html += '</tbody></table></div>'

    # RAGAS vs Backend comparison
    comparison_html = ""
    if ragas_vs:
        comparison_html = '<div class="section"><h2>RAGAS vs Backend Faithfulness</h2><table><thead><tr><th>Question</th><th>RAGAS</th><th>Backend</th><th>Delta</th></tr></thead><tbody>'
        for r in ragas_vs:
            delta_color = "#16a34a" if r["delta"] < 0.1 else "#ca8a04" if r["delta"] < 0.2 else "#dc2626"
            comparison_html += f'<tr><td>{r["question"][:60]}</td><td>{r["ragas_faithfulness"]:.3f}</td><td>{r["backend_faithfulness"]:.3f}</td><td style="color:{delta_color}">{r["delta"]:.3f}</td></tr>'
        comparison_html += '</tbody></table></div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Prism RAG Evaluation Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8fafc; color: #1e293b; padding: 2rem; line-height: 1.5; }}
  .header {{ text-align: center; margin-bottom: 2rem; }}
  .header h1 {{ font-size: 1.75rem; font-weight: 700; color: #0f172a; }}
  .header .meta {{ color: #64748b; font-size: 0.875rem; margin-top: 0.25rem; }}
  .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; margin-bottom: 2rem; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.25rem 1.5rem; min-width: 150px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  .card-val {{ font-size: 1.75rem; font-weight: 700; }}
  .card-label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.25rem; }}
  .section {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  .section h2 {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; color: #0f172a; }}
  .stats-row {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1rem; }}
  .stat {{ font-size: 0.9rem; color: #475569; }}
  .stat b {{ color: #0f172a; }}
  .bar-row {{ display: flex; align-items: center; margin-bottom: 0.4rem; }}
  .bar-label {{ width: 100px; font-size: 0.8rem; color: #64748b; text-align: right; padding-right: 0.75rem; }}
  .bar {{ background: #5b47ff; color: #fff; font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px; min-width: 30px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ background: #f1f5f9; padding: 0.6rem; text-align: left; font-weight: 600; border-bottom: 2px solid #e2e8f0; }}
  td {{ padding: 0.5rem 0.6rem; border-bottom: 1px solid #f1f5f9; }}
  .matrix td, .matrix th {{ text-align: center; font-size: 0.8rem; }}
  .matrix td:first-child {{ text-align: left; }}
  .cell-pass {{ background: #f0fdf4; color: #16a34a; }}
  .cell-warn {{ background: #fefce8; color: #ca8a04; }}
  .cell-fail {{ background: #fef2f2; color: #dc2626; font-weight: 700; }}
</style>
</head>
<body>
<div class="header">
  <h1>Prism RAG Evaluation Report</h1>
  <div class="meta">{ts} | Mode: {config.get('mode', 'unknown')} | Questions: {config.get('num_questions', 0)}</div>
</div>

<div class="cards">{cards_html}</div>

{'<div class="section"><h2>Backend Metrics</h2><div class="stats-row">' + backend_html + '</div></div>' if backend_html else ''}

<div class="section">
  <h2>Answer Mode Distribution</h2>
  {mode_html}
</div>

{'<div class="section"><h2>Pipeline Latency</h2><table><thead><tr><th>Stage</th><th>Mean</th><th>P50</th><th>P95</th></tr></thead><tbody>' + latency_html + '</tbody></table></div>' if latency_html else ''}

{rbac_html}
{comparison_html}

</body>
</html>"""

    with open(path, "w") as f:
        f.write(html)
    print(f"\n  HTML report saved to: {path}")


# ---------------------------------------------------------------------------
# 7. MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Prism RAG Evaluator — evaluate your RAG pipeline on RAGAS metrics and RBAC compliance."
    )
    parser.add_argument("--create-dataset", action="store_true", help="Generate TechNova ground-truth dataset")
    parser.add_argument("--lightweight", action="store_true", help="Heuristic eval (no OpenAI needed)")
    parser.add_argument("--rbac", action="store_true", help="RBAC compliance matrix (all 4 roles)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="Backend URL")
    parser.add_argument("--dataset", default="evaluation_dataset.json", help="Path to evaluation dataset")
    parser.add_argument("--output", default="rag_eval_results.json", help="Output path for results")
    parser.add_argument("--format", choices=["json", "html"], default="json", help="Output format")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit 1 if thresholds breached")
    parser.add_argument("--ci-min-faithfulness", type=float, default=0.75, help="CI: min avg faithfulness (default 0.75)")
    parser.add_argument("--ci-rbac-pass-rate", type=float, default=1.0, help="CI: min RBAC pass rate (default 1.0)")
    args = parser.parse_args()

    config = EvalConfig(
        base_url=args.base_url,
        dataset_path=args.dataset,
        output_path=args.output,
        rbac_mode=args.rbac,
        lightweight_mode=args.lightweight,
        output_format=args.format,
        ci_mode=args.ci,
        ci_min_faithfulness=args.ci_min_faithfulness,
        ci_rbac_pass_rate=args.ci_rbac_pass_rate,
    )

    print(f"\n{'='*60}")
    print(f"  PRISM RAG EVALUATOR")
    print(f"{'='*60}\n")

    # --create-dataset: generate and exit
    if args.create_dataset:
        create_technova_dataset(config.dataset_path)
        return

    # Connectivity check
    print(f"  Connecting to {config.base_url}...")
    exec_token = check_connectivity(config)

    # Load dataset
    dataset = load_dataset(config.dataset_path)

    # ── RBAC mode ──
    if config.rbac_mode:
        rbac_results = run_rbac_evaluation(dataset, config)

        # Also run lightweight on exec responses if requested
        lightweight_results = None
        if config.lightweight_mode:
            # Collect exec responses for quality eval
            enriched = collect_rag_responses(dataset, exec_token, config)
            lightweight_results = run_lightweight_evaluation(enriched)
        else:
            enriched = []

        output = format_results(
            ragas_results=None,
            enriched_data=enriched,
            config=config,
            lightweight_results=lightweight_results,
            rbac_results=rbac_results,
        )

        if config.output_format == "html":
            html_path = config.output_path.replace(".json", ".html")
            if html_path == config.output_path:
                html_path = "rag_eval_report.html"
            generate_html_report(output, html_path)
        with open(config.output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\n  Results saved to {config.output_path}")
        if config.ci_mode:
            _ci_gate(output, config)
        return

    # ── Quality evaluation (as exec) ──
    enriched = collect_rag_responses(dataset, exec_token, config)

    if config.lightweight_mode:
        lightweight_results = run_lightweight_evaluation(enriched)
        output = format_results(
            ragas_results=None,
            enriched_data=enriched,
            config=config,
            lightweight_results=lightweight_results,
        )
    else:
        # Full RAGAS evaluation
        if not os.environ.get("OPENAI_API_KEY"):
            print("\n  OPENAI_API_KEY not set. RAGAS needs it for the judge LLM.")
            print("    export OPENAI_API_KEY=sk-...")
            print("    Or run with --lightweight for a no-dependency evaluation.")
            sys.exit(1)

        ragas_results = run_ragas_evaluation(enriched, config)
        if not ragas_results:
            print("  RAGAS evaluation failed.")
            return

        output = format_results(
            ragas_results=ragas_results,
            enriched_data=enriched,
            config=config,
        )

    if config.output_format == "html":
        html_path = config.output_path.replace(".json", ".html")
        if html_path == config.output_path:
            html_path = "rag_eval_report.html"
        generate_html_report(output, html_path)

    with open(config.output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {config.output_path}")

    if config.ci_mode:
        _ci_gate(output, config)


def _ci_gate(output: dict, config: EvalConfig):
    """Check CI thresholds and exit 1 if any are breached."""
    failures = []

    # RBAC pass rate
    rbac = output.get("rbac_matrix")
    if rbac:
        summary = rbac.get("summary", {})
        total = summary.get("total_tests", 0)
        passed = summary.get("rbac_passed", 0)
        rate = passed / max(total, 1)
        if rate < config.ci_rbac_pass_rate:
            failures.append(f"RBAC pass rate {rate:.1%} < {config.ci_rbac_pass_rate:.1%}")
        if summary.get("chunk_leaks", 0) > 0:
            failures.append(f"Chunk leaks detected: {summary['chunk_leaks']}")

    # Faithfulness threshold
    backend = output.get("backend_metrics", {})
    avg_faith = backend.get("avg_faithfulness")
    if avg_faith is not None and avg_faith < config.ci_min_faithfulness:
        failures.append(f"Avg faithfulness {avg_faith:.3f} < {config.ci_min_faithfulness}")

    # RAGAS aggregate
    agg = output.get("aggregate_scores", {})
    ragas_faith = agg.get("faithfulness")
    if ragas_faith is not None and ragas_faith < config.ci_min_faithfulness:
        failures.append(f"RAGAS faithfulness {ragas_faith:.3f} < {config.ci_min_faithfulness}")

    # Lightweight aggregate
    lw = output.get("lightweight", {})
    lw_agg = lw.get("aggregate", {}) if lw else {}
    lw_faith = lw_agg.get("backend_faithfulness")
    if lw_faith is not None and avg_faith is None and lw_faith < config.ci_min_faithfulness:
        failures.append(f"Backend faithfulness {lw_faith:.3f} < {config.ci_min_faithfulness}")

    print(f"\n{'='*60}")
    print(f"  CI GATE")
    print(f"{'='*60}")

    if failures:
        print(f"  FAILED — {len(failures)} threshold(s) breached:\n")
        for f in failures:
            print(f"    X  {f}")
        print()
        sys.exit(1)
    else:
        print(f"  PASSED — all thresholds met.")
        print(f"    Faithfulness >= {config.ci_min_faithfulness}")
        if rbac:
            print(f"    RBAC pass rate = 100%")
        print()


if __name__ == "__main__":
    main()
