"""Schema profiler — deterministic, LLM-free analysis of tabular data.

Pure functions over pandas DataFrames. Given a DataFrame + filename,
produces a structured TableProfile with column types, value distributions,
unit inference, and business-term candidates. profile_corpus() combines
N tables and adds inferred foreign-key candidates via name match + value
overlap. format_profile_for_prompt() renders a CorpusProfile into a text
block the analytics-agent LLM can read as its schema context, replacing
the hardcoded TECHNOVA_CORPUS_CONSTANTS + BUSINESS-TERM GLOSSARY + TABLE
SEMANTICS blocks when PRISM_DYNAMIC_PROFILER=1.

No side effects: no store writes, no LLM calls, no IO. Safe to call
anywhere a DataFrame is in memory.

See `profiler_DESIGN.md` in this directory for the full U1a spec +
TechNova-ism audit.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


# ── Tuning constants ───────────────────────────────────────────────────

# Row cap for profile stat computation. Tables above this threshold get
# sampled to keep profile generation under ~1s even on millions of rows.
_SAMPLE_ROWS = 10_000

# Categorical ceiling: a string/object column is treated as "categorical"
# if unique_count <= max(absolute_ceiling, relative_ceiling * row_count).
# Example: 50k-row table with 20 unique dept names is categorical; 50k-row
# table with 5000 unique customer names is text (freeform).
_CATEGORICAL_ABSOLUTE_CEILING = 50
_CATEGORICAL_RELATIVE_CEILING = 0.10

# Unit-inference suffix patterns. Longer/more-specific first — first match
# wins. Cover common currency/duration/percent/count naming conventions.
_UNIT_SUFFIXES = [
    ("_inr_lakhs", "INR_lakhs"),
    ("_inr_crores", "INR_crores"),
    ("_inr_cr", "INR_crores"),
    ("_inr", "INR"),
    ("_usd", "USD"),
    ("_eur", "EUR"),
    ("_gbp", "GBP"),
    ("_hours", "hours"),
    ("_days", "days"),
    ("_weeks", "weeks"),
    ("_months", "months"),
    ("_years", "years"),
    ("_pct", "percent"),
    ("_percent", "percent"),
    ("_rate", "rate"),
    ("_ratio", "ratio"),
    ("_count", "count"),
]

_UNIT_PREFIXES = [
    ("num_", "count"),
    ("n_", "count"),
    ("count_of_", "count"),
]

# Token-level stopwords for business-term candidate extraction. Dropped
# when decomposing column names into candidate terms.
_TERM_STOPWORDS = {
    "id", "key", "pk", "fk",
    "the", "a", "an", "of", "to", "in", "on",
    "value", "val", "data",
}

# Role hints attached to columns. Prompt consumers use these to decide
# filter vs aggregate vs group-by. Not ground truth — heuristic signal.
ROLE_PK_CANDIDATE = "primary_key_candidate"
ROLE_CATEGORICAL = "categorical"
ROLE_ORDERABLE = "orderable"
ROLE_MONETARY = "monetary"
ROLE_SEGMENTATION = "segmentation"
ROLE_TEMPORAL = "temporal"
ROLE_MEASURE = "measure"
ROLE_TEXT = "text"
ROLE_BOOLEAN = "boolean"


# ── Dataclasses ────────────────────────────────────────────────────────

@dataclass
class ColumnProfile:
    name: str
    dtype: str  # id | categorical | numeric | datetime | text | boolean
    null_rate: float
    unique_count: Optional[int] = None
    unique_values: Optional[list] = None          # up to 20 for categorical/boolean
    top_frequencies: Optional[dict] = None        # {value: count} for top-K
    numeric_min: Optional[float] = None
    numeric_max: Optional[float] = None
    numeric_mean: Optional[float] = None
    numeric_median: Optional[float] = None
    unit_inferred: Optional[str] = None
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    role_hints: list[str] = field(default_factory=list)
    business_term_candidates: list[str] = field(default_factory=list)


@dataclass
class TableProfile:
    table_id: str       # normalized identifier, e.g. 'df_customers'
    filename: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "TableProfile":
        return cls.from_dict(json.loads(raw))

    @classmethod
    def from_dict(cls, d: dict) -> "TableProfile":
        cols = [ColumnProfile(**col) for col in d.get("columns", [])]
        return cls(
            table_id=d["table_id"],
            filename=d["filename"],
            row_count=int(d.get("row_count", 0)),
            column_count=int(d.get("column_count", 0)),
            columns=cols,
        )


@dataclass
class ForeignKeyCandidate:
    from_table: str
    from_col: str
    to_table: str
    to_col: str
    overlap_pct: float
    confidence: str  # high | medium | low


@dataclass
class CorpusProfile:
    table_count: int
    tables: list[TableProfile] = field(default_factory=list)
    foreign_keys: list[ForeignKeyCandidate] = field(default_factory=list)
    unit_dictionary: dict[str, list[str]] = field(default_factory=dict)
    created_at: str = ""


# ── Helpers ────────────────────────────────────────────────────────────

def _normalize_table_id(filename: str) -> str:
    """Filename → 'df_<slug>'. '04_Customers.xlsx' → 'df_customers'.
    Matches the naming the analytics agent uses for DataFrame variables."""
    stem = Path(filename).stem.lower()
    stem = re.sub(r"^[0-9_]+", "", stem)
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return f"df_{stem}" if stem else "df_table"


def _infer_unit(col_name: str) -> Optional[str]:
    lower = col_name.lower()
    for suffix, unit in _UNIT_SUFFIXES:
        if lower.endswith(suffix):
            return unit
    for prefix, unit in _UNIT_PREFIXES:
        if lower.startswith(prefix):
            return unit
    return None


def _split_term_tokens(col_name: str) -> list[str]:
    """Decompose a column name into term tokens. Handles snake_case +
    camelCase + digits."""
    pieces = re.split(r"[_\-\s]+", col_name.lower())
    out: list[str] = []
    for p in pieces:
        sub = re.findall(r"[a-z]+|[0-9]+", p)
        out.extend(sub)
    return [t for t in out if t]


def _business_term_candidates(col_name: str) -> list[str]:
    """Business-term candidates from a column name. Non-stopword, non-digit,
    length ≥ 2 tokens. Order preserved; deduplicated."""
    tokens = _split_term_tokens(col_name)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t in _TERM_STOPWORDS or t.isdigit() or len(t) < 2:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _is_boolean_series(series: pd.Series) -> bool:
    """True when the series has ≤2 unique non-null values matching a
    standard boolean encoding."""
    if pd.api.types.is_bool_dtype(series):
        return True
    non_null = series.dropna()
    if non_null.empty:
        return False
    try:
        uniques = {str(v).lower() for v in non_null.unique()}
    except Exception:
        return False
    if len(uniques) > 2:
        return False
    bool_sets = [
        {"true", "false"},
        {"yes", "no"},
        {"y", "n"},
        {"0", "1"},
        {"0.0", "1.0"},
        {"t", "f"},
    ]
    return any(uniques <= s for s in bool_sets)


def _is_datetime_series(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    non_null = series.dropna().astype(str)
    if non_null.empty:
        return False
    sample = non_null.head(20)
    try:
        parsed = pd.to_datetime(sample, errors="coerce")
        return parsed.notna().mean() >= 0.8
    except Exception:
        return False


_ID_NAME_PATTERN = re.compile(r"(?:^|_)id$|(?:^|_)key$", re.IGNORECASE)


def _classify_column(name: str, series: pd.Series, row_count: int) -> str:
    """One of: id | categorical | numeric | datetime | text | boolean."""
    # Boolean check first — catches 0/1 ints, yes/no strings, true/false
    # as distinct from general numeric or categorical columns.
    if _is_boolean_series(series):
        return "boolean"
    # Numeric — demote to 'id' if fully unique AND name suggests id.
    if pd.api.types.is_numeric_dtype(series):
        if row_count > 0:
            try:
                uq = int(series.nunique(dropna=True))
                if uq == row_count and _ID_NAME_PATTERN.search(name):
                    return "id"
            except Exception:
                pass
        return "numeric"
    # Datetime (either native or parseable strings).
    if _is_datetime_series(series):
        return "datetime"
    # Object/string branch.
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        try:
            uq = int(series.nunique(dropna=True))
        except Exception:
            return "text"
        if row_count > 0 and uq == row_count:
            if _ID_NAME_PATTERN.search(name):
                return "id"
            return "text"
        cap = max(
            _CATEGORICAL_ABSOLUTE_CEILING,
            int(row_count * _CATEGORICAL_RELATIVE_CEILING),
        )
        if uq <= cap:
            return "categorical"
        return "text"
    return "text"


def _role_hints_for(
    name: str,
    dtype: str,
    unit: Optional[str],
    unique_values: Optional[list],
) -> list[str]:
    hints: list[str] = []
    lower = name.lower()
    if dtype == "id":
        hints.append(ROLE_PK_CANDIDATE)
    elif dtype == "categorical":
        hints.append(ROLE_CATEGORICAL)
        seg_hit = any(kw in lower for kw in ("segment", "tier", "category", "grade", "class", "level"))
        if seg_hit:
            hints.append(ROLE_SEGMENTATION)
        elif unique_values:
            try:
                if any(
                    re.search(r"tier|segment|grade|class|level", str(v).lower())
                    for v in unique_values
                ):
                    hints.append(ROLE_SEGMENTATION)
            except Exception:
                pass
    elif dtype == "numeric":
        hints.append(ROLE_MEASURE)
        hints.append(ROLE_ORDERABLE)
        if unit in ("INR", "INR_lakhs", "INR_crores", "USD", "EUR", "GBP"):
            hints.append(ROLE_MONETARY)
    elif dtype == "datetime":
        hints.append(ROLE_TEMPORAL)
        hints.append(ROLE_ORDERABLE)
    elif dtype == "text":
        hints.append(ROLE_TEXT)
    elif dtype == "boolean":
        hints.append(ROLE_BOOLEAN)
    return hints


def _strip_id_suffix(col_lower: str) -> str:
    return col_lower.removesuffix("_id").removesuffix("_key")


# ── Public API ─────────────────────────────────────────────────────────

def profile_column(name: str, series: pd.Series, row_count: int) -> ColumnProfile:
    """Per-column profile. `row_count` is the table's row count (not the
    series length, which may differ when the series is a sample)."""
    try:
        null_count = int(series.isna().sum())
    except Exception:
        null_count = 0
    null_rate = (null_count / row_count) if row_count else 0.0

    dtype = _classify_column(name, series, row_count)
    unit = _infer_unit(name)

    prof = ColumnProfile(
        name=name,
        dtype=dtype,
        null_rate=round(float(null_rate), 4),
    )
    try:
        prof.unique_count = int(series.nunique(dropna=True))
    except Exception:
        prof.unique_count = None

    if dtype == "numeric":
        try:
            prof.numeric_min = float(series.min())
            prof.numeric_max = float(series.max())
            prof.numeric_mean = round(float(series.mean()), 4)
            prof.numeric_median = float(series.median())
        except Exception:
            pass
        prof.unit_inferred = unit
    elif dtype == "categorical":
        non_null = series.dropna()
        try:
            uq_list = non_null.unique().tolist()[:20]
            prof.unique_values = [str(v) for v in uq_list]
        except Exception:
            prof.unique_values = None
        try:
            top = non_null.value_counts().head(5).to_dict()
            prof.top_frequencies = {str(k): int(v) for k, v in top.items()}
        except Exception:
            pass
    elif dtype == "datetime":
        try:
            parsed = pd.to_datetime(series, errors="coerce")
            non_null = parsed.dropna()
            if not non_null.empty:
                prof.date_min = str(non_null.min().date())
                prof.date_max = str(non_null.max().date())
        except Exception:
            pass
    elif dtype == "boolean":
        try:
            non_null = series.dropna()
            prof.unique_values = [str(v) for v in non_null.unique().tolist()[:2]]
        except Exception:
            pass
    elif dtype == "text":
        try:
            top = series.dropna().value_counts().head(3).to_dict()
            prof.top_frequencies = {str(k)[:80]: int(v) for k, v in top.items()}
        except Exception:
            pass
    # 'id' dtype intentionally skips value dumps — the values themselves
    # are uninformative and could leak PII into the prompt context.

    prof.role_hints = _role_hints_for(name, dtype, unit, prof.unique_values)
    prof.business_term_candidates = _business_term_candidates(name)
    return prof


def profile_table(df: pd.DataFrame, filename: str) -> TableProfile:
    """Deterministic profile of a single table. Pure function."""
    row_count = len(df)
    if row_count > _SAMPLE_ROWS:
        work_df = df.sample(n=_SAMPLE_ROWS, random_state=42)
    else:
        work_df = df

    columns = [
        profile_column(col, work_df[col], len(work_df)) for col in work_df.columns
    ]
    return TableProfile(
        table_id=_normalize_table_id(filename),
        filename=filename,
        row_count=row_count,
        column_count=len(work_df.columns),
        columns=columns,
    )


def _infer_foreign_keys(
    tables: list[TableProfile],
    data_by_id: dict[str, pd.DataFrame],
) -> list[ForeignKeyCandidate]:
    """Heuristic FK inference. Requires (a) name match (exact or after
    stripping `_id`/`_key` suffix) + (b) ≥ 50% value overlap."""
    candidates: list[ForeignKeyCandidate] = []
    pk_locs: list[tuple[str, str]] = [
        (tp.table_id, c.name) for tp in tables for c in tp.columns if c.dtype == "id"
    ]
    if not pk_locs:
        return candidates

    for tp in tables:
        for c in tp.columns:
            if c.dtype == "id":
                continue  # PKs aren't FKs (same table)
            col_lower = c.name.lower()
            if not re.search(r"_id$|_key$|id$|key$", col_lower):
                continue
            stem_fk = _strip_id_suffix(col_lower)

            for (pk_tid, pk_col) in pk_locs:
                if pk_tid == tp.table_id:
                    continue  # skip same table
                pk_lower = pk_col.lower()
                stem_pk = _strip_id_suffix(pk_lower)
                # Match requires either exact name OR equal stem
                if pk_lower != col_lower and (not stem_fk or stem_fk != stem_pk):
                    continue

                df_from = data_by_id.get(tp.table_id)
                df_to = data_by_id.get(pk_tid)
                if df_from is None or df_to is None:
                    continue
                try:
                    from_vals = set(df_from[c.name].dropna().astype(str).unique())
                    to_vals = set(df_to[pk_col].dropna().astype(str).unique())
                except Exception:
                    continue
                if not from_vals:
                    continue
                overlap = len(from_vals & to_vals) / len(from_vals)
                if overlap < 0.50:
                    continue
                confidence = (
                    "high" if overlap >= 0.80
                    else ("medium" if overlap >= 0.60 else "low")
                )
                candidates.append(ForeignKeyCandidate(
                    from_table=tp.table_id,
                    from_col=c.name,
                    to_table=pk_tid,
                    to_col=pk_col,
                    overlap_pct=round(overlap, 3),
                    confidence=confidence,
                ))
    return candidates


def profile_corpus(tables: list[tuple[str, pd.DataFrame]]) -> CorpusProfile:
    """Profile N tables + infer cross-table relationships.

    Input:  list of (filename, DataFrame).
    Output: CorpusProfile (table profiles + FK candidates + unit dictionary).
    """
    table_profiles = [profile_table(df, fn) for (fn, df) in tables]
    data_by_id = {_normalize_table_id(fn): df for (fn, df) in tables}
    fks = _infer_foreign_keys(table_profiles, data_by_id)

    unit_dict: dict[str, list[str]] = {}
    for tp in table_profiles:
        for c in tp.columns:
            if c.unit_inferred:
                unit_dict.setdefault(c.unit_inferred, []).append(f"{tp.table_id}.{c.name}")

    return CorpusProfile(
        table_count=len(table_profiles),
        tables=table_profiles,
        foreign_keys=fks,
        unit_dictionary=unit_dict,
        created_at=datetime.utcnow().isoformat(timespec="seconds"),
    )


def format_profile_for_prompt(profile: CorpusProfile) -> str:
    """Render a corpus profile as a compact schema block the analytics-
    agent LLM can read. Replaces the TECHNOVA_CORPUS_CONSTANTS +
    BUSINESS-TERM GLOSSARY + TABLE SEMANTICS blocks when
    PRISM_DYNAMIC_PROFILER=1."""
    lines: list[str] = ["=== DYNAMIC CORPUS SCHEMA ==="]
    lines.append(
        f"Profiled {profile.table_count} table(s) at upload. Use this block "
        f"as ground truth for column names, types, value distributions, and "
        f"cross-table relationships — NOT memorized facts about any "
        f"previous corpus."
    )
    lines.append("")

    for tp in profile.tables:
        lines.append(
            f"— {tp.table_id}  (from {tp.filename}, {tp.row_count} rows, "
            f"{tp.column_count} columns)"
        )
        for c in tp.columns:
            bits: list[str] = [f"  {c.name}: {c.dtype}"]
            if c.dtype == "numeric":
                if c.numeric_min is not None and c.numeric_max is not None:
                    bits.append(f"range [{c.numeric_min:g}..{c.numeric_max:g}]")
                    if c.numeric_median is not None:
                        bits.append(f"median {c.numeric_median:g}")
                if c.unit_inferred:
                    bits.append(f"unit={c.unit_inferred}")
            elif c.dtype == "categorical" and c.unique_values is not None:
                preview = ", ".join(repr(v) for v in c.unique_values[:8])
                more = "" if len(c.unique_values) <= 8 else f", +{len(c.unique_values) - 8} more"
                bits.append(f"values: {{{preview}{more}}}")
            elif c.dtype == "boolean" and c.unique_values:
                bits.append(
                    f"values: {{{', '.join(repr(v) for v in c.unique_values)}}}"
                )
            elif c.dtype == "datetime" and c.date_min and c.date_max:
                bits.append(f"range {c.date_min} .. {c.date_max}")
            elif c.dtype == "id":
                bits.append(f"unique_count={c.unique_count}")
            elif c.dtype == "text" and c.unique_count is not None:
                bits.append(f"unique_count={c.unique_count}")

            if c.null_rate > 0.001:
                bits.append(f"null_rate={c.null_rate:.2%}")
            if c.role_hints:
                bits.append(f"role={'|'.join(c.role_hints)}")
            lines.append("  ".join(bits))
        lines.append("")

    if profile.foreign_keys:
        lines.append("— Foreign-key candidates (inferred by name + value overlap):")
        for fk in profile.foreign_keys:
            lines.append(
                f"  {fk.from_table}.{fk.from_col}  →  "
                f"{fk.to_table}.{fk.to_col}  "
                f"(overlap={fk.overlap_pct:.0%}, confidence={fk.confidence})"
            )
        lines.append("")

    if profile.unit_dictionary:
        lines.append("— Columns grouped by inferred unit:")
        for unit, cols in profile.unit_dictionary.items():
            preview = cols[:6]
            more = "" if len(cols) <= 6 else f", +{len(cols) - 6} more"
            lines.append(f"  {unit}: {', '.join(preview)}{more}")
        lines.append("")

    lines.append("=== END DYNAMIC CORPUS SCHEMA ===")
    return "\n".join(lines)
