"""SQL Analytics Agent — natural-language queries on tabular data.

Instead of chunking Excel/CSV into text → embedding → retrieval (which
loses structure), this agent loads the raw file into a pandas DataFrame
and asks the LLM to write pandas code that answers the user's question.

Pipeline:
  1. Identify which uploaded docs are tabular (CSV/XLSX/XLS).
  2. Load the target file(s) into pandas DataFrames.
  3. Send schema + sample rows to the LLM, ask it to write pandas code.
  4. Execute the code in a restricted sandbox (no imports, no I/O).
  5. Return the result as a table (list of dicts) + optional ECharts spec.

Security: the sandbox uses a restricted `exec()` with a whitelist of
builtins. No file I/O, no imports, no network. The LLM can only call
pandas/numpy methods on the pre-loaded DataFrame variable `df`.
"""

import json
import re
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import settings
from src.core import store
from src.pipelines.generation_pipeline import _complete_chat


# ── Tabular file detection ────────────────────────────────────────────────

_TABULAR_MIMES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}

_TABULAR_EXTS = {".csv", ".xlsx", ".xls"}


def is_tabular_doc(doc: store.Document) -> bool:
    """True if the document is a tabular file (CSV/Excel)."""
    if doc.mime in _TABULAR_MIMES:
        return True
    ext = Path(doc.filename).suffix.lower()
    return ext in _TABULAR_EXTS


def list_tabular_docs(max_doc_level: int | None = None) -> list[store.Document]:
    """Return all uploaded tabular documents the caller can see."""
    docs = store.list_documents()
    out = []
    for d in docs:
        if max_doc_level is not None and d.doc_level > max_doc_level:
            continue
        if is_tabular_doc(d):
            out.append(d)
    return out


# ── Data query detection ──────────────────────────────────────────────────

_DATA_KEYWORDS = {
    "total", "sum", "count", "how many", "average", "avg", "mean",
    "minimum", "min", "maximum", "max", "median", "percentage", "percent",
    "ratio", "proportion", "group by", "grouped by", "per department",
    "per employee", "per month", "per year", "breakdown", "distribution",
    "top 5", "top 10", "top five", "top ten", "bottom 5", "bottom 10",
    "highest", "lowest", "rank", "sort by", "sorted by", "order by",
    "filter", "where", "greater than", "less than", "more than",
    "between", "range", "chart", "graph", "plot", "visualize",
    "table", "spreadsheet", "excel", "csv", "salary", "revenue",
    "expense", "budget", "cost", "profit", "loss", "growth",
    "compare", "trend", "over time", "monthly", "quarterly", "annually",
    "calculate", "compute", "aggregate", "pivot",
}


# Phrases that indicate a document/policy question, NOT a data query.
# "What is the salary policy?" should go to RAG, not pandas.
_DOC_QUERY_SIGNALS = {
    "policy", "procedure", "guideline", "rule", "regulation",
    "what is the", "what are the", "explain", "describe", "tell me about",
    "summarize", "summary", "overview", "define", "definition",
    "how does", "how do", "why does", "why do", "when was", "who is",
    "document", "handbook", "manual", "report", "clause", "section",
}


def classify_data_query(query: str) -> str:
    """Classify query intent: 'data', 'doc', or 'ambiguous'.

    'What is the total count of present' → 'data'
    'What is the salary policy' → 'doc'
    'What is the total salary policy breakdown' → 'ambiguous'
    """
    q_lower = query.lower()
    data_matches = sum(1 for kw in _DATA_KEYWORDS if kw in q_lower)
    if data_matches < 2:
        return "doc"
    doc_matches = sum(1 for kw in _DOC_QUERY_SIGNALS if kw in q_lower)
    if doc_matches > data_matches:
        return "doc"
    # Close call — signals within 1 of each other and both ≥ 2
    if doc_matches >= 2 and abs(data_matches - doc_matches) <= 1:
        return "ambiguous"
    return "data"


def looks_like_data_query(query: str) -> bool:
    """Backward-compatible wrapper. True only for clear 'data' intent."""
    return classify_data_query(query) == "data"


# ── DataFrame loading ─────────────────────────────────────────────────────

def _raw_path(doc: store.Document) -> Path:
    """Resolve the raw file path for a document."""
    ext = Path(doc.filename).suffix.lower()
    return Path(settings.RAW_DIR) / f"{doc.doc_id}{ext}"


def load_dataframe(doc: store.Document) -> pd.DataFrame:
    """Load a tabular document into a pandas DataFrame."""
    path = _raw_path(doc)
    if not path.exists():
        raise FileNotFoundError(f"Raw file not found: {path}")
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path)
    elif ext in {".xlsx", ".xls"}:
        # Read first sheet by default; multi-sheet handled via sheet_name
        xls = pd.ExcelFile(path)
        if len(xls.sheet_names) == 1:
            return pd.read_excel(path, sheet_name=0)
        # Multi-sheet: concat all sheets with a _sheet column
        frames = []
        for name in xls.sheet_names:
            df = pd.read_excel(path, sheet_name=name)
            df["_sheet"] = name
            frames.append(df)
        return pd.concat(frames, ignore_index=True)
    else:
        raise ValueError(f"Not a tabular file: {ext}")


def _schema_summary(df: pd.DataFrame, max_rows: int = 5) -> str:
    """Generate a concise schema + sample for the LLM prompt."""
    lines = []
    lines.append(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
    lines.append("")
    lines.append("Columns:")
    for col in df.columns:
        dtype = str(df[col].dtype)
        nunique = df[col].nunique()
        nulls = int(df[col].isna().sum())
        sample_vals = df[col].dropna().head(3).tolist()
        sample_str = ", ".join(str(v) for v in sample_vals)
        lines.append(f"  - {col} ({dtype}, {nunique} unique, {nulls} nulls) — e.g. {sample_str}")
    lines.append("")
    lines.append(f"First {max_rows} rows:")
    lines.append(df.head(max_rows).to_string(index=False, max_colwidth=40))
    return "\n".join(lines)


# ── LLM code generation prompt ────────────────────────────────────────────

ANALYTICS_CODE_PROMPT = """You are a data analyst assistant. Given a pandas DataFrame `df` and a user question, write Python code that answers the question.

RULES:
- The DataFrame is already loaded as `df`. Do NOT import anything or read files.
- Store your final answer in a variable called `result`. It must be one of:
  - A pandas DataFrame (for tables)
  - A pandas Series (for single-column results)
  - A scalar (int, float, str) for single values
  - A dict for structured answers
- Keep the code concise. No plots, no prints, no file I/O.
- If the question asks for a chart/visualization, also create a variable called `chart` containing an ECharts option dict with keys: type ("bar"|"line"|"pie"), title (str), xAxis (list), series (list of {{name, data}}).
- If no chart is needed, do NOT create a `chart` variable.
- Handle edge cases: if a column doesn't exist, set result = "Column not found: <name>"
- For percentage calculations, round to 2 decimal places.
- For monetary values, don't round — keep full precision.

SCHEMA:
{schema}

QUESTION: {query}

Write ONLY the Python code, no explanation, no markdown fences, no comments:"""


# ── Sandboxed execution ───────────────────────────────────────────────────

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool,
    "dict": dict, "enumerate": enumerate, "filter": filter,
    "float": float, "frozenset": frozenset, "int": int,
    "isinstance": isinstance, "len": len, "list": list,
    "map": map, "max": max, "min": min, "print": print,
    "range": range, "round": round, "set": set, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "type": type,
    "zip": zip, "True": True, "False": False, "None": None,
}

# Patterns that indicate malicious or unsafe code
_UNSAFE_PATTERNS = [
    re.compile(r"\bimport\s+", re.IGNORECASE),
    re.compile(r"\b__\w+__\b"),  # dunder access
    re.compile(r"\bopen\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bos\.", re.IGNORECASE),
    re.compile(r"\bsys\.", re.IGNORECASE),
    re.compile(r"\bsubprocess\b", re.IGNORECASE),
    re.compile(r"\bshutil\b", re.IGNORECASE),
    re.compile(r"\b__builtins__\b"),
    re.compile(r"\bglobals\s*\("),
    re.compile(r"\blocals\s*\("),
    re.compile(r"\bgetattr\s*\("),
    re.compile(r"\bsetattr\s*\("),
    re.compile(r"\bdelattr\s*\("),
    re.compile(r"\bcompile\s*\("),
]


def _is_safe_code(code: str) -> tuple[bool, str]:
    """Check if generated code is safe to execute."""
    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(code):
            return False, f"Unsafe pattern detected: {pattern.pattern}"
    return True, ""


def _execute_pandas_code(code: str, df: pd.DataFrame) -> dict[str, Any]:
    """Execute LLM-generated pandas code in a restricted sandbox.

    Returns:
      {
        "ok": bool,
        "result": <serialized result>,
        "result_type": "table" | "scalar" | "error",
        "chart": <ECharts option dict> | None,
        "error": str | None,
        "code": str,  # the generated code
      }
    """
    safe, reason = _is_safe_code(code)
    if not safe:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": f"Code safety check failed: {reason}",
            "code": code,
        }

    import numpy as np

    sandbox = {
        "__builtins__": _SAFE_BUILTINS,
        "df": df.copy(),  # copy so the original is never mutated
        "pd": pd,
        "np": np,
    }

    try:
        exec(code, sandbox)
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": f"{type(e).__name__}: {e}",
            "code": code,
        }

    # Extract result
    raw_result = sandbox.get("result")
    chart = sandbox.get("chart")

    if raw_result is None:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": "Code did not produce a `result` variable.",
            "code": code,
        }

    # Serialize the result
    try:
        if isinstance(raw_result, pd.DataFrame):
            # Cap at 50 rows for the frontend
            truncated = raw_result.head(50)
            result_data = {
                "columns": list(truncated.columns),
                "rows": truncated.to_dict(orient="records"),
                "total_rows": len(raw_result),
                "truncated": len(raw_result) > 50,
            }
            result_type = "table"
        elif isinstance(raw_result, pd.Series):
            result_data = {
                "columns": [raw_result.name or "value"],
                "rows": [
                    {"index": str(k), raw_result.name or "value": v}
                    for k, v in raw_result.head(50).items()
                ],
                "total_rows": len(raw_result),
                "truncated": len(raw_result) > 50,
            }
            result_type = "table"
        elif isinstance(raw_result, (int, float, str, bool)):
            result_data = raw_result
            result_type = "scalar"
        elif isinstance(raw_result, dict):
            result_data = raw_result
            result_type = "scalar"
        else:
            result_data = str(raw_result)
            result_type = "scalar"
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": f"Failed to serialize result: {e}",
            "code": code,
        }

    # Validate chart spec if present
    if chart is not None:
        if not isinstance(chart, dict):
            chart = None
        else:
            # Ensure required keys
            if "type" not in chart:
                chart["type"] = "bar"

    # Convert any numpy/pandas types to native Python for JSON serialization
    def _jsonify(obj):
        if isinstance(obj, (pd.Timestamp,)):
            return obj.isoformat()
        if hasattr(obj, 'item'):  # numpy scalar
            return obj.item()
        if isinstance(obj, float) and (obj != obj):  # NaN
            return None
        return obj

    result_json = json.loads(json.dumps(result_data, default=_jsonify))
    chart_json = json.loads(json.dumps(chart, default=_jsonify)) if chart else None

    return {
        "ok": True,
        "result": result_json,
        "result_type": result_type,
        "chart": chart_json,
        "error": None,
        "code": code,
    }


# ── Main agent entry point ────────────────────────────────────────────────

async def run_analytics_query(
    query: str,
    doc: store.Document,
    user_level: int,
) -> dict[str, Any]:
    """Run a natural-language analytics query against a tabular document.

    Returns a dict with:
      ok, result, result_type, chart, error, code, doc_id, filename, schema
    """
    # RBAC check
    if doc.doc_level > user_level:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": "Access denied — document above your clearance level.",
            "code": "",
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "schema": "",
        }

    # Load data
    try:
        df = load_dataframe(doc)
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": f"Failed to load data: {e}",
            "code": "",
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "schema": "",
        }

    schema = _schema_summary(df)

    # Generate pandas code via LLM
    prompt = ANALYTICS_CODE_PROMPT.format(schema=schema, query=query)
    try:
        code = await _complete_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.0,
        )
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": f"LLM code generation failed: {e}",
            "code": "",
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "schema": schema,
        }

    # Clean up the generated code
    code = (code or "").strip()
    # Strip markdown fences if the LLM wrapped them
    if code.startswith("```"):
        lines = code.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        code = "\n".join(lines).strip()

    if not code:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": "LLM returned empty code.",
            "code": "",
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "schema": schema,
        }

    # Execute
    result = _execute_pandas_code(code, df)

    # Corrective retry: if the first attempt failed with a runtime error,
    # send the error back to the LLM and ask it to fix the code.
    if not result["ok"] and result["error"] and "safety check" not in result["error"]:
        retry_prompt = (
            f"Your previous code failed with this error:\n"
            f"{result['error']}\n\n"
            f"Original code:\n{code}\n\n"
            f"Fix the code. Remember: the DataFrame is `df`, store result in `result`.\n"
            f"Schema:\n{schema}\n\n"
            f"Question: {query}\n\n"
            f"Write ONLY the corrected Python code:"
        )
        try:
            retry_code = await _complete_chat(
                [{"role": "user", "content": retry_prompt}],
                max_tokens=500,
                temperature=0.0,
            )
            retry_code = (retry_code or "").strip()
            if retry_code.startswith("```"):
                lines = retry_code.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                retry_code = "\n".join(lines).strip()
            if retry_code:
                result = _execute_pandas_code(retry_code, df)
                result["code"] = f"# Retry (original failed: {result.get('error', 'unknown')})\n{retry_code}"
        except Exception:
            pass  # keep the original error

    result["doc_id"] = doc.doc_id
    result["filename"] = doc.filename
    result["schema"] = schema

    return result


async def find_target_doc(
    query: str,
    doc_ids: list[str] | None,
    user_level: int,
    caller_role: str | None = None,
) -> store.Document | None:
    """Find the best tabular doc to run analytics on.

    Priority:
      1. If doc_ids is scoped to exactly one tabular doc, use it.
      2. If the query mentions a filename, match it.
      3. If there's only one tabular doc visible, use it.
      4. Otherwise return None (let the normal RAG pipeline handle it).
    """
    tabular = list_tabular_docs(max_doc_level=user_level)

    # Filter by doc_ids scope if provided — but if the scoped set
    # contains NO tabular docs, fall back to all visible tabular docs.
    # This handles the common case where the user has .docx/.pdf files
    # selected in the Knowledge sidebar but asks a data question that
    # should hit an uploaded Excel/CSV.
    if doc_ids:
        scoped = [d for d in tabular if d.doc_id in doc_ids]
        if scoped:
            tabular = scoped
        # else: keep all tabular docs — the sidebar scope doesn't have any

    if not tabular:
        return None

    # Single tabular doc — easy
    if len(tabular) == 1:
        return tabular[0]

    # Try to match query against filenames
    q_lower = query.lower()
    for doc in tabular:
        name_parts = Path(doc.filename).stem.lower().replace("_", " ").replace("-", " ").split()
        if any(part in q_lower for part in name_parts if len(part) >= 3):
            return doc

    # Multiple tabular docs, no clear match — return the most recently uploaded
    return sorted(tabular, key=lambda d: d.created_at, reverse=True)[0]
