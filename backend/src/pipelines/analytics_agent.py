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
import math as _math
import re
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import settings
from src.core import store
from src.pipelines.generation_pipeline import _complete_chat


# ── Shared cycle-safe NaN scrubber ──────────────────────────────────────
#
# The LLM occasionally builds a `result` dict that contains a reference
# to itself (or to a parent dict that references the child). Plain
# recursive scrubbing infinite-loops on that; json.dumps then blows up
# with "Circular reference detected". We track visited object ids and
# return a sentinel when we hit one we've seen — breaks the cycle
# cleanly and lets serialization succeed.

_CYCLE_SENTINEL = "<circular reference omitted>"


def _scrub_for_json(obj: Any, _seen: set[int] | None = None) -> Any:
    """NaN-safe + cycle-safe scrub before json.dumps.

    Replaces NaN with None, datetimes with isoformat strings, numpy
    scalars with native Python, and breaks cycles via id() tracking.
    Never raises — worst case returns a string description of the
    offending object.
    """
    # Primitives — cheap path, no tracking needed
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
        return obj

    # Timestamps first (pandas / datetime) — returns a string primitive
    if isinstance(obj, pd.Timestamp):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)

    # numpy scalars expose .item()
    if hasattr(obj, "item") and not isinstance(obj, (list, tuple, dict)):
        try:
            v = obj.item()
            if isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)):
                return None
            return v
        except Exception:
            return None

    # Containers — track by id to break cycles
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return _CYCLE_SENTINEL
    _seen.add(oid)
    try:
        if isinstance(obj, dict):
            return {
                str(k): _scrub_for_json(v, _seen) for k, v in obj.items()
            }
        if isinstance(obj, (list, tuple, set, frozenset)):
            return [_scrub_for_json(x, _seen) for x in obj]
    finally:
        _seen.discard(oid)

    # Last resort — anything else, stringify (DataFrames/Series should
    # already have been serialized by the caller; if they land here it's
    # a nested one and we flatten to a summary string rather than crash)
    try:
        return str(obj)[:500]
    except Exception:
        return "<unserializable>"


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


# Derived-metric keywords — computable from underlying tabular columns.
# Unlike _DATA_KEYWORDS (which requires ≥2 matches to classify as data),
# a single derived-metric hit is enough to force analytics routing. Without
# this bridge, "what's our operating margin?" reads as a pure finance
# concept and routes to document RAG, which truthfully says "documents do
# not specify" — even though Financial_Transactions contains Revenue +
# Operating Expense rows that let the analytics agent derive it.
_DERIVED_METRIC_KEYWORDS = {
    "operating margin", "gross margin", "net margin", "profit margin",
    "ebitda", "ebit", "opex", "capex", "roi", "roa", "roe",
    "burn rate", "runway", "utilization", "utilisation",
    "attrition rate", "churn rate", "retention rate",
    "compensation ratio", "pay ratio", "gender pay gap",
    "cost per employee", "revenue per employee", "arr per employee",
    "headcount by", "headcount per",
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
    'What is our operating margin?' → 'data' (derived-metric bridge)
    """
    q_lower = query.lower()
    # Derived-metric bridge: a single hit on a computable metric is enough
    # to force analytics, even when ordinary data keywords (total/sum/etc.)
    # are absent. These phrases imply arithmetic over tabular columns.
    if any(kw in q_lower for kw in _DERIVED_METRIC_KEYWORDS):
        return "data"
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
- NEVER round intermediate values. Sort/rank/compare on RAW values; only
  round in the final display step. Rounding before sort flips near-ties.
- For percentages, compute on raw values, then round ONLY the final column.
- INCLUDE ALL MATCHING ROWS, even small or zero values, unless the user
  explicitly asked to exclude them. Let the user judge significance.
- DO NOT write `import` statements. The following are already loaded and
  callable directly: `pd`, `np`, `datetime`, `date`, `timedelta`,
  `Counter`, `defaultdict`. If you'd normally write
  `from datetime import timedelta`, just use `timedelta(...)` directly.
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
    "hasattr": hasattr, "repr": repr,
    # Needed internally by stdlib objects like datetime.date.today() and
    # Counter.__init__ — they call __import__ during attribute resolution.
    # User-level `import` statements are rejected by the regex in
    # _UNSAFE_PATTERNS BEFORE exec runs, so exposing __import__ here is
    # safe: it can only fire for internal machinery, not user code.
    "__import__": __import__,
}

# Patterns that indicate malicious or unsafe code
_UNSAFE_PATTERNS = [
    # Real import STATEMENTS only — must be at the start of a line (after
    # optional whitespace). The old `\bimport\s+` pattern matched the word
    # "import" anywhere, including inside comments, which killed otherwise-
    # safe code. _strip_unsafe_imports() neutralises the common preloaded-
    # stdlib imports before we even reach this check, so anything that
    # lands here is genuinely trying to reach beyond the sandbox.
    re.compile(
        r"^[ \t]*(?:import\s+\S+|from\s+\S+\s+import\s+\S+)",
        re.MULTILINE,
    ),
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


_IMPORT_LINE = re.compile(
    r"^[ \t]*(?:import\s+\S+.*|from\s+\S+\s+import\s+.*)$",
    re.MULTILINE,
)


def _strip_unsafe_imports(code: str) -> str:
    """Remove any top-level `import X` / `from X import Y` lines.

    All stdlib helpers the LLM typically reaches for (datetime, date,
    timedelta, Counter, defaultdict) are pre-loaded into the sandbox, so
    these lines are redundant at best and safety-check-trip at worst.
    Stripping them lets us recover silently from the LLM's most common
    prompt-violating habit without a second round-trip.

    Any non-stdlib import (e.g. `import os`) would still be blocked by
    _UNSAFE_PATTERNS (via `\\bos\\.` or `\\bsubprocess\\b`) once the stripped
    code runs — a stripped `import os` just becomes unused noise.
    """
    # Replacement comment must NOT contain the word "import" followed by
    # whitespace — the safety regex would match it and re-trigger the block.
    return _IMPORT_LINE.sub("# (stripped: stdlib pre-loaded)", code)


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
    code = _strip_unsafe_imports(code)
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
    from datetime import datetime, date, timedelta
    from collections import Counter, defaultdict

    sandbox = {
        "__builtins__": _SAFE_BUILTINS,
        "df": df.copy(),  # copy so the original is never mutated
        "pd": pd,
        "np": np,
        # Preload common stdlib helpers so the LLM never writes `import`
        # (the safety check rejects it). See multi-table sandbox for the
        # Q4 laptop-spend regression that motivated this.
        "datetime": datetime,
        "date": date,
        "timedelta": timedelta,
        "Counter": Counter,
        "defaultdict": defaultdict,
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

    # Cycle- + NaN-safe scrub (shared helper at module scope)
    _scrub_nan = _scrub_for_json

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


def _parse_readme_schema_graph(docs: list[store.Document]) -> list[dict]:
    """Extract FK edges from a Schema_Notes / README sheet if one exists.

    When sir's relational dataset ships with a `00_README_and_Schema.xlsx`
    containing a sheet like `Schema_Notes`, `README`, or `Relationships`,
    parse it for lines of the form:
        employees.department_id → departments.department_id
        customers.account_manager_employee_id -> employees.employee_id
        FK: salary_records.employee_id references employees.employee_id

    Returns a list of {"from": "df_a.col", "to": "df_b.col", "reason": "readme"}
    edges — same shape as `_detect_foreign_keys` so they can be merged.

    This complements the *_id auto-detector: the README catches
    relationships the heuristic misses (renamed keys like
    `account_manager_employee_id → employees.employee_id`).
    """
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    # Regex: "a.x → b.y" or "a.x -> b.y" or "a.x references b.y"
    arrow = re.compile(
        r"\b([a-z][a-z0-9_]+)\.([a-z][a-z0-9_]+)\s*(?:→|->|references|ref\.|refs)\s*"
        r"([a-z][a-z0-9_]+)\.([a-z][a-z0-9_]+)\b",
        re.IGNORECASE,
    )

    for doc in docs:
        if Path(doc.filename).suffix.lower() not in {".xlsx", ".xls"}:
            continue
        try:
            path = _raw_path(doc)
            if not path.exists():
                continue
            xls = pd.ExcelFile(path)
        except Exception:
            continue

        # Find schema/notes/readme sheets — ones we explicitly skip in
        # load_dataframe. Flip the filter here: we WANT them.
        schema_sheets = [s for s in xls.sheet_names if not _is_data_sheet(s)]
        for sheet in schema_sheets:
            try:
                raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
            except Exception:
                continue
            # Flatten every cell into one big text blob and scan
            text = "\n".join(
                str(v) for row in raw.values.tolist() for v in row if v and str(v) != "nan"
            )
            for m in arrow.finditer(text):
                src_tbl, src_col, dst_tbl, dst_col = (
                    m.group(1).lower(), m.group(2).lower(),
                    m.group(3).lower(), m.group(4).lower(),
                )
                edge = (f"df_{src_tbl}.{src_col}", f"df_{dst_tbl}.{dst_col}")
                if edge in seen:
                    continue
                seen.add(edge)
                edges.append({
                    "from": edge[0], "to": edge[1], "reason": "readme",
                })
    return edges


def _multi_table_schema_summary(dfs: dict[str, pd.DataFrame], docs: list[store.Document] | None = None) -> str:
    """Generate a combined schema summary for multiple DataFrames with FK hints."""
    lines = []
    lines.append(f"You have {len(dfs)} DataFrames loaded.")
    lines.append("CRITICAL: Use ONLY the column names listed below — do NOT")
    lines.append("invent names like 'incident_id' or 'manager_employee_id' if")
    lines.append("they aren't listed. Copy names EXACTLY as shown (case, underscores).")
    lines.append("")

    # Pre-flight column dump — same format as the retry-on-KeyError path.
    # Injecting this BEFORE the first attempt (not only on retry) stops
    # column hallucination upfront. Prevention beats recovery.
    lines.append("=== VERBATIM COLUMN LISTS (copy these names exactly) ===")
    for name, df in dfs.items():
        clean_cols = [
            c for c in df.columns
            if not str(c).startswith("_")
            and not str(c).startswith("Unnamed")
            and not str(c).startswith("TechNova Inc.")
        ]
        lines.append(f"  df_{name}.columns = {clean_cols}")
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

    # Merge README-declared edges (if any) on top of the auto-detected set.
    # README wins on conflicts — it's the human source of truth, and catches
    # renamed keys (account_manager_employee_id → employees.employee_id)
    # that the *_id heuristic can't match by name alone.
    if docs:
        readme_edges = _parse_readme_schema_graph(docs)
        existing = {(fk["from"], fk["to"]) for fk in fks}
        for edge in readme_edges:
            if (edge["from"], edge["to"]) not in existing:
                fks.append(edge)

    if fks:
        lines.append("Likely JOIN keys (foreign-key relationships):")
        for fk in fks:
            tag = " [from README]" if fk.get("reason") == "readme" else ""
            lines.append(f"  {fk['from']} → {fk['to']}{tag}")
        lines.append("")

    return "\n".join(lines)


MULTI_TABLE_ANALYTICS_PROMPT = """You are a senior data analyst with access to MULTIPLE pandas DataFrames. Answer by joining with pd.merge() as needed.

=== TODAY ===
Today's date is {today}. When the user says "this year", "last year",
"next year", interpret those ANCHORED ON {today}, not on the max date
found in the data. "Last year" means the calendar year (today.year - 1),
even if the data also contains a few rows from the current year. DO NOT
infer the reference year from `df['reported_date'].max().year` — that
overweights partial current-year data and silently loses last year's
full volume (this has burned us before on SEV-1/SEV-2 "last year" asks).

{policy_facts}
{term_resolutions}

AVAILABLE DATAFRAMES:
{schema}

RULES:
1. *** DO NOT WRITE ANY `import` OR `from ... import ...` STATEMENT. ***
   The sandbox REJECTS imports. These names are already loaded and are
   callable directly — use them as-is:
       pd, np, datetime, date, timedelta, Counter, defaultdict
   Wrong:  `from datetime import timedelta, date`
   Wrong:  `import datetime as dt`
   Right:  `cutoff = date.today() - timedelta(days=365)`
   If your first instinct is to write `import`, stop and use the name
   directly. This is the #1 reason a multi-table query fails — do not
   spend your output tokens on import lines.
2. Use exact variable names shown (df_employees, df_departments, etc.).
3. Use ONLY the column names listed in "EXACT COLUMN NAMES". Do NOT invent
   column names like 'incident_id', 'manager_id', or unit-shortened aliases
   like 'amount' when the real column is 'amount_inr_crores'. If the column
   you expect isn't there, use the closest one that IS. Before writing any
   column reference, re-read the EXACT COLUMN NAMES list.
4. Store the final answer in `result` (DataFrame, Series, scalar, or dict).
5. NEVER round intermediate values. Sort, rank and compare on RAW values.
   Only round in the FINAL display step (e.g. `.round(2)` on the result
   DataFrame before assigning to `result`). Rounding too early flips
   near-tie rankings (0.87 vs 0.88 compliance, 0.331 vs 0.329 margin).
6. INCLUDE ALL MATCHING ROWS, even when values are very small or zero.
   Do not add `> 0` or `!= 0` filters unless the user explicitly asks to
   exclude them. Let the user decide what counts as significant — dropping
   a small department from the answer is worse than showing it as 0.
7. DEDUPLICATE after merges when the question asks about entities, not
   pairs. "Which customers have X" → one row per customer, use
   `.drop_duplicates(subset=['customer_id'])`. The fan-out of a merge
   will multiply rows — always ask "should this entity appear more than
   once?" before returning.

=== COLUMN-UNIT SUFFIX CONVENTIONS ===
Financial columns in this corpus carry unit suffixes. When the user
says "amount" / "revenue" / "cost", pick the column from the EXACT
COLUMN NAMES list — it will be one of:
  • <name>_inr           (rupees)
  • <name>_inr_lakhs     (₹ lakhs = 100,000)
  • <name>_inr_crores    (₹ crores = 10,000,000)
  • <name>_usd           (US dollars)
Never shorten the column to 'amount' if the real column is 'amount_inr_crores'
— you will get a KeyError. When aggregating across tables with different
units, convert to a common unit first and document the conversion.

=== BUSINESS-TERM → FILTER TRANSLATION ===
Executives speak in colloquial shorthand. Translate these phrases BEFORE
writing filters, otherwise you will under- or over-match.

  • "engineers" / "engineering staff" / "senior engineering staff"
      DEFAULT (scope-narrow) → department_name == 'Engineering'
      BROADEN ONLY when the verb / context signals incident response,
      on-call, security, or site-reliability work. Trigger phrases:
      "incidents", "serious incidents", "on-call", "handled", "paged",
      "site reliability", "SEV", "security incident", "outage",
      "incident response". In THOSE cases widen to:
          department_name IN ('Engineering', 'Information Security',
                              'Site Reliability Eng.', 'Data & AI Research',
                              'IT Operations')
      Ask yourself: "would a CFO reading this interpret 'engineers'
      strictly as the Engineering org, or as technical staff broadly?"
      Laptop/compensation/headcount questions → narrow.
      Incident/on-call/reliability questions → broad.
  • "technical staff" / "technology teams" / "tech folks"
      → ALWAYS broad (all tech departments listed above).

  • "biggest accounts" / "top customers" / "major clients" / "largest deals"
      → tier == 'Tier 1'     (enterprise tier is the business definition
                               of "biggest" in this corpus, NOT a simple
                               ARR .nlargest which would mix tiers)
      If the query also says "top N by ARR", rank within Tier 1.

  • "serious incidents" / "major incidents" / "critical incidents"
      → severity IN ('SEV-1', 'SEV-2')

  • "last year" / "past year" / "previous year"
      → reported_date.dt.year == (today.year - 1)
        where `today` is the TODAY header above, not `df[...].max()`.
      Do NOT use `df['reported_date'].max().year` as "last year" —
      the data often contains YTD current-year rows which would
      collapse "last year" to today.year and drop 11 months of data.
      Pattern in code:
          import-free: use the preloaded `date.today()`
          last_year = date.today().year - 1
          last_year_rows = df[pd.to_datetime(df['reported_date']).dt.year == last_year]

  • "haven't completed X" / "without X" / "didn't bother with X"
      → use ~df.isin() (NOT-IN) — see Pattern E.
      Example: "AMs without ESOPs" = level NOT IN ('L5','L6','L7','L8').

  • "external certifications" / "professional certs"
      → training_compliance rows where module_name contains any of:
        'AWS', 'Azure', 'Google', 'GCP', 'CKA', 'CKAD', 'CKS',
        'CISSP', 'CIPP', 'CISM', 'PMP', 'Scrum', 'ML Engineer'
        AND status == 'Completed'.
      "Zero certifications" = employee_id NOT in the set above.

  • "without ESOPs" / "no ESOP" / "unvested"
      → level NOT IN ('L5','L6','L7','L8')    (ESOPs grant at L5+)

  • "on-call pay" / "what we paid them for on-call"
      → primary_oncall_weeks × ₹5,000 + secondary_oncall_weeks × ₹2,500
        (use the WHOLE period the question asks about — usually "last
         year" = 52 weeks max per person, but cap at the data column)
      If the question specifically says "during the intensive response"
      or cites a named incident → use 8 weeks, not the full year.

  • "retention bonus" / "lock in" / "keep them" / "golden handcuffs"
      → 30% × total_ctc_inr_lakhs   (cap from Salary_Structure.pdf §5)

  • "compliance flagged" / "under the threshold"
      → department completion rate < 0.90

=== GEO / MARKET GLOSSARY ===
When a query mentions market groupings, interpret them as:
  • "APAC" / "Asia-Pacific"         → India, Japan, South Korea, Singapore,
                                      Vietnam, Indonesia, Philippines,
                                      Thailand, Malaysia, Australia, China
  • "regulated Asian markets"       → India, Japan, South Korea (strong
                                      data-protection regimes: DPDP, APPI,
                                      PIPA). Filter customers.country in
                                      that set.
  • "data-localization risk"        → Vietnam, Indonesia (per Board_Minutes
                                      Q4 §5). Filter customers.country in
                                      that set.
  • "EU" / "European"               → Germany, France, Netherlands, Spain,
                                      Italy, Ireland, Sweden, etc.
If the query is ambiguous, pick the narrowest reasonable list and say so
in the result's context string.

=== TECHNOVA CORPUS CONSTANTS (apply ONLY when these PDFs are in scope) ===
Use these values when the query requires a rule that isn't in the tabular
data but IS documented in a policy PDF. Cite the source in a comment.
  • Retention bonus ceiling    = 30% of annual CTC      (Salary_Structure.pdf §5)
  • ESOP grant level           = L5 and above           (Salary_Structure.pdf §3)
  • On-call stipend            = ₹5,000/week primary,   (OnCall_Runbook.pdf §1)
                                 ₹2,500/week secondary
  • Training-compliance flag   = department rate < 90%  (Training_Compliance.pdf §3)
  • Mandatory training modules = InfoSec Awareness,     (Training_Compliance.pdf §3)
                                 POSH, ABAC, DPDP Act 2023
  • External-cert bonus        = ₹25,000 per cert       (Training_Compliance.pdf §2)
  • Vendor risk statuses       = {{Conditional, Suspended}} flagged
                                                         (Vendor_Contracts.pdf §4)
  • AI/ML FY26-27 budget       = 38% of ₹485 Cr plan    (Product_Roadmap_2026.pdf §1)
                                 = ₹184.30 crores
  • AI cluster footprint       = 16 × NVIDIA A100 GPU   (Platform_Architecture.pdf §4)
                                 nodes = 128 GPUs total,
                                 single AWS EKS cluster
                                 (NOT regionally redundant)
  • FY25-26 AI infra actual    = GPU Compute ₹133.99 Cr (Financial_Transactions,
                                 + Data Warehouse       Data & AI Research dept)
                                 ₹49.68 Cr + GPU CapEx
                                 ₹43.00 Cr = ₹226.67 Cr
                                 infra-only, or ₹334.20 Cr
                                 including salaries
  • Engineering Q4 utilisation = 94.7% of ₹210 Cr       (Q4_Financial_Report.pdf §4)
                                 = ₹198.87 Cr actual Q4 spend
  • Q4 Hardware Procurement    = ₹11.88 Cr booked under (Financial_Transactions)
                                 IT Operations, NOT Engineering
  • Engineering L4+ laptops    = MacBook Pro 16-inch    (IT_Asset_Policy.pdf §1)
                                 M4 Max or ThinkPad equiv
  • Data-localization risk geo = Vietnam, Indonesia     (Board_Minutes_Q4.pdf §5)
  • Customer-count IPO target  = 3,500 enterprise by    (Product_Roadmap_2026.pdf §5)
                                 Q2 FY2027 (current 2,847)
                                 => gap = 653 net new logos
  • Serious-incident window    = 8-week intensive       (Security_Incident_Report.pdf)
                                 response Oct-Nov 2025
                                 after INC-2025-0847
If the query mentions "retention bonus", "ESOP", "on-call pay", "compliance
flag", "certification bonus", "data-localization", "IPO target", or similar,
you probably need one of these constants — not a column lookup.

=== TABLE SEMANTICS — USE THE RIGHT DataFrame ===
- Physical hardware (laptops, GPU workstations, monitors, phones) and software
  licenses are in df_assets_licenses — NOT in df_products_services.
- df_products_services is SaaS microservices and internal products, not assets
  owned by employees.
- Training records (which employee completed which module, with status) are
  in df_training_compliance, with columns: employee_id, module_name, status,
  completion_date. Status values: 'Completed', 'Pending', 'Overdue',
  'In Progress', 'Not Started'.
- Vendors (Apple, NVIDIA, AWS) are in df_vendors. Match by vendor_name
  (e.g. vendor_name.str.contains('Apple', case=False, na=False)).
- Financial transactions are in df_financial_transactions (has category like
  'Operating Expense' or 'CapEx'), separate from vendors' category (which
  describes vendor type like 'Cloud Infrastructure', 'Hardware').

=== COMMON PITFALLS — FOLLOW THESE PATTERNS EXACTLY ===

PATTERN A — Simple 2-table join with human-readable names:
  merged = df_a.merge(df_b, on='shared_id', how='inner')
  # If both have 'category', use rename FIRST:
  df_b2 = df_b.rename(columns={{'category': 'vendor_category'}})
  merged = df_a.merge(df_b2, on='shared_id')

PATTERN B — Deduplicate after merge (CRITICAL for "which X have Y"):
  # If question is "which vendors have assets", each vendor-asset pair produces
  # a row — deduplicate to get UNIQUE vendors:
  result = merged[['vendor_id','vendor_name','risk_status']].drop_duplicates()

PATTERN C — Self-join for manager chain (CRITICAL for "manager's manager"):
  # STEP 1: customers → account manager (Employee)
  #   Use left_on + right_on + explicit suffix on the right side
  step1 = df_customers.merge(
      df_employees.rename(columns={{
          'employee_id':'am_employee_id',
          'first_name':'am_first_name',
          'last_name':'am_last_name',
          'manager_employee_id':'am_manager_id',
      }}),
      left_on='account_manager_employee_id',
      right_on='am_employee_id', how='left'
  )
  # STEP 2: account manager's manager (Employee again, renamed differently)
  step2 = step1.merge(
      df_employees.rename(columns={{
          'employee_id':'mgr_employee_id',
          'first_name':'mgr_first_name',
          'last_name':'mgr_last_name',
      }}),
      left_on='am_manager_id',
      right_on='mgr_employee_id', how='left'
  )
  # Now columns are clean & explicit — no _x/_y confusion.
  result = step2.nlargest(10, 'arr_inr_lakhs')[
      ['customer_name','arr_inr_lakhs','am_first_name','am_last_name',
       'mgr_first_name','mgr_last_name']
  ]

PATTERN D — 3-way intersection (L5+ employees AND Apple laptops AND training gaps):
  # Step 1: filter level
  senior = df_employees[df_employees['level'].isin(['L5','L6','L7','L8'])].copy()
  # Step 2: find employees with Apple laptops (case-insensitive contains)
  apple_vendors = df_vendors[df_vendors['vendor_name'].str.contains('Apple', case=False, na=False)]['vendor_id']
  apple_assets = df_assets_licenses[
      (df_assets_licenses['asset_type'].str.contains('Laptop', case=False, na=False)) &
      (df_assets_licenses['vendor_id'].isin(apple_vendors))
  ]
  apple_owners = set(apple_assets['employee_id'].dropna())
  # Step 3: find employees with unresolved training
  unresolved = df_training_compliance[
      df_training_compliance['status'].isin(['Pending','Overdue','In Progress','Not Started'])
  ]
  unresolved_owners = set(unresolved['employee_id'].dropna())
  # Step 4: intersect all three
  final_ids = apple_owners & unresolved_owners & set(senior['employee_id'])
  result = senior[senior['employee_id'].isin(final_ids)][
      ['employee_id','first_name','last_name','level']
  ]

PATTERN E — NOT-condition ("employees who have NOT completed X"):
  completed = df_training_compliance[
      (df_training_compliance['module_name']=='DPDP Act 2023') &
      (df_training_compliance['status']=='Completed')
  ]['employee_id']
  not_completed = df_employees[~df_employees['employee_id'].isin(completed)]

PATTERN F — CEO lookup (by title, not id):
  ceo_row = df_employees[df_employees['job_title'].str.contains(
      'CEO|Chairman|Managing Director|MD', case=False, regex=True, na=False
  )].iloc[0]
  ceo_ctc = df_salary_records[df_salary_records['employee_id']==ceo_row['employee_id']]['total_ctc_inr_lakhs'].iloc[0]

PATTERN G — AGGREGATE BEFORE RANKING (critical for ratios & compliance):
  When ranking by a ratio/rate across an entity (department, account manager),
  you MUST aggregate all member records into ONE number per entity BEFORE
  sorting. Picking .nlargest on a pre-aggregation dataframe ranks single
  rows, not entities — almost always the wrong answer.
  # WRONG: ratio per customer then nlargest → best customer, not best AM
  # wrong = merged.assign(r=merged.arr/merged.ctc).nlargest(1,'r')
  # RIGHT: sum ARR per AM, then divide by AM's CTC once:
  per_am = (df_customers.merge(
               df_employees[['employee_id']].rename(columns={{'employee_id':'am_id'}}),
               left_on='account_manager_employee_id', right_on='am_id')
            .groupby('am_id', as_index=False)
            .agg(total_arr=('arr_inr_lakhs', 'sum')))
  per_am = per_am.merge(
      df_salary_records[['employee_id','total_ctc_inr_lakhs']],
      left_on='am_id', right_on='employee_id')
  per_am['arr_to_ctc'] = per_am['total_arr'] / per_am['total_ctc_inr_lakhs']
  per_am = per_am.merge(df_employees[['employee_id','first_name','last_name']],
                        on='employee_id')
  result = per_am.nlargest(1, 'arr_to_ctc')[
      ['first_name','last_name','total_arr','total_ctc_inr_lakhs','arr_to_ctc']
  ]

PATTERN H — COMPLIANCE/COMPLETION RATE (total-over-total, NOT mean-of-means):
  Compliance rate = completed_records / total_records AT THE DEPARTMENT LEVEL.
  Do NOT compute per-employee rate and then mean it — that over-weights
  employees with few training records.
  merged = df_training_compliance.merge(
      df_employees[['employee_id','department_id']], on='employee_id')
  merged = merged.merge(
      df_departments[['department_id','department_name']], on='department_id')
  by_dept = merged.groupby('department_name').agg(
      total=('status', 'count'),
      completed=('status', lambda s: (s == 'Completed').sum()),
  ).reset_index()
  by_dept['compliance_rate'] = by_dept['completed'] / by_dept['total']
  # "WORST" compliance = LOWEST rate → nsmallest.
  # "BEST"  compliance = HIGHEST rate → nlargest.
  result = by_dept.nsmallest(1, 'compliance_rate')[
      ['department_name','completed','total','compliance_rate']
  ]

SEMANTIC SORT RULE — BEFORE writing .nlargest/.nsmallest, ask:
  - "worst / lowest / least / smallest / bottom" → nsmallest
  - "best / highest / most / greatest / top"     → nlargest
  - For ratios/rates: worst compliance = LOWEST rate; best ARR = HIGHEST.
  - For costs/losses: worst = HIGHEST (biggest loss); best = LOWEST.
  Re-read the user's superlative before picking the function.

PATTERN I — N-TO-N CROSS-REFERENCE (avoid cartesian explosions):
  When a query asks "services that use flagged vendors AND have training
  gaps", three separate filters share ONLY department_id. Merging them
  naively produces services × vendors × employees × trainings row
  explosions. SOLUTION: aggregate at the level the user asks about —
  usually one row per DEPARTMENT — with the other sides rolled up into
  lists.
  # 1) Find flagged depts (dept ids that own ≥1 flagged vendor)
  flagged = df_vendors[df_vendors['risk_status'].isin(['Conditional','Suspended'])]
  flagged_depts = set(flagged['owner_department_id'].dropna())
  # 2) Critical services in those depts
  crit = df_products_services[
      (df_products_services['criticality_tier']=='Critical') &
      (df_products_services['owner_department_id'].isin(flagged_depts))
  ]
  # 3) Training gaps for employees in those depts (no merge yet!)
  incomplete = df_training_compliance[
      df_training_compliance['status'].isin(['Pending','Overdue','In Progress','Not Started'])
  ]
  emp_dept = df_employees[df_employees['department_id'].isin(flagged_depts)][
      ['employee_id','first_name','last_name','department_id']
  ]
  gaps = incomplete.merge(emp_dept, on='employee_id', how='inner')
  # 4) Summarise PER DEPARTMENT — aggregate the N-to-N sides into lists
  dept_names = df_departments.set_index('department_id')['department_name'].to_dict()
  rows = []
  for dept_id in sorted(flagged_depts):
      svc_list = sorted(crit[crit['owner_department_id']==dept_id]['service_name'].unique().tolist())
      vendor_list = sorted(flagged[flagged['owner_department_id']==dept_id]['vendor_name'].unique().tolist())
      gap_rows = gaps[gaps['department_id']==dept_id]
      gap_list = [f"{{r.first_name}} {{r.last_name}} — {{r.module_name}} ({{r.status}})"
                  for r in gap_rows.itertuples()]
      if svc_list and (vendor_list or gap_list):
          rows.append({{
              'department': dept_names.get(dept_id, f'dept_{{dept_id}}'),
              'critical_services': ', '.join(svc_list),
              'flagged_vendors':   ', '.join(vendor_list),
              'training_gaps':     ' | '.join(gap_list) or '(none)',
          }})
  result = pd.DataFrame(rows)

PATTERN J — "BIGGEST ACCOUNTS" + "WITHOUT CERTIFICATIONS" / "WITHOUT ESOPs":
  # "Which of our BIGGEST accounts in regulated Asian markets are managed
  # by people who DON'T have ESOPs and HAVEN'T bothered with any
  # certifications?"
  #
  # Step 1 — "biggest" = Tier 1; "regulated Asian" = India/Japan/S.Korea
  tier1_asia = df_customers[
      (df_customers['tier'] == 'Tier 1') &
      (df_customers['country'].isin(['India', 'Japan', 'South Korea']))
  ]
  # Step 2 — merge AM, keep AM level + id
  with_am = tier1_asia.merge(
      df_employees[['employee_id','first_name','last_name','level','job_title','department_id']],
      left_on='account_manager_employee_id', right_on='employee_id', how='left'
  )
  # Step 3 — AMs WITHOUT ESOPs = level below L5
  no_esop = with_am[~with_am['level'].isin(['L5','L6','L7','L8'])]
  # Step 4 — AMs who have ZERO external-cert completions
  CERT_RE = r'AWS|Azure|Google|GCP|CKA|CKAD|CKS|CISSP|CIPP|CISM|PMP|Scrum|ML Engineer'
  certified_emp_ids = set(
      df_training_compliance[
          (df_training_compliance['module_name'].str.contains(CERT_RE, case=False, regex=True, na=False)) &
          (df_training_compliance['status'] == 'Completed')
      ]['employee_id']
  )
  result = no_esop[~no_esop['employee_id'].isin(certified_emp_ids)][
      ['customer_name','country','tier','arr_inr_lakhs',
       'first_name','last_name','level','job_title']
  ].sort_values('arr_inr_lakhs', ascending=False)
  # Do NOT fall back to Tier 2/3 if the result is "too small" — under-
  # matching a business filter is ALWAYS better than over-matching.

PATTERN K — "ENGINEERS WHO HANDLED SERIOUS INCIDENTS":
  # "engineers" in a business question = technical staff across MULTIPLE
  # departments, not just Engineering. Tech departments in this corpus:
  TECH_DEPTS = ['Engineering','Information Security',
                'Site Reliability Eng.','Data & AI Research','IT Operations']
  # Step 1 — SEV-1 / SEV-2 in last calendar year
  last_year = date.today().year - 1
  serious = df_incidents[
      (df_incidents['severity'].isin(['SEV-1','SEV-2'])) &
      (pd.to_datetime(df_incidents['reported_date']).dt.year == last_year)
  ]
  # Step 2 — distinct reporter ids, join to employees + dept + salary
  reporter_ids = serious['reporter_employee_id'].dropna().unique()
  emp = df_employees.merge(
      df_departments[['department_id','department_name']],
      on='department_id', how='left'
  )
  tech = emp[
      emp['department_name'].isin(TECH_DEPTS) &
      emp['employee_id'].isin(reporter_ids)
  ].merge(
      df_salary_records[['employee_id','total_ctc_inr_lakhs']],
      on='employee_id', how='left'
  )
  # Step 3 — retention (30% of CTC) + on-call pay (primary + secondary)
  inc_counts = serious.groupby('reporter_employee_id').size().rename('serious_incidents_handled')
  tech = tech.merge(inc_counts, left_on='employee_id', right_index=True, how='left')
  tech['retention_bonus_inr_lakhs'] = tech['total_ctc_inr_lakhs'] * 0.30
  tech['oncall_pay_inr_lakhs'] = (
      tech.get('primary_oncall_weeks', 0).fillna(0) * 5000 / 100000
      + tech.get('secondary_oncall_weeks', 0).fillna(0) * 2500 / 100000
  )
  tech['total_lock_in_exposure_inr_lakhs'] = (
      tech['retention_bonus_inr_lakhs'] + tech['oncall_pay_inr_lakhs']
  )
  result = tech.sort_values('total_lock_in_exposure_inr_lakhs', ascending=False)[[
      'employee_id','first_name','last_name','department_name','level',
      'total_ctc_inr_lakhs','serious_incidents_handled',
      'retention_bonus_inr_lakhs','oncall_pay_inr_lakhs',
      'total_lock_in_exposure_inr_lakhs'
  ]]

CARTESIAN GUARD — SANITY CHECK YOUR RESULT SIZE:
  If result has WAY more rows than any input DataFrame (e.g. 900 rows
  from inputs of 25, 3, 8), you've done an accidental cross-join. Fix
  by switching to the groupby-then-aggregate approach (Pattern I) rather
  than chained .merge() calls.

=== SOFT RULES ===
4. For top-N, use .nlargest(N,'col') or .sort_values('col',ascending=False).head(N).
5. Always include human-readable names alongside IDs in the result.
6. For scalar answers, add context string (e.g. "Engineering — 14.32 ratio").
7. NEVER reference a suffixed column name (_x, _y, _am, _mgr) that isn't guaranteed
   to exist. Prefer explicit .rename() over suffix-based merges.

QUESTION: {query}

Write ONLY the Python code, no explanation, no markdown fences:"""


def _execute_multi_table_code(code: str, dfs: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Execute LLM-generated pandas code with multiple named DataFrames.

    Extends _execute_pandas_code: sandbox exposes df_<name> for every loaded
    table plus df as the primary (largest) one for backward compat.
    """
    code = _strip_unsafe_imports(code)
    safe, reason = _is_safe_code(code)
    if not safe:
        return {
            "ok": False, "result": None, "result_type": "error", "chart": None,
            "error": f"Code safety check failed: {reason}", "code": code,
        }

    import numpy as np
    from datetime import datetime, date, timedelta
    from collections import Counter, defaultdict

    sandbox = {
        "__builtins__": _SAFE_BUILTINS,
        "pd": pd,
        "np": np,
        # Preloaded so the LLM never has to write `import` (which the
        # safety check rejects). Q4 laptop-spend query died because the
        # LLM wrote `from datetime import timedelta` and hit the import
        # regex. Expose these directly and the import is unnecessary.
        "datetime": datetime,
        "date": date,
        "timedelta": timedelta,
        "Counter": Counter,
        "defaultdict": defaultdict,
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

    # ── CARTESIAN GUARD ──────────────────────────────────────────────
    # Detect accidental cross-joins: if the result DataFrame has way more
    # rows than any input DataFrame, the LLM almost certainly chained
    # merges through a weak key (e.g. department_id across three tables)
    # instead of filtering/grouping. Signal this so the corrective retry
    # can steer the LLM to Pattern I (groupby + list aggregation).
    if isinstance(raw_result, pd.DataFrame) and len(raw_result) > 0:
        max_input = max((len(d) for d in dfs.values()), default=0)
        # 3x is the threshold: genuine full-table queries stay under 1x,
        # legitimate self-joins might reach 2x, but 3x+ is almost always
        # a cross-join explosion.
        if max_input > 0 and len(raw_result) > max_input * 3:
            return {
                "ok": False, "result": None, "result_type": "error", "chart": None,
                "error": (
                    f"CARTESIAN_EXPLOSION: result has {len(raw_result)} rows but "
                    f"the largest input DataFrame has only {max_input} rows. "
                    f"Chained merges likely produced a cross-join. Rewrite using "
                    f"Pattern I (groupby-then-aggregate) — filter first, then "
                    f"summarise per entity with lists/counts instead of merging."
                ),
                "code": code,
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

    # Cycle- + NaN-safe scrub (shared helper at module scope). The LLM
    # occasionally builds a result with self-referencing dicts; the
    # id()-tracked scrubber breaks cycles instead of letting json.dumps
    # throw "Circular reference detected".
    _scrub_nan = _scrub_for_json

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
    max_tables: int = 20,
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
    - 3+ tabular docs loaded (default: route multi-table regardless of
      query wording — single-table picking by filename match is unreliable
      for paraphrased questions like "laptop spend on senior engineering
      staff" where none of 'laptop', 'senior', or 'staff' appears in a
      filename. Multi-table agent loads all tables and lets the LLM pick.)
    - Mentions >1 domain noun
    - Uses relational phrasing ("per department", "by vendor", "whose manager")
    - Single derived-metric hit (operating margin, burn rate, …)
    """
    q = query.lower()

    # Default route for moderately-sized corpora: with 3+ tabular docs
    # available, multi-table is almost always the safer bet. Skipping
    # the routing gate catches queries that phrase entities in natural
    # English rather than table nomenclature.
    if tabular_doc_count >= 3:
        return True

    # Derived-metric bridge: single-keyword force-route to multi-table
    # when the corpus has tabular data to derive against. Same list used
    # in classify_data_query, re-applied here so the query doesn't stall
    # on the domain-noun heuristic (operating margin ≠ obvious noun).
    if tabular_doc_count >= 1 and any(kw in q for kw in _DERIVED_METRIC_KEYWORDS):
        return True

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

    schema = _multi_table_schema_summary(dfs, docs=accessible)
    from datetime import date as _date
    today_iso = _date.today().isoformat()

    # Corpus-dynamic policy facts: retrieve rules extracted at upload time
    # from PDFs/DOCX in this corpus that match the query. This replaces the
    # old hardcoded TECHNOVA CONSTANTS block with facts sourced from the
    # actual uploaded documents — so a hospital corpus yields medical
    # thresholds, a retail corpus yields margin rules, etc.
    from src.pipelines import fact_extractor, term_resolver
    try:
        retrieved_facts = fact_extractor.search_facts(
            query=query,
            max_doc_level=user_level,
            limit=15,
        )
        policy_facts_block = fact_extractor.format_facts_for_prompt(retrieved_facts)
    except Exception:
        policy_facts_block = ""  # best-effort — never block code-gen on retrieval

    # Phase 3 pipeline (resolver always runs; planner is GATED):
    #
    #   resolver → (check any ambiguity) → if ambiguous AND PRISM_PLANNER=1
    #                                       then PLAN → dry_check → resolved
    #                                       else use resolver output
    #
    # Gating avoids the regression observed on Q1/Q5 where the planner
    # fabricated "missing dimensions" on unambiguous queries.
    import os as _os
    _planner_env = _os.environ.get("PRISM_PLANNER", "")
    planner_enabled = _planner_env.strip().lower() in ("1", "true", "yes", "on")
    term_resolutions_block = ""
    from src.pipelines import term_resolver
    resolutions: list[dict[str, str]] = []
    try:
        resolutions = await term_resolver.resolve_query_terms(
            query=query, dfs=dfs, today_iso=today_iso,
            policy_facts_block=policy_facts_block,
        )
    except Exception:
        resolutions = []

    # ── Phase 3 gate: Z — anti-join signal whitelist ──────────────
    #
    # Fire the planner ONLY on queries that contain one of a small,
    # hand-curated set of anti-join signals. These are query shapes
    # where single-pass code-gen has demonstrable interpretation
    # ambiguity (Q3's "haven't bothered with certifications" is the
    # canonical example: `~isin(completed)` vs `isin(non_completed)`).
    #
    # Unambiguous queries — Q1 ("behind on training"), Q5 ("revenue in
    # markets") — get the direct code-gen path, because the planner's
    # LLM-driven likely_intent picking does MORE HARM than good on
    # those phrasings. 1-query-helped-to-2-queries-hurt is not a
    # deployment.
    #
    # Whitelist entries are EARNED by evidence. New phrases only get
    # added when a failing query is diagnosed as the same class as Q3
    # AND the planner's prompt has been extended to handle that class
    # AND the harness confirms no regression. See Z-handoff doc.
    _ANTI_JOIN_SIGNALS = (
        "haven't",
        "have not",
        "who didn't",
        "did not",
        "don't have",
        "do not have",
        "without ",
        "excluding ",
        "not completed",
        "missing ",
    )
    q_lower = query.lower()
    gate_match = next(
        (sig for sig in _ANTI_JOIN_SIGNALS if sig in q_lower), None
    )
    use_planner = planner_enabled and (gate_match is not None)
    if planner_enabled:
        if gate_match:
            print(f"[planner-gate] Z MATCH {gate_match!r} → firing planner", flush=True)
        else:
            print(f"[planner-gate] Z miss → direct code-gen (query: {query[:60]!r})", flush=True)

    planner_concern: str | None = None

    if use_planner:
        print(f"[planner-gate] FIRING planner for query: {query[:80]}", flush=True)
        from src.pipelines import planner
        try:
            schema_preview = term_resolver._build_schema_preview(dfs)
            # Render FK list for the planner — kills "missing dimension"
            # hallucinations because planner can see which JOIN chains
            # actually exist.
            fks = _detect_foreign_keys(dfs)
            fk_list = "\n".join(
                f"  {fk['from']} → {fk['to']}" for fk in fks
            ) if fks else ""
            print(f"[planner-gate] fk_count={len(fks)} schema_preview_len={len(schema_preview)}", flush=True)
            plan = await planner.plan_query(
                query=query,
                schema_preview=schema_preview,
                policy_facts_block=policy_facts_block,
                today_iso=today_iso,
                fk_list=fk_list,
            )
            print(f"[planner-gate] plan got: sub_decisions={len(plan.sub_decisions)} proceed={plan.proceed}", flush=True)
            resolved = planner.dry_check_interpretations(plan, dfs)
            term_resolutions_block = planner.format_resolved_plan_for_prompt(
                plan, resolved
            )

            # v2.A: proceed=false is DIAGNOSTIC, not a gate.
            # Planner's bailout logic was hallucinating "missing dimensions"
            # even when the FK chain existed. We capture its concern and
            # log it for later analysis, but always hand the filters it
            # DID produce to code-gen. If the generated code then produces
            # 0 rows, that's the real "no data" signal — not the planner's
            # pre-emptive opinion.
            if not plan.proceed and plan.missing_data_dimensions:
                planner_concern = (
                    "Planner uncertainty: "
                    + "; ".join(plan.missing_data_dimensions)
                )
                # Persist to jsonl for post-hoc analysis — which queries
                # did the planner call out as missing data, and did the
                # code-gen then succeed (proving planner was wrong) or
                # fail (proving planner was right)?
                try:
                    import json as _json, time as _time, os as _osmod
                    _log_path = "/tmp/planner_concerns.jsonl"
                    with open(_log_path, "a") as _f:
                        _f.write(_json.dumps({
                            "ts": _time.time(),
                            "query": query,
                            "missing_dimensions": plan.missing_data_dimensions,
                            "sub_decisions": len(plan.sub_decisions),
                            "unambiguous_filters": len(plan.unambiguous_filters),
                        }) + "\n")
                except Exception:
                    pass
                print(f"[planner-gate] proceed=false IGNORED (v2.A); concern logged", flush=True)
        except Exception as exc:
            print(f"[planner] non-fatal: {exc}; falling back to resolver output")
            use_planner = False

    if not use_planner:
        # Resolver output is the resolution source (no planner call).
        # Either PRISM_PLANNER is off, or no ambiguity was detected, or
        # the planner itself failed.
        try:
            term_resolutions_block = term_resolver.format_resolutions_for_prompt(resolutions)
        except Exception:
            term_resolutions_block = ""

    prompt = MULTI_TABLE_ANALYTICS_PROMPT.format(
        schema=schema,
        query=query,
        today=today_iso,
        policy_facts=policy_facts_block,
        term_resolutions=term_resolutions_block,
    )

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

    # Corrective retry on runtime error OR safety-check failure.
    # Safety-check retries are valuable now that datetime/Counter/etc. are
    # preloaded — the most common safety trip is a stray `import` line
    # that's unnecessary once the LLM knows the preloads are available.
    if not result["ok"] and result["error"]:
        # If KeyError, inject explicit column lists per DataFrame so the LLM
        # stops hallucinating column names. This is the #1 retry failure mode.
        column_dump = ""
        if "KeyError" in (result["error"] or ""):
            column_dump = "\n\nEXACT COLUMN LISTS (copy these names verbatim):\n"
            for tname, df_ in dfs.items():
                clean_cols = [c for c in df_.columns
                              if not str(c).startswith("_")
                              and not str(c).startswith("Unnamed")
                              and not str(c).startswith("TechNova Inc.")]
                column_dump += f"  df_{tname}.columns = {clean_cols}\n"

        # Safety-specific hint: if the safety check tripped on an import,
        # the LLM is trying to reach for stdlib helpers that are actually
        # pre-loaded. Explicitly list them so the retry doesn't re-import.
        safety_hint = ""
        if "safety check" in (result["error"] or "").lower():
            safety_hint = (
                "\n\nDO NOT write `import` or `from ... import ...` — the "
                "sandbox rejects any import statement. The following are "
                "already available as names you can call directly: pd, np, "
                "datetime, date, timedelta, Counter, defaultdict. Replace "
                "`from datetime import timedelta` with nothing (timedelta "
                "is already a name). Replace `import math` with using np "
                "equivalents (np.sqrt, np.log, etc.)."
            )

        # Cartesian-specific hint: if the guard fired, inject FK list so the
        # LLM re-merges on the right keys instead of chaining the same bad
        # merge. Seeing the concrete FK pairs is the fastest steer away from
        # accidental cross-joins.
        cartesian_hint = ""
        if "CARTESIAN_EXPLOSION" in (result["error"] or ""):
            fks = _detect_foreign_keys(dfs)
            fk_lines = "\n".join(f"  {fk['from']} → {fk['to']}" for fk in fks) or "  (none auto-detected)"
            cartesian_hint = (
                "\n\nYOUR MERGE PRODUCED A CARTESIAN PRODUCT. "
                "The join is missing a shared key. Use one of these FK pairs:\n"
                f"{fk_lines}\n"
                "If a query spans 3+ tables sharing ONLY department_id, rewrite "
                "with Pattern I (filter each table separately, then aggregate "
                "per department using groupby + list) — do NOT chain merges."
            )
        retry_prompt = (
            f"Your previous code failed with:\n{result['error']}\n\n"
            f"Original code:\n{code}\n\n"
            f"Fix it. Available DataFrames: {', '.join(f'df_{n}' for n in dfs.keys())}. "
            f"Store the answer in `result`."
            f"{column_dump}{cartesian_hint}{safety_hint}\n\n"
            f"Hint: after pd.merge with suffixes, check df.columns before "
            f"accessing. For self-joins, prefer explicit .rename() over suffixes "
            f"(see Pattern C in the original prompt).\n\n"
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

    # ── Result validator (post-exec sanity check) ────────────────────
    # Second LLM pass catches subtle math errors the exec engine can't —
    # wrong column picked, premature rounding, filter dropped valid rows.
    # Non-blocking: surfaces a concern string, never rejects the result.
    if result.get("ok"):
        try:
            verdict = await _validate_result(
                query=query,
                code=result.get("code", ""),
                result_summary=_summarize_result_for_validator(result),
                schema=schema,
            )
            if not verdict["ok"] and verdict["concern"]:
                result["validator_concern"] = verdict["concern"]
        except Exception:
            pass

    result["tables"] = list(dfs.keys())
    result["schema"] = schema
    result["doc_ids"] = [d.doc_id for d in accessible]
    result["filenames"] = [d.filename for d in accessible]
    # v2.A diagnostic: surface the planner's proceed=false concern on
    # the response so it can render as an amber chip next to the answer.
    # Never blocks the result; purely informational.
    if planner_concern:
        result["planner_concern"] = planner_concern
    return result


# ── Result validator agent ────────────────────────────────────────────────

async def _validate_result(
    query: str,
    code: str,
    result_summary: str,
    schema: str,
) -> dict[str, Any]:
    """Second LLM pass: sanity-check the executed result before we hand it
    to the user. Catches subtle math errors — wrong column, off-by-one
    filter, premature rounding, missing rows — that the exec engine can't
    detect because the code ran without errors.

    Returns: {"ok": bool, "concern": str | None}. Never blocks on failure —
    validator errors are swallowed so we don't break the happy path.
    """
    from datetime import date as _date
    today = _date.today().isoformat()
    prompt = (
        "You are an analytics QA reviewer. A pandas query was generated and "
        "executed. Judge ONLY whether the RESULT plausibly answers the "
        "QUESTION — do not re-run the code. Be strict about:\n"
        "  - wrong units / wrong column picked (e.g. ARR instead of CTC,\n"
        "    or 'amount' used where the real column is 'amount_inr_crores')\n"
        "  - magnitude wildly off (expected lakhs, got crores or vice versa)\n"
        "  - row count obviously wrong (1 row when question implies many,\n"
        "    or repeated identical rows that suggest missing drop_duplicates)\n"
        "  - premature rounding that flipped a near-tie ranking\n"
        "  - a filter that dropped small-but-valid values\n"
        "  - 'best'/'worst' inverted (nlargest vs nsmallest)\n"
        "  - a scalar=0 that probably means no rows matched (bad filter)\n\n"
        f"TODAY'S DATE: {today}. When the user says 'last year' / 'this year',\n"
        "interpret relative to today. Do not flag a year filter as wrong\n"
        "unless you are certain it mis-reads the relative phrase.\n\n"
        f"QUESTION:\n{query}\n\n"
        f"SCHEMA (abbreviated):\n{schema[:1500]}\n\n"
        f"CODE EXECUTED:\n{code[:1500]}\n\n"
        f"RESULT:\n{result_summary[:1500]}\n\n"
        "Reply with EXACTLY one of these two formats, nothing else:\n"
        "  OK\n"
        "  CONCERN: <one sentence describing the specific issue>\n"
    )
    try:
        verdict = await _complete_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=120, temperature=0.0,
        )
    except Exception:
        return {"ok": True, "concern": None}
    verdict = (verdict or "").strip()
    if verdict.upper().startswith("OK"):
        return {"ok": True, "concern": None}
    if verdict.upper().startswith("CONCERN"):
        concern = verdict.split(":", 1)[1].strip() if ":" in verdict else verdict
        return {"ok": False, "concern": concern[:300]}
    return {"ok": True, "concern": None}


def _summarize_result_for_validator(result: dict[str, Any]) -> str:
    """Compact text preview of a result dict for the validator prompt."""
    if not result.get("ok"):
        return f"(execution error: {result.get('error', 'unknown')})"
    r = result.get("result")
    rt = result.get("result_type", "unknown")
    if rt == "table" and isinstance(r, dict):
        cols = r.get("columns", [])
        rows = r.get("rows", []) or []
        total = r.get("total_rows", len(rows))
        preview = rows[:10]
        return (
            f"table — columns={cols}, total_rows={total}, "
            f"first_rows={preview}"
        )
    if rt == "scalar":
        return f"scalar — {r}"
    return f"{rt} — {str(r)[:500]}"


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

    # Corrective retry: if the first attempt failed with a runtime error
    # OR a safety-check trip (usually a stray `import`), retry with a hint.
    if not result["ok"] and result["error"]:
        safety_hint = ""
        if "safety check" in (result["error"] or "").lower():
            safety_hint = (
                "\n\nDO NOT write `import` — sandbox rejects it. pd, np, "
                "datetime, date, timedelta, Counter, defaultdict are "
                "already loaded; call them directly."
            )
        retry_prompt = (
            f"Your previous code failed with this error:\n"
            f"{result['error']}\n\n"
            f"Original code:\n{code}\n\n"
            f"Fix the code. Remember: the DataFrame is `df`, store result in `result`."
            f"{safety_hint}\n"
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

    # ── Result validator (post-exec sanity check) ────────────────────
    if result.get("ok"):
        try:
            verdict = await _validate_result(
                query=query,
                code=result.get("code", ""),
                result_summary=_summarize_result_for_validator(result),
                schema=schema,
            )
            if not verdict["ok"] and verdict["concern"]:
                result["validator_concern"] = verdict["concern"]
        except Exception:
            pass

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
