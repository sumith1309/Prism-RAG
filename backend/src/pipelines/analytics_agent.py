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
    # Conversational data queries — natural phrasing
    "longest", "shortest", "most", "least", "fewest",
    "which day", "which month", "which week", "which employee",
    "which department", "which year", "which date",
    "how often", "how many times", "how much", "how long",
    "when did", "when was", "who had", "who has", "who worked",
    "worked the", "earned the", "spent the", "took the",
    "late", "absent", "present", "overtime", "hours",
    "attendance", "timecard", "time card", "punch", "clock in",
    "clock out", "shift", "working days", "work hours",
}


# Phrases that indicate a document/policy question, NOT a data query.
# "What is the salary policy?" should go to RAG, not pandas.
_DOC_QUERY_SIGNALS = {
    "policy", "procedure", "guideline", "rule", "regulation",
    "what is the", "what are the", "explain", "describe", "tell me about",
    "summarize", "summary", "overview", "define", "definition",
    "how does", "how do", "why does", "why do", "when was", "who is",
    "document", "handbook", "manual", "report", "clause", "section",
    # Multi-hop / cross-document comparison signals — "compare what two
    # documents say" is RAG, not "compute a number from a spreadsheet".
    "relate to", "relationship between", "reflected in", "improvements from",
    "how does.*relate", "incident", "remediation", "escalation",
    "roadmap", "board meeting", "board-approved", "vendor contract",
    "compliance training", "security incident", "platform architecture",
    "sla requirement", "asset replacement", "on-call rotation",
}


def _word_boundary_match(keyword: str, text: str) -> bool:
    """Match keyword with word boundaries to avoid substring false positives.
    'sum' should match 'the sum of' but NOT 'summarize'."""
    import re
    # Multi-word keywords and keywords with special chars use plain `in`
    if " " in keyword or not keyword.isalpha():
        return keyword in text
    return bool(re.search(rf"\b{re.escape(keyword)}\b", text))


def classify_data_query(query: str) -> str:
    """Classify query intent: 'data', 'doc', or 'ambiguous'.

    'What is the total count of present' → 'data'
    'What is the salary policy' → 'doc'
    'What is the total salary policy breakdown' → 'ambiguous'
    """
    q_lower = query.lower()
    data_matches = sum(1 for kw in _DATA_KEYWORDS if _word_boundary_match(kw, q_lower))
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


def _fix_messy_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Auto-detect and fix messy Excel headers.

    Many real-world Excel files have metadata rows above the actual data
    header (e.g. "From 2026-02-01 To 2026-02-28" in row 0, employee info
    in row 1, actual column names in row 2). This creates Unnamed: columns.

    Fix: scan the first 5 rows for the one with the most unique non-null
    string values — that's likely the real header row. Promote it and
    drop the metadata rows above.
    """
    unnamed_count = sum(1 for c in df.columns if str(c).startswith("Unnamed"))
    if unnamed_count < len(df.columns) * 0.5:
        return df  # headers look fine

    best_row = -1
    best_score = 0
    for i in range(min(5, len(df))):
        row_vals = df.iloc[i].dropna().astype(str).tolist()
        # Score: count of unique string values that look like column names
        # (short, no digits-only, no long sentences)
        good = [v for v in row_vals if 2 <= len(v) <= 30 and not v.replace(".", "").isdigit()]
        score = len(set(good))
        if score > best_score:
            best_score = score
            best_row = i

    if best_row >= 0 and best_score >= 3:
        new_headers = df.iloc[best_row].astype(str).tolist()
        # Preserve the _sheet column name — it's our multi-sheet identifier
        old_cols = list(df.columns)
        df = df.iloc[best_row + 1:].reset_index(drop=True)
        final_headers = []
        for i, h in enumerate(new_headers):
            if i < len(old_cols) and old_cols[i] == "_sheet":
                final_headers.append("Employee_ID")
            else:
                final_headers.append(h)
        df.columns = final_headers
    return df


def _clean_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert hh:mm or hh:mm:ss time strings to decimal hours for math.

    Many time-tracking Excel files store working hours as '08:42' strings.
    The LLM can't do math on these — convert to float hours (8.7).
    Adds a new column '{col}_hours' for each detected time column.
    """
    import re
    time_pattern = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")

    for col in df.columns:
        if col.startswith("_"):
            continue
        sample = df[col].dropna().head(10).astype(str).tolist()
        time_matches = sum(1 for v in sample if time_pattern.match(v.strip()))
        if time_matches >= len(sample) * 0.5 and time_matches >= 3:
            # Convert to decimal hours
            def to_hours(val):
                try:
                    parts = str(val).strip().split(":")
                    h = int(parts[0])
                    m = int(parts[1]) if len(parts) > 1 else 0
                    s = int(parts[2]) if len(parts) > 2 else 0
                    return round(h + m / 60 + s / 3600, 2)
                except (ValueError, IndexError):
                    return None
            df[f"{col}_hours"] = df[col].apply(to_hours)
    return df


def _strip_metadata_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove summary/metadata rows that aren't real data.

    Common patterns in real-world Excel files:
      - "Statistics" / "Total" / "Grand Total" / "Summary" rows
      - "From 2026-02-01 To 2026-02-28" date-range headers
      - "Employee: Name, Gender [ID]" employee info rows
      - Rows where the first column contains long text (metadata)

    These rows pollute aggregations (a 'Statistics' row with Total Time
    = 157:50 converts to 157.83 hours, destroying any average).
    """
    if df.empty:
        return df

    # Find the first text column (usually Date or a label column)
    # Check for both 'object' and 'str'/'string' dtypes (pandas 2.x uses StringDtype)
    text_cols = [c for c in df.columns if str(df[c].dtype) in ("object", "str", "string", "string[python]", "string[pyarrow]") and not c.startswith("_") and not c.endswith("_hours")]
    if not text_cols:
        return df

    first_col = text_cols[0]

    _METADATA_PATTERNS = [
        "statistics", "total", "grand total", "summary", "subtotal",
        "employee:", "from ", "position:", "department:",
        "note:", "remarks", "disclaimer",
    ]

    def _is_metadata(val):
        if pd.isna(val):
            return False
        s = str(val).strip().lower()
        if not s:
            return False
        # Long text in date/label column = metadata
        if len(s) > 40:
            return True
        return any(s.startswith(p) or s == p for p in _METADATA_PATTERNS)

    mask = df[first_col].apply(_is_metadata)
    removed = mask.sum()
    if removed > 0:
        df = df[~mask].reset_index(drop=True)

    return df


_EMP_PATTERN = re.compile(
    r"Employee:\s*([^,\[]+?)(?:\s*,+\s*(?:Male|Female|Other|[MF]))?\s*\[(\d+)\]"
    r"(?:.*?Position:\s*([^\s]+(?:\s+[^\s]+)*?))?"
    r"(?:\s+Department:\s*([^\n\[]+?)(?:\[|\n|$))?",
    re.IGNORECASE,
)


def _scan_sheet_for_employee(sheet_df: pd.DataFrame) -> dict:
    """Scan the first few rows of a sheet for an 'Employee: Name, Male [ID]'
    metadata row. Returns {"Employee_Name", "Position", "Department"} or {}.

    Must run BEFORE _fix_messy_headers drops metadata rows.
    """
    if sheet_df.empty:
        return {}
    for i in range(min(5, len(sheet_df))):
        for col in sheet_df.columns[:3]:  # metadata is in left columns
            val = sheet_df.iloc[i].get(col)
            if pd.isna(val):
                continue
            s = str(val).strip()
            if "employee:" not in s.lower():
                continue
            m = _EMP_PATTERN.search(s)
            if not m:
                continue
            return {
                "Employee_Name": m.group(1).strip() if m.group(1) else None,
                "Position": m.group(3).strip() if m.group(3) else None,
                "Department": m.group(4).strip() if m.group(4) else None,
            }
    return {}


_SCHEMA_SHEET_PATTERNS = re.compile(
    r"^(schema[\s_]*notes?|schema|readme|notes?|documentation|doc|example[s_]*.*|"
    r"example.*quer(y|ies)|instructions?|help|info|metadata|"
    r"data[\s_]*dictionary|dictionary|glossary|column[\s_]*notes?|"
    r"cover|sheet[\s_]*1?|summary)$",
    re.IGNORECASE,
)


def _is_data_sheet(sheet_name: str) -> bool:
    """Return False for schema/notes/documentation sheets.
    These describe the data but aren't data themselves, and concatenating
    them pollutes the column space of the real data sheet."""
    return not _SCHEMA_SHEET_PATTERNS.match(str(sheet_name).strip())


def load_dataframe(doc: store.Document) -> pd.DataFrame:
    """Load a tabular document into a pandas DataFrame.

    Applies auto-cleaning:
      1. Skip schema/notes/README sheets (they describe data, aren't data)
      2. Per-sheet metadata extraction (Employee_Name from "Employee: Manoj [28]")
      3. Fix messy headers (Unnamed: columns → promote real header row)
      4. Strip metadata/summary rows (Statistics, Employee:, From..To..)
      5. Convert time strings (hh:mm) to decimal hours for math
    """
    path = _raw_path(doc)
    if not path.exists():
        raise FileNotFoundError(f"Raw file not found: {path}")
    ext = path.suffix.lower()

    # Per-sheet metadata map: sheet_name → {Employee_Name, Position, Department}
    sheet_metadata: dict = {}

    if ext == ".csv":
        df = pd.read_csv(path)
    elif ext in {".xlsx", ".xls"}:
        xls = pd.ExcelFile(path)
        # Filter out schema/notes/documentation sheets
        data_sheets = [s for s in xls.sheet_names if _is_data_sheet(s)]
        # Safety: if filtering removes everything, fall back to all sheets
        if not data_sheets:
            data_sheets = xls.sheet_names

        if len(data_sheets) == 1:
            # Single data sheet — load directly, no _sheet column needed
            df = pd.read_excel(path, sheet_name=data_sheets[0])
        else:
            frames = []
            for name in data_sheets:
                sheet_df = pd.read_excel(path, sheet_name=name)
                # Extract employee metadata BEFORE header promotion discards it
                info = _scan_sheet_for_employee(sheet_df)
                if info:
                    sheet_metadata[str(name)] = info
                sheet_df["_sheet"] = name
                frames.append(sheet_df)
            df = pd.concat(frames, ignore_index=True)
    else:
        raise ValueError(f"Not a tabular file: {ext}")

    df = _fix_messy_headers(df)

    # Inject Employee_Name / Position / Department from the sheet-level map.
    # _fix_messy_headers converts _sheet → Employee_ID, so use Employee_ID to
    # look up each row's sheet metadata.
    if sheet_metadata and "Employee_ID" in df.columns:
        def _lookup(eid, field):
            info = sheet_metadata.get(str(eid)) or {}
            return info.get(field)
        df["Employee_Name"] = df["Employee_ID"].apply(lambda e: _lookup(e, "Employee_Name"))
        df["Position"] = df["Employee_ID"].apply(lambda e: _lookup(e, "Position"))
        df["Department"] = df["Employee_ID"].apply(lambda e: _lookup(e, "Department"))

    df = _strip_metadata_rows(df)
    df = _clean_time_columns(df)
    return df


def _schema_summary(df: pd.DataFrame, max_rows: int = 5) -> str:
    """Generate a rich schema + sample for the LLM prompt.

    Includes data quality notes so the LLM knows how to handle messy data:
    - Which columns are mostly empty (skip them)
    - Which columns have _hours equivalents (use those for math)
    - Which rows are likely metadata/empty (filter them)
    - What the _sheet column means (employee/entity ID)
    """
    lines = []
    lines.append(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
    lines.append("")

    # Separate useful vs junk columns
    useful_cols = []
    junk_cols = []
    for col in df.columns:
        nulls = int(df[col].isna().sum())
        null_pct = nulls / max(len(df), 1)
        # Check if column values are just the column name repeated
        non_null = df[col].dropna()
        if len(non_null) > 0:
            most_common = non_null.astype(str).value_counts().iloc[0]
            most_common_val = non_null.astype(str).value_counts().index[0]
            if most_common / len(non_null) > 0.9 and most_common_val == str(col):
                junk_cols.append(col)
                continue
        if null_pct > 0.9:
            junk_cols.append(col)
            continue
        useful_cols.append(col)

    lines.append("Useful columns:")
    for col in useful_cols:
        dtype = str(df[col].dtype)
        nunique = df[col].nunique()
        nulls = int(df[col].isna().sum())
        null_pct = round(nulls / max(len(df), 1) * 100)
        sample_vals = df[col].dropna().head(4).tolist()
        sample_str = ", ".join(str(v) for v in sample_vals)
        annotation = ""
        if col.endswith("_hours"):
            annotation = " [USE THIS for calculations — decimal hours from time strings]"
        elif col == "Employee_Name":
            annotation = f" [EMPLOYEE NAME — prefer this over Employee_ID when returning results so users see 'Manoj' not '28' ({nunique} distinct)]"
        elif col in ("Employee_ID", "_sheet") or ("employee" in col.lower() and "id" in col.lower()):
            annotation = f" [ENTITY ID — use for groupby to compare across employees ({nunique} distinct). Join back to Employee_Name for display.]"
        elif dtype in ("object", "str", "string", "string[python]", "string[pyarrow]") and nunique < 100 and col not in ("Date", "Weekday", "Employee_Name") and nunique > 1 and nunique < len(df) * 0.1:
            annotation = f" [categorical — {nunique} groups, use for groupby]"
        lines.append(f"  - {col} ({dtype}, {nunique} unique, {null_pct}% null) — e.g. {sample_str}{annotation}")

    if junk_cols:
        lines.append(f"\nIgnore these columns (mostly empty or just header text repeated): {', '.join(junk_cols)}")

    # Data quality notes
    lines.append("\nData quality notes:")
    null_rows = df[useful_cols].isna().all(axis=1).sum()
    if null_rows > 0:
        lines.append(f"  - {null_rows} rows are completely empty (days off / holidays) — FILTER THEM OUT with .dropna()")
    hours_cols = [c for c in df.columns if c.endswith("_hours")]
    if hours_cols:
        lines.append(f"  - For time-based calculations, use the _hours columns ({', '.join(hours_cols)}) — they are decimal hours (8.70 = 8h42m)")
        lines.append(f"  - Do NOT try to parse the original time strings (Clock In, Total Time, etc.) — use the _hours versions")

    lines.append("")
    lines.append(f"First {max_rows} data rows (non-empty):")
    # Show non-empty rows for the sample
    clean_sample = df.dropna(subset=[c for c in useful_cols if c in df.columns and df[c].dtype != "object"][:1] or useful_cols[:1]).head(max_rows)
    lines.append(clean_sample[useful_cols].to_string(index=False, max_colwidth=35))
    return "\n".join(lines)


# ── LLM code generation prompt ────────────────────────────────────────────

ANALYTICS_CODE_PROMPT = """You are a senior data analyst. Given a pandas DataFrame `df` and a user question, write Python code that answers it accurately.

STEP 1 — DATA CLEANING (always do this first):
- df = df.dropna(how='all')  # remove empty rows
- If _hours columns exist, use THOSE for math (8.70 = 8h42m). NEVER parse raw time strings.
- Filter out rows where the key columns are NaN before aggregating.

STEP 2 — ALWAYS TRY TO COMPUTE FIRST:
- Think creatively about how to answer. Example: "how many employees were present on each day?" → count distinct Employee_IDs that have a non-null Clock In per Date → find the max.
- "Employees present" = rows with non-null Clock In or Total Time for that date.
- Store your answer in `result` (DataFrame, Series, scalar, or dict).
- `result` must be a COMPUTED VALUE (number, table, dict), NEVER a column name, dtype, or label.
- For groupby, use columns marked as "ENTITY ID" or "categorical" in the schema.
- For percentage calculations, round to 2 decimal places.
- If the question asks for a chart, or if the result is a time-series / distribution, ALWAYS create a `chart` variable showing ALL data points (not just the aggregate). For example, "highest absent day" should chart absent counts for EVERY day, not just the max.
- Chart format: dict with type ("bar"|"line"|"pie"), title (str), xAxis (list of ALL labels), series (list of {{name, data: list of ALL values}}).
- For scalar answers about a max/min/peak, ALWAYS include context: which date, which employee, which category. E.g. result = "57 employees absent on 01-02-2026 (Sunday)" not just 57.

STEP 3 — ONLY IF GENUINELY IMPOSSIBLE:
- If a required column truly doesn't exist: result = "Column not found: <name>. Available: " + str(list(df.columns))
- If after trying you truly cannot compute an answer, explain what the data DOES contain and suggest a question it CAN answer.
- Do NOT give up without trying. Most questions CAN be answered by combining columns creatively.

SCHEMA:
{schema}

QUESTION: {query}

Write ONLY the Python code, no explanation, no markdown fences:"""


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
            # Cap at 50 rows + replace NaN with None (NaN isn't valid JSON)
            truncated = raw_result.head(50).where(lambda x: pd.notna(x), None)
            result_data = {
                "columns": list(truncated.columns),
                "rows": truncated.to_dict(orient="records"),
                "total_rows": len(raw_result),
                "truncated": len(raw_result) > 50,
            }
            result_type = "table"
        elif isinstance(raw_result, pd.Series):
            clean_series = raw_result.head(50).where(lambda x: pd.notna(x), None)
            result_data = {
                "columns": [raw_result.name or "value"],
                "rows": [
                    {"index": str(k), raw_result.name or "value": v}
                    for k, v in clean_series.items()
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

    # ── Result validation ─────────────────────────────────────────────
    # Catch nonsensical results: column names, dtype labels, NaN, empty
    # strings, row labels that the LLM returned as if they were answers.
    col_names_lower = {str(c).lower() for c in df.columns}
    _DTYPE_LABELS = {"int64", "float64", "object", "str", "bool", "datetime64", "string", "category"}

    def _is_nonsense(val) -> str | None:
        """Return a reason string if the result is nonsensical, else None."""
        if val is None:
            return "Result is None"
        if isinstance(val, float) and (val != val):  # NaN
            return "Result is NaN"
        if isinstance(val, str):
            s = val.strip().lower()
            if not s:
                return "Result is empty string"
            if s in col_names_lower:
                return f"Result is a column name ('{val}'), not a computed value"
            if s in _DTYPE_LABELS:
                return f"Result is a dtype label ('{val}'), not a computed value"
            if s in {"nan", "none", "null", "nat"}:
                return f"Result is '{val}'"
        if isinstance(val, dict) and not val:
            return "Result is empty dict"
        return None

    nonsense_reason = None
    if result_type == "scalar":
        nonsense_reason = _is_nonsense(result_data)
    elif result_type == "table" and isinstance(result_data, dict):
        rows = result_data.get("rows", [])
        cols = result_data.get("columns", [])
        if not rows:
            nonsense_reason = "Result table is empty"
        elif len(rows) == 1 and len(cols) == 1:
            # Single-cell table — check if the value is nonsense
            only_val = rows[0].get(cols[0]) if cols else None
            nonsense_reason = _is_nonsense(only_val)

    if nonsense_reason:
        return {
            "ok": False,
            "result": None,
            "result_type": "error",
            "chart": None,
            "error": f"Invalid result: {nonsense_reason}. The generated code ran but didn't produce a meaningful answer. This may mean the question can't be answered from this data.",
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
            val = obj.item()
            if isinstance(val, float) and (val != val):  # numpy NaN
                return None
            return val
        if isinstance(obj, float) and (obj != obj):  # NaN
            return None
        return obj

    # Proactively scrub NaN from the result BEFORE json.dumps. NaN serializes
    # to the literal "NaN" which isn't valid JSON — this breaks both the
    # frontend JSON.parse AND downstream json.dumps(allow_nan=False) in the
    # persistence/audit path. Scrub recursively so nested dicts/lists are clean.
    import math as _math
    def _scrub_nan(o):
        if isinstance(o, float) and _math.isnan(o):
            return None
        if hasattr(o, 'item'):  # numpy scalar
            try:
                v = o.item()
                if isinstance(v, float) and _math.isnan(v):
                    return None
                return v
            except Exception:
                return None
        if isinstance(o, dict):
            return {k: _scrub_nan(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_scrub_nan(x) for x in o]
        if isinstance(o, tuple):
            return tuple(_scrub_nan(x) for x in o)
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        return o

    try:
        scrubbed = _scrub_nan(result_data)
        result_json = json.loads(json.dumps(scrubbed, default=_jsonify))
    except (TypeError, ValueError) as e:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"Failed to serialize result: {e}", "code": code,
        }
    try:
        chart_json = json.loads(json.dumps(_scrub_nan(chart), default=_jsonify)) if chart else None
    except (TypeError, ValueError):
        chart_json = None

    return {
        "ok": True,
        "result": result_json,
        "result_type": result_type,
        "chart": chart_json,
        "error": None,
        "code": code,
    }


# ── Multi-table support (cross-file JOINs) ────────────────────────────────

def _table_name_from_filename(filename: str) -> str:
    """Normalize filename to a Python variable name.

    02_Employees.xlsx → 'employees'
    Salary_Records.xlsx → 'salary_records'
    Time Card 20260317.xlsx → 'time_card_20260317'
    """
    stem = Path(filename).stem
    # Strip leading number + underscore (common "NN_Name" prefix)
    stem = re.sub(r"^\d+[_\-\.]", "", stem)
    # Replace non-alphanumeric with underscore, lowercase
    name = re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_").lower()
    # Ensure it starts with a letter (prepend 't_' if starts with digit)
    if name and name[0].isdigit():
        name = "t_" + name
    return name or "table"


def _detect_foreign_keys(dfs: dict[str, pd.DataFrame]) -> list[dict]:
    """Detect likely FK relationships across loaded DataFrames.

    Heuristic: if table A has column `<name>_id` (not its own primary key) and
    table B has a column `<name>_id` that is its primary key (nearly all unique),
    then A.<name>_id → B.<name>_id is a likely FK.

    Returns list of {"from": "table.col", "to": "table.col", "reason": str}.
    """
    # Identify each table's likely primary key (first column ending in _id with
    # near-unique values)
    primary_keys: dict[str, str] = {}
    for name, df in dfs.items():
        if df.empty:
            continue
        for col in df.columns:
            col_str = str(col)
            if col_str.endswith("_id") or col_str.endswith("_ID"):
                vals = df[col].dropna()
                if len(vals) > 0 and vals.nunique() / len(vals) > 0.95:
                    primary_keys[name] = col_str
                    break

    # For each column ending in _id in every table, try to match it to another
    # table's primary key by column name
    fks = []
    for name, df in dfs.items():
        own_pk = primary_keys.get(name, "")
        for col in df.columns:
            col_str = str(col)
            if not (col_str.endswith("_id") or col_str.endswith("_ID")):
                continue
            if col_str == own_pk:
                continue
            # Look for another table whose PK matches this column
            for other_name, other_pk in primary_keys.items():
                if other_name == name:
                    continue
                if col_str == other_pk:
                    fks.append({
                        "from": f"df_{name}.{col_str}",
                        "to": f"df_{other_name}.{other_pk}",
                        "reason": "column name match",
                    })
                    break
    return fks


def _multi_table_schema_summary(dfs: dict[str, pd.DataFrame]) -> str:
    """Generate a combined schema summary for multiple DataFrames with FK hints."""
    lines = []
    lines.append(f"You have {len(dfs)} DataFrames loaded.")
    lines.append("CRITICAL: Use ONLY the column names listed below — do NOT")
    lines.append("invent names like 'incident_id' or 'manager_employee_id' if")
    lines.append("they aren't listed. Copy names EXACTLY as shown (case, underscores).")
    lines.append("")

    for name, df in dfs.items():
        # Filter junk columns (from schema_notes leftovers, Unnamed, etc.)
        clean_cols = [
            c for c in df.columns
            if not str(c).startswith("_")
            and not str(c).startswith("Unnamed")
            and not str(c).startswith("TechNova Inc.")
        ]
        lines.append(f"── df_{name} ({df.shape[0]} rows × {len(clean_cols)} cols) ──")
        # Explicit EXACT-columns list at the top
        lines.append(f"  EXACT COLUMN NAMES: {clean_cols}")
        # Per-column detail with sample value
        for col in clean_cols:
            dtype = str(df[col].dtype)
            sample = df[col].dropna().head(1).tolist()
            sample_str = str(sample[0])[:40] if sample else "(all null)"
            lines.append(f"    {col!r}  ({dtype})  e.g. {sample_str}")
        lines.append("")

    fks = _detect_foreign_keys(dfs)
    if fks:
        lines.append("Likely JOIN keys (foreign-key relationships):")
        for fk in fks:
            lines.append(f"  {fk['from']} → {fk['to']}")
        lines.append("")

    return "\n".join(lines)


MULTI_TABLE_ANALYTICS_PROMPT = """You are a senior data analyst with access to MULTIPLE pandas DataFrames. Answer the user's question by joining them with pd.merge() as needed.

AVAILABLE DATAFRAMES:
{schema}

RULES:
1. Use the exact variable names shown (df_employees, df_departments, etc.).
2. Use ONLY the column names listed in "EXACT COLUMN NAMES". Do NOT invent
   names. If a column you expect isn't there, pick the closest one that IS.
3. For joins, use pd.merge(left, right, on='<id>', how='inner'|'left').
4. MERGE SUFFIX PITFALL (CRITICAL — most common bug):
   When both tables share a column name (e.g. both have 'category' or 'level'),
   pd.merge adds default suffixes '_x' and '_y'. BEFORE you groupby/filter on
   that column, either:
   (a) RENAME before merge:
       df_vendors2 = df_vendors.rename(columns={{'category': 'vendor_category'}})
       merged = pd.merge(df_financial_transactions, df_vendors2, on='vendor_id')
       merged.groupby('vendor_category')['amount'].sum()
   (b) Use explicit suffixes and reference the suffixed name:
       merged = pd.merge(ft, vendors, on='vendor_id', suffixes=('_tx','_vendor'))
       merged.groupby('category_vendor')...  # note '_vendor' suffix
5. SELF-JOIN PITFALL (for "manager's manager"):
   # Step 1: customer → account manager
   am = pd.merge(df_customers, df_employees,
                 left_on='account_manager_employee_id',
                 right_on='employee_id', suffixes=('','_am'))
   # Step 2: account manager → their manager
   mgr = pd.merge(am, df_employees,
                  left_on='manager_employee_id',
                  right_on='employee_id', suffixes=('','_mgr'))
   # Now columns are: first_name (customer fields), first_name_mgr (manager)
   # The AM's name is in 'first_name' after first merge; after second merge
   # it gets renamed. Use suffixes consistently.
6. For NOT conditions ("have NOT completed X"):
   completed_ids = df_training[df_training['status'] == 'Completed']['employee_id']
   not_completed = df_employees[~df_employees['employee_id'].isin(completed_ids)]
7. When returning IDs, ALSO include the human-readable name column.
8. Store the final answer in `result` (DataFrame, Series, scalar, or dict).
9. For top-N, use .nlargest(N, 'col') or .sort_values('col', ascending=False).head(N).
10. For scalar answers, include context (e.g. "Engineering dept — INR 45.2 crore").
11. CEO lookup: filter df_employees by job_title containing 'CEO' or
    'Chairman' or 'Managing Director' — do NOT assume employee_id == 1001.
12. Never access a variable not in the list. Never call reset_index() before
    checking what columns exist. Print df.columns if unsure.

QUESTION: {query}

Write ONLY the Python code, no explanation, no markdown fences:"""


def _execute_multi_table_code(code: str, dfs: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Execute LLM-generated pandas code with multiple named DataFrames.

    Extends _execute_pandas_code: sandbox exposes df_<name> for every loaded
    table plus df as the primary (largest) one for backward compat.
    """
    safe, reason = _is_safe_code(code)
    if not safe:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"Code safety check failed: {reason}", "code": code,
        }

    import numpy as np

    sandbox = {
        "__builtins__": _SAFE_BUILTINS,
        "pd": pd,
        "np": np,
    }
    # Expose each DataFrame as df_<name>
    for name, df in dfs.items():
        sandbox[f"df_{name}"] = df.copy()
    # Also expose `df` as the largest DataFrame for single-table-style code
    if dfs:
        primary = max(dfs.items(), key=lambda kv: len(kv[1]))[1]
        sandbox["df"] = primary.copy()

    try:
        exec(code, sandbox)
    except Exception as e:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"{type(e).__name__}: {e}", "code": code,
        }

    raw_result = sandbox.get("result")
    chart = sandbox.get("chart")
    if raw_result is None:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": "Code did not produce a `result` variable.", "code": code,
        }

    # Serialize (same logic as single-table path)
    try:
        if isinstance(raw_result, pd.DataFrame):
            # Replace NaN with None — NaN serializes to invalid JSON "NaN"
            # which breaks browser JSON.parse downstream.
            truncated = raw_result.head(50).where(lambda x: pd.notna(x), None)
            result_data = {
                "columns": list(truncated.columns),
                "rows": truncated.to_dict(orient="records"),
                "total_rows": len(raw_result),
                "truncated": len(raw_result) > 50,
            }
            result_type = "table"
        elif isinstance(raw_result, pd.Series):
            clean_series = raw_result.head(50).where(lambda x: pd.notna(x), None)
            result_data = {
                "columns": [raw_result.name or "value"],
                "rows": [
                    {"index": str(k), raw_result.name or "value": v}
                    for k, v in clean_series.items()
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
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"Failed to serialize result: {e}", "code": code,
        }

    def _jsonify(obj):
        if isinstance(obj, (pd.Timestamp,)):
            return obj.isoformat()
        if hasattr(obj, 'item'):
            val = obj.item()
            if isinstance(val, float) and (val != val):
                return None
            return val
        if isinstance(obj, float) and (obj != obj):
            return None
        return obj

    # Proactively scrub NaN (recursive) — same approach as multi-table path.
    import math as _math
    def _scrub_nan(o):
        if isinstance(o, float) and _math.isnan(o):
            return None
        if hasattr(o, 'item'):
            try:
                v = o.item()
                if isinstance(v, float) and _math.isnan(v):
                    return None
                return v
            except Exception:
                return None
        if isinstance(o, dict):
            return {k: _scrub_nan(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_scrub_nan(x) for x in o]
        if isinstance(o, tuple):
            return tuple(_scrub_nan(x) for x in o)
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        return o

    try:
        scrubbed = _scrub_nan(result_data)
        result_json = json.loads(json.dumps(scrubbed, default=_jsonify))
    except (TypeError, ValueError) as e:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"Failed to serialize result: {e}", "code": code,
        }
    try:
        chart_json = json.loads(json.dumps(_scrub_nan(chart), default=_jsonify)) if chart else None
    except (TypeError, ValueError):
        chart_json = None

    return {
        "ok": True, "result": result_json, "result_type": result_type,
        "chart": chart_json, "error": None, "code": code,
    }


async def find_target_docs(
    query: str,
    doc_ids: list[str] | None,
    user_level: int,
    caller_role: str | None = None,
    max_tables: int = 10,
) -> list[store.Document]:
    """Find multiple tabular docs for a cross-table query.

    Returns docs ordered by relevance. RBAC-filtered to user_level.
    """
    tabular = list_tabular_docs(max_doc_level=user_level)
    if doc_ids:
        scoped = [d for d in tabular if d.doc_id in doc_ids]
        if scoped:
            tabular = scoped
    if not tabular:
        return []

    # Rank: tables whose normalized name appears in the query go first
    q_lower = query.lower()
    def _mentions(doc: store.Document) -> int:
        tname = _table_name_from_filename(doc.filename)
        parts = tname.split("_")
        return sum(1 for p in parts if len(p) >= 3 and p in q_lower)

    tabular.sort(key=lambda d: (-_mentions(d), d.filename))
    return tabular[:max_tables]


def is_multi_table_query(query: str, tabular_doc_count: int = 0) -> bool:
    """Heuristic: detect when a query needs cross-table JOINs.

    Signals:
    - Mentions >1 domain noun (employees, customers, departments, vendors,...)
    - Uses relational phrasing ("per department", "by vendor", "whose manager")
    - Mentions compensation/financial terms AND ≥3 tabular docs are loaded
      (single-table path would pick the wrong file — multi-table lets LLM
      choose the right one from all available schemas)
    """
    q = query.lower()
    _DOMAIN_NOUNS = {
        "employee", "employees", "department", "departments", "salary", "salaries",
        "customer", "customers", "vendor", "vendors", "incident", "incidents",
        "product", "products", "service", "services", "training", "asset",
        "assets", "license", "licenses", "transaction", "transactions",
        "manager", "managers", "account manager",
        # Compensation / financial terms (strong signals even alone)
        "ceo", "cto", "cfo", "executive", "compensation", "pay", "payroll",
        "esop", "equity", "bonus", "ctc", "arr", "revenue",
    }
    hits = sum(1 for noun in _DOMAIN_NOUNS if noun in q)
    if hits >= 2:
        return True

    _RELATIONAL_PATTERNS = [
        "per department", "per employee", "per vendor", "per customer",
        "by department", "by vendor", "by customer",
        "whose ", "who have", "that have", "who has", "that own", "who own",
        "linked to", "managed by", "owned by", "assigned to",
        "for each ", "with unresolved", "with status",
        "ratio", "compared to", "breakdown by",
    ]
    if sum(1 for p in _RELATIONAL_PATTERNS if p in q) >= 1 and hits >= 1:
        return True

    # When many tabular docs are loaded, single-table filename matching is
    # unreliable — filename won't match queries about "pay", "ratio", etc.
    # Route to multi-table so LLM can pick the right schema.
    if tabular_doc_count >= 3 and hits >= 1:
        return True
    return False


async def run_multi_table_query(
    query: str,
    docs: list[store.Document],
    user_level: int,
) -> dict[str, Any]:
    """Run a cross-table analytics query with pandas joins.

    Loads every doc in `docs` as df_<table_name>, exposes all to the LLM,
    lets it generate pandas merge() code, executes in sandbox.
    """
    # RBAC check on every doc
    accessible = [d for d in docs if d.doc_level <= user_level]
    if not accessible:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": "Access denied — no accessible tabular documents for your clearance level.",
            "code": "", "tables": [], "schema": "",
        }

    # Load every accessible doc
    dfs: dict[str, pd.DataFrame] = {}
    load_errors = []
    for doc in accessible:
        try:
            tname = _table_name_from_filename(doc.filename)
            # Uniquify if collision
            if tname in dfs:
                tname = f"{tname}_{doc.doc_id[:6]}"
            dfs[tname] = load_dataframe(doc)
        except Exception as e:
            load_errors.append(f"{doc.filename}: {e}")

    if not dfs:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"Failed to load any tabular data. Errors: {'; '.join(load_errors)}",
            "code": "", "tables": [], "schema": "",
        }

    schema = _multi_table_schema_summary(dfs)
    prompt = MULTI_TABLE_ANALYTICS_PROMPT.format(schema=schema, query=query)

    try:
        code = await _complete_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=800, temperature=0.0,
        )
    except Exception as e:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"LLM code generation failed: {e}",
            "code": "", "tables": list(dfs.keys()), "schema": schema,
        }

    code = (code or "").strip()
    if code.startswith("```"):
        lines = code.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        code = "\n".join(lines).strip()

    if not code:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": "LLM returned empty code.",
            "code": "", "tables": list(dfs.keys()), "schema": schema,
        }

    result = _execute_multi_table_code(code, dfs)

    # Corrective retry on runtime error
    if not result["ok"] and result["error"] and "safety check" not in result["error"]:
        retry_prompt = (
            f"Your previous code failed:\n{result['error']}\n\n"
            f"Original code:\n{code}\n\n"
            f"Fix it. Available DataFrames: {', '.join(f'df_{n}' for n in dfs.keys())}. "
            f"Store the answer in `result`.\n\n"
            f"{schema}\n\nQUESTION: {query}\n\n"
            f"Write ONLY the corrected Python code:"
        )
        try:
            retry_code = await _complete_chat(
                [{"role": "user", "content": retry_prompt}],
                max_tokens=800, temperature=0.0,
            )
            retry_code = (retry_code or "").strip()
            if retry_code.startswith("```"):
                lines = retry_code.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                retry_code = "\n".join(lines).strip()
            if retry_code:
                result = _execute_multi_table_code(retry_code, dfs)
                if result["ok"]:
                    result["code"] = f"# Retry succeeded\n{retry_code}"
        except Exception:
            pass

    result["tables"] = list(dfs.keys())
    result["schema"] = schema
    result["doc_ids"] = [d.doc_id for d in accessible]
    result["filenames"] = [d.filename for d in accessible]
    return result


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
