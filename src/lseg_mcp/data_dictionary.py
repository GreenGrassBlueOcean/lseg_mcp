"""
Extended Data Dictionary Engine for lseg-mcp.

Provides fuzzy search over the broader LSEG/TR data item dictionary
(Pricing, Estimates, ESG, Ownership, Reference, News, etc.) beyond
the specialized Financials fundamentals mapping matrix.

Sources (in priority):
1. User-provided Excel/CSV via LSEG_DATA_DICTIONARY_PATH or "Custom_Fields" /
   "Extended Data Dictionary" / "Data Dictionary" sheet in the main mapping xlsx.
2. High-quality built-in seed mined from RefinitivR examples, docs, and
   common production usage patterns (TR.* fields + specialized rd_* surfaces).
3. Future: mined from live DIB/Screener "Export as Formulas" imports.

This enables the LLM to confidently generate ld.get_data / rd_GetData calls
(and specialized rd_GetEstimates / rd_GetESG when appropriate) for the
full range of content the user has in Workspace.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

# ── High-value built-in seed (mined + curated from RefinitivR + real usage) ──
# These are real, commonly used fields that work with rd_GetData / ld.get_data.
# Categories help route to best API surface (get_data vs specialized functions).
_BUILTIN_SEED: list[dict[str, Any]] = [
    # Pricing / Market Data (very high frequency)
    {"field": "TR.PriceClose", "description": "Closing price (adjusted by default in many contexts)", "category": "Pricing", "parameters": "SDate, EDate, Frq, Curn, Adjusted", "notes": "Core daily close. Use with rd_GetHistory for series."},
    {"field": "TR.PriceOpen", "description": "Open price", "category": "Pricing", "parameters": "SDate, EDate, Frq", "notes": ""},
    {"field": "TR.HighPrice", "description": "High price", "category": "Pricing", "parameters": "SDate, EDate, Frq", "notes": ""},
    {"field": "TR.LowPrice", "description": "Low price", "category": "Pricing", "parameters": "SDate, EDate, Frq", "notes": ""},
    {"field": "TR.Volume", "description": "Trading volume", "category": "Pricing", "parameters": "SDate, EDate, Frq", "notes": ""},
    {"field": "TR.Turnover", "description": "Turnover / value traded", "category": "Pricing", "parameters": "", "notes": ""},
    {"field": "TR.Bid", "description": "Bid price (real-time or last)", "category": "Pricing", "parameters": "", "notes": "Streaming or snapshot friendly."},
    {"field": "TR.Ask", "description": "Ask price", "category": "Pricing", "parameters": "", "notes": ""},
    {"field": "TR.CLOSEPRICE", "description": "Close price (often used with parameters like Adjusted=0)", "category": "Pricing", "parameters": "Adjusted, SDate", "notes": "Legacy casing variant; TR.PriceClose preferred in modern docs."},
    {"field": "TR.MIDPRICE", "description": "Mid price", "category": "Pricing", "parameters": "", "notes": ""},

    # Reference / Descriptive
    {"field": "TR.CompanyName", "description": "Company legal or display name", "category": "Reference", "parameters": "", "notes": "Always safe starter field."},
    {"field": "TR.RIC", "description": "Reuters Instrument Code", "category": "Reference", "parameters": "", "notes": ""},
    {"field": "TR.PrimaryInstrument", "description": "Primary listing RIC for the instrument", "category": "Reference", "parameters": "", "notes": "Critical for corporate action / share data alignment."},
    {"field": "TR.Ticker", "description": "Ticker symbol", "category": "Reference", "parameters": "", "notes": ""},
    {"field": "TR.ExchangeName", "description": "Exchange name", "category": "Reference", "parameters": "", "notes": ""},
    {"field": "TR.InstrumentType", "description": "Instrument type classification", "category": "Reference", "parameters": "", "notes": ""},
    {"field": "TR.ISIN", "description": "ISIN code", "category": "Reference", "parameters": "", "notes": ""},
    {"field": "TR.SEDOL", "description": "SEDOL code", "category": "Reference", "parameters": "", "notes": ""},
    {"field": "TR.CompanyMarketCap", "description": "Market capitalization", "category": "Reference", "parameters": "SDate, Scale, Curn, ShType", "notes": "Commonly used with Scale=6 or ShType=FFL."},
    {"field": "TR.IssueMarketCap", "description": "Issue-level market cap", "category": "Reference", "parameters": "Scale, ShType", "notes": ""},
    {"field": "TR.FreeFloatPct", "description": "Free float percentage", "category": "Reference", "parameters": "ShType", "notes": "Often divided by 100 for weights."},
    {"field": "TR.IssueSharesOutstanding", "description": "Shares outstanding for the issue", "category": "Reference", "parameters": "Scale, ShType", "notes": ""},
    {"field": "TR.EnterpriseValue", "description": "Enterprise value", "category": "Reference", "parameters": "SDate, Curn", "notes": ""},

    # Fundamentals / P&L (overlap with mapping matrix but direct TR.* also work)
    {"field": "TR.Revenue", "description": "Total Revenue", "category": "Fundamentals", "parameters": "SDate, EDate, Frq, Curn, Period", "notes": "Direct TR. field; mapping matrix provides industry FCC for normalized."},
    {"field": "TR.GrossProfit", "description": "Gross Profit", "category": "Fundamentals", "parameters": "SDate, EDate, Frq, Curn", "notes": ""},
    {"field": "TR.EBITDA", "description": "EBITDA", "category": "Fundamentals", "parameters": "", "notes": ""},
    {"field": "TR.EPS", "description": "Earnings per share (reported)", "category": "Fundamentals", "parameters": "", "notes": ""},

    # Estimates / I/B/E/S (use rd_GetEstimates for best results, or TR.* via get_data)
    {"field": "TR.EPSMean", "description": "Mean / consensus EPS estimate", "category": "Estimates", "parameters": "SDate, Period, Broker", "notes": "Prefer rd_GetEstimates(view=..., package=...) for full consensus history."},
    {"field": "TR.RevenueMean", "description": "Mean / consensus Revenue estimate", "category": "Estimates", "parameters": "SDate, Period", "notes": ""},
    {"field": "TR.EBITMean", "description": "Mean EBIT estimate", "category": "Estimates", "parameters": "", "notes": ""},
    {"field": "TR.PriceTargetMean", "description": "Mean analyst price target", "category": "Estimates", "parameters": "SDate", "notes": ""},
    {"field": "TR.NumEstimates", "description": "Number of analyst estimates contributing", "category": "Estimates", "parameters": "", "notes": ""},
    {"field": "TR.EPS", "description": "Actual or estimate EPS (context dependent)", "category": "Estimates", "parameters": "", "notes": "See rd_GetEstimates for actuals vs summary views."},

    # ESG (best via specialized rd_GetESG / ld content; some TR. fields exist)
    {"field": "TR.ESGScore", "description": "Overall ESG Score", "category": "ESG", "parameters": "SDate, Period", "notes": "Use rd_GetESG(view='scores-full') for pillars and full history."},
    {"field": "TR.ESGCombinedScore", "description": "ESG Combined Score (controversies adjusted)", "category": "ESG", "parameters": "", "notes": ""},
    {"field": "TR.EnvironmentPillarScore", "description": "Environmental pillar score", "category": "ESG", "parameters": "", "notes": ""},
    {"field": "TR.SocialPillarScore", "description": "Social pillar score", "category": "ESG", "parameters": "", "notes": ""},
    {"field": "TR.GovernancePillarScore", "description": "Governance pillar score", "category": "ESG", "parameters": "", "notes": ""},

    # Other high-value
    {"field": "TR.PE", "description": "Price to Earnings (LTM diluted excl. often)", "category": "Valuation", "parameters": "SDate", "notes": "Example in RefinitivR docs: TR.PE(Sdate=0D)"},
    {"field": "TR.DividendYield", "description": "Dividend yield", "category": "Valuation", "parameters": "", "notes": ""},
]

# Columns we normalize everything to
_DD_COLS = ["field", "description", "category", "parameters", "notes", "source"]


class DataDictionary:
    """Lightweight fuzzy-searchable registry of extended LSEG data items."""

    def __init__(self, xlsx_path: str | Path | None = None, csv_path: str | Path | None = None):
        self._xlsx_path = Path(xlsx_path) if xlsx_path else None
        self._csv_path = Path(csv_path) if csv_path else None
        if self._csv_path is None:
            try:
                from lseg_mcp._paths import get_data_dictionary_path
                dd_path = get_data_dictionary_path()
                if dd_path:
                    if str(dd_path).lower().endswith((".csv", ".tsv")):
                        self._csv_path = dd_path
                    else:
                        self._xlsx_path = dd_path
            except Exception:  # pragma: no cover - defensive import/path guard
                pass
        self._df: pd.DataFrame | None = None
        self._by_category: dict[str, pd.DataFrame] = {}

    def _load(self) -> None:
        frames: list[pd.DataFrame] = []

        # 1. Built-in high-quality seed (always present)
        seed = pd.DataFrame(_BUILTIN_SEED)
        seed["source"] = "builtin"
        frames.append(seed)

        # 2. User Excel (LSEG_Mapping.xlsx sidecar sheets or dedicated dict xlsx)
        xlsx_candidates: list[Path] = []
        if self._xlsx_path and self._xlsx_path.exists():
            xlsx_candidates.append(self._xlsx_path)
        else:
            # Try to discover alongside the financials mapping
            from lseg_mcp._paths import get_mapping_xlsx
            try:
                main = get_mapping_xlsx()
                if main.exists():
                    xlsx_candidates.append(main)
            except Exception:  # pragma: no cover - defensive path discovery guard
                pass

        for xp in xlsx_candidates:
            try:
                xl = pd.ExcelFile(xp)
                for sheet in xl.sheet_names:
                    s_lower = sheet.lower().strip()
                    if any(k in s_lower for k in ("custom", "data dict", "data_dictionary", "dib", "extended", "tr fields", "fields")):
                        raw = pd.read_excel(xl, sheet_name=sheet, header=None)
                        parsed = self._parse_flat_sheet(raw)
                        if not parsed.empty:
                            parsed["source"] = f"xlsx:{sheet}"
                            frames.append(parsed)
            except Exception:  # pragma: no cover - skip unreadable workbook
                continue

        # 3. Explicit CSV/Parquet override (power users)
        if self._csv_path and self._csv_path.exists():
            try:
                csv_df = pd.read_csv(self._csv_path)
                csv_df = self._normalize_df(csv_df)
                csv_df["source"] = "csv"
                frames.append(csv_df)
            except Exception:  # pragma: no cover - skip unreadable CSV override
                pass

        # 4. Auto-load any seed/*.csv or sample files shipped in the package data dir
        #    This now also picks up real fields mined from RefinitivR source
        #    (see data/real_harvested_from_refinitivr.csv and scripts/harvest_real_fields_via_refinitivr.R)
        try:
            from lseg_mcp._paths import get_data_dir
            data_dir = get_data_dir()
            seed_globs = [
                "*fields*.csv",
                "sample*.csv",
                "*real*.csv",
                "*refinitivr*.csv",
                "*harvested*.csv",
            ]
            for glob_pat in seed_globs:
                for p in data_dir.glob(glob_pat):
                    if p.exists():
                        try:
                            s = pd.read_csv(p)
                            s = self._normalize_df(s)
                            # Preserve good source info if the CSV already provides one (e.g. live RefinitivRAPI harvest)
                            if "source" not in s.columns or (s["source"].astype(str).str.strip() == "").all():
                                s["source"] = f"seed:{p.name}"
                            # else keep the CSV's source (e.g. "RefinitivRAPI-live") and the dedup priority will favor it
                            frames.append(s)
                        except Exception:  # pragma: no cover - skip unreadable seed CSV
                            pass

            # Also scan the repo root "data/" when developing (so CSVs written by the R harvester are picked up)
            try:
                # data_dir = .../src/lseg_mcp/data
                # .parent = .../lseg_mcp
                # .parent.parent = .../src
                # .parent.parent.parent = project root
                repo_root_data = data_dir.parent.parent.parent / "data"
                if repo_root_data.exists() and repo_root_data != data_dir:
                    for glob_pat in seed_globs:
                        for p in repo_root_data.glob(glob_pat):
                            if p.exists():
                                try:
                                    s = pd.read_csv(p)
                                    s = self._normalize_df(s)
                                    if "source" not in s.columns or (s["source"].astype(str).str.strip() == "").all():
                                        s["source"] = f"seed:{p.name}"
                                    frames.append(s)
                                except Exception:  # pragma: no cover - skip unreadable seed CSV
                                    pass
            except Exception:  # pragma: no cover - repo-root scan is best-effort
                pass
        except Exception:  # pragma: no cover - data-dir scan is best-effort
            pass

        if frames:
            df = pd.concat(frames, ignore_index=True)
        else:  # pragma: no cover - builtin seed guarantees frames is non-empty
            df = pd.DataFrame(columns=_DD_COLS)

        df = self._normalize_df(df)
        # De-dupe: strongly prefer live RefinitivRAPI harvests, then other user seeds, then builtin
        def _source_priority(s):
            s = s.str.lower()
            live = s.str.contains("refinitivrapi|live").astype(int) * 3
            user_seed = (~s.str.contains("builtin")).astype(int) * 2
            return live + user_seed
        df = df.sort_values("source", key=_source_priority, ascending=False).drop_duplicates(subset=["field"], keep="first")
        self._df = df.reset_index(drop=True)

        # Index by category for fast filtering
        self._by_category = {}
        if "category" in self._df.columns:
            for cat, g in self._df.groupby(self._df["category"].fillna("Other")):
                self._by_category[str(cat)] = g

    def _parse_flat_sheet(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Heuristically parse a user DIB / Custom_Fields export sheet."""
        if raw.shape[0] < 2:
            return pd.DataFrame()
        # Try to detect header row
        header_row = 0
        for i in range(min(5, len(raw))):
            vals = [str(v).lower() for v in raw.iloc[i].tolist() if pd.notna(v)]
            if any("field" in v or "tr." in v for v in vals):
                header_row = i
                break
        data = raw.iloc[header_row + 1 :].copy()
        data.columns = [str(c).strip().lower() if pd.notna(c) else f"col_{j}" for j, c in enumerate(raw.iloc[header_row])]
        # Map common column name variants
        col_map = {
            "field": "field",
            "tr field": "field",
            "data item": "field",
            "formula": "field",
            "description": "description",
            "desc": "description",
            "name": "description",
            "category": "category",
            "type": "category",
            "group": "category",
            "parameters": "parameters",
            "params": "parameters",
            "notes": "notes",
            "note": "notes",
            "comment": "notes",
        }
        rename = {}
        for c in data.columns:
            for k, target in col_map.items():
                if k in c:
                    rename[c] = target
                    break
        data = data.rename(columns=rename)
        # Ensure we have at least a 'field' column
        if "field" not in data.columns:
            # fallback: first column that looks like it contains TR.
            for c in data.columns:
                if data[c].astype(str).str.contains("TR\\.", case=False, na=False).any():
                    data = data.rename(columns={c: "field"})
                    break
        return self._normalize_df(data)

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        # Case-insensitive column matching: a user CSV / DIB export may use
        # "Field", "Description", etc. (the README promises case-insensitive
        # columns). Lower-case incoming column names before mapping to _DD_COLS.
        df = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
        out = pd.DataFrame()
        for col in _DD_COLS:
            if col in df.columns:
                out[col] = df[col].astype(str).replace({"nan": "", "None": ""}).fillna("")
            else:
                out[col] = ""
        # Ensure field is present and upper-cased for matching
        out["field"] = out["field"].astype(str).str.strip()
        # Drop rows without a plausible field
        out = out[out["field"].str.len() > 2].copy()
        # Clean category
        out["category"] = out["category"].replace("", "General").fillna("General")
        return out[_DD_COLS]

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self._load()
        return self._df  # type: ignore[return-value]

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy search the extended dictionary.

        Matches against field name and description. Category filter is prefix/contains.
        """
        df = self.df
        if df.empty:
            return []

        q = query.lower().strip()
        tokens = [t for t in q.split() if t]
        if not tokens:
            tokens = [q]
        def _has_all(s: pd.Series) -> pd.Series:
            m = pd.Series(True, index=s.index)
            for t in tokens:
                m &= s.str.lower().str.contains(t, regex=False, na=False)
            return m
        mask = (
            _has_all(df["field"])
            | _has_all(df["description"])
            | _has_all(df["notes"])
        )

        result = df[mask].copy()

        if category:
            cat_lower = category.lower()
            result = result[
                result["category"].str.lower().str.contains(cat_lower, regex=False, na=False)
            ]

        records = []
        for _, row in result.iterrows():
            rec = {k: ("" if pd.isna(v) else str(v)) for k, v in row.items()}
            rec["_match_score"] = self._score(rec, q)
            records.append(rec)
        # Sort by score desc then field, THEN truncate — applying the limit
        # before sorting would return arbitrary dataframe-order rows and drop
        # the best matches (e.g. an exact field hit) when limit is small.
        records.sort(key=lambda r: (-r.get("_match_score", 0), r.get("field", "")))
        records = records[:limit]
        for r in records:
            r.pop("_match_score", None)
        return records

    def _score(self, rec: dict[str, Any], q: str) -> int:
        s = 0
        f = rec.get("field", "").lower()
        d = rec.get("description", "").lower()
        if q == f:
            s += 100
        if f.startswith(q):
            s += 50
        if q in f:
            s += 30
        if q in d:
            s += 10
        # Prefer core categories
        if rec.get("category") in ("Pricing", "Estimates", "ESG", "Reference"):
            s += 5
        return s

    def list_categories(self) -> list[str]:
        df = self.df
        cats = sorted(df["category"].dropna().unique().tolist())
        return cats

    def get_field(self, field: str) -> dict[str, Any] | None:
        df = self.df
        hit = df[df["field"].str.lower() == field.lower().strip()]
        if hit.empty:
            return None
        row = hit.iloc[0]
        return {k: ("" if pd.isna(v) else str(v)) for k, v in row.items()}

    def suggest_specialized(self, category: str | None = None, fields: list[str] | None = None) -> dict[str, Any]:
        """
        Given a category or list of fields, suggest whether to use a specialized
        RefinitivR function (rd_GetEstimates, rd_GetESG, etc.) instead of plain rd_GetData.
        """
        suggestions: dict[str, Any] = {"recommended_function": "rd_GetData / ld.get_data", "reason": ""}
        cats = set()
        if category:
            cats.add(category.lower())
        if fields:
            for f in fields:
                hit = self.get_field(f)
                if hit:
                    cats.add(hit.get("category", "").lower())

        if any(c in cats for c in ("estimates", "estimate")):
            suggestions = {
                "recommended_function": "rd_GetEstimates (R) or estimates content layer (Python)",
                "reason": "Full consensus history, actuals, recommendations, and package tiers (basic/standard/professional) are best served by the dedicated Estimates views.",
                "example_views": ["view-summary/annual", "view-actuals/annual", "view-summary/recommendations"],
            }
        elif any(c in cats for c in ("esg", "esg ")):
            suggestions = {
                "recommended_function": "rd_GetESG (R) or esg content layer (Python)",
                "reason": "Pillar scores, measures, and controversies require the dedicated ESG views (scores-full, measures-full, etc.).",
                "example_views": ["scores-full", "measures-standard", "basic"],
            }
        elif "pricing" in cats or "market" in cats:
            suggestions["recommended_function"] = "rd_GetData + rd_GetHistory (for series) or streaming"
            suggestions["reason"] = "Pricing snapshots via get_data; full history via GetHistory/HistoricalPricing."
        return suggestions
