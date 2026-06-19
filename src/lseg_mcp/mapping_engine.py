"""
Semantic Mapping Engine for LSEG Financials → LSEG Company Fundamentals.

Ingests the official LSEG mapping Excel workbook and provides:
 - Fuzzy search across COA codes, descriptions, and labels
 - Industry-specific FCC routing (Industrial, Bank, Insurance, etc.)
 - Additive formula detection (e.g. SOLL+SLAP+SCAL+SDIL+SRLN)
 - Bracket/ASR layer flagging (e.g. [AFUL] → As Reported layer)
 - "No FCC Match" interception with non-operating fallback guidance
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import pandas as pd

# ── Column names we assign after parsing the multi-header Excel rows ─────────
_FINANCIALS_COLS = [
    "statement",
    "line_id",
    "coa",
    "coa_description",
    "office_field",
    "label",
    "polarity",
    "display",
    "bank_applicable",
    "industry_applicable",
    "insurance_applicable",
    "utility_applicable",
]

_SEPARATOR = "_sep"

_FUNDAMENTALS_COLS = [
    "fcc_industrial",
    "fcc_inv_trust",
    "fcc_financial",
    "fcc_property",
    "fcc_bank",
    "fcc_insurance",
    "overall_match",
]

COLUMN_NAMES = _FINANCIALS_COLS + [_SEPARATOR] + _FUNDAMENTALS_COLS

# All industry-specific FCC columns for easy iteration
FCC_INDUSTRY_COLS = [
    "fcc_industrial",
    "fcc_inv_trust",
    "fcc_financial",
    "fcc_property",
    "fcc_bank",
    "fcc_insurance",
]

INDUSTRY_DISPLAY_NAMES = {
    "fcc_industrial": "Industrial",
    "fcc_inv_trust": "Investment Trust",
    "fcc_financial": "Financial",
    "fcc_property": "Property",
    "fcc_bank": "Bank",
    "fcc_insurance": "Insurance",
}


class MappingEngine:
    """In-memory engine for querying the LSEG mapping matrix."""

    def __init__(self, xlsx_path: str | Path | None = None):
        if xlsx_path is None:
            from lseg_mcp._paths import get_mapping_xlsx
            xlsx_path = get_mapping_xlsx()
        self._xlsx_path = Path(xlsx_path)
        self._df: pd.DataFrame | None = None
        self._explanations: str | None = None
        self._segments_df: pd.DataFrame | None = None
        self._aggregates_df: pd.DataFrame | None = None

    # ── Data Loading ─────────────────────────────────────────────────────

    def _load(self) -> None:
        """Parse the multi-header Excel workbook into clean DataFrames."""
        xl = pd.ExcelFile(self._xlsx_path)

        # ── Explanations (rules text) ────────────────────────────────────
        expl_df = pd.read_excel(xl, sheet_name="Explanations", header=None)
        lines: list[str] = []
        for _, row in expl_df.iterrows():
            for val in row:
                if pd.notna(val) and str(val).strip():
                    lines.append(str(val).strip())
        self._explanations = "\n".join(lines)

        # ── Standardized Financials (main mapping matrix) ────────────────
        std_sheet = next((s for s in xl.sheet_names if "Standardized Financials" in s), xl.sheet_names[0])
        raw = pd.read_excel(
            xl, sheet_name=std_sheet, header=None
        )
        # Row 2 (0-indexed) contains the actual column headers.
        # Data starts from row 3 onward.  Drop the first 3 header rows.
        data = raw.iloc[3:].reset_index(drop=True)
        data.columns = COLUMN_NAMES[: data.shape[1]]

        # Drop the separator column
        if _SEPARATOR in data.columns:
            data = data.drop(columns=[_SEPARATOR])

        # Forward-fill the statement column (section headers span rows)
        data["statement"] = data["statement"].ffill()

        # Drop pure section-header rows (where COA is NaN)
        data = data.dropna(subset=["coa"]).reset_index(drop=True)

        # Normalise applicability columns to boolean
        for col in ["bank_applicable", "industry_applicable",
                     "insurance_applicable", "utility_applicable"]:
            if col in data.columns:
                data[col] = data[col].notna() & (data[col] != "")

        self._df = data

        # ── Segments ─────────────────────────────────────────────────────
        try:
            self._segments_df = pd.read_excel(xl, sheet_name="Segments ")
        except Exception:
            self._segments_df = pd.DataFrame()

        # ── Aggregates ───────────────────────────────────────────────────
        try:
            self._aggregates_df = pd.read_excel(xl, sheet_name="Aggregates")
        except Exception:
            self._aggregates_df = pd.DataFrame()

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self._load()
        return self._df  # type: ignore[return-value]

    @property
    def explanations(self) -> str:
        if self._explanations is None:
            self._load()
        return self._explanations  # type: ignore[return-value]

    # ── Public API ───────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        industry: str | None = None,
        statement: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy-search the mapping matrix.

        Parameters
        ----------
        query
            Free-text search term matched against COA, COA Description,
            Label, Office Field, and all FCC columns.
        industry
            Optional industry filter: ``"industrial"``, ``"bank"``,
            ``"insurance"``, ``"property"``, ``"financial"``,
            ``"inv_trust"``, or ``"utility"``.
        statement
            Optional statement filter: ``"Income Statement"``,
            ``"Balance Sheet"``, ``"Cash Flow"``.
        limit
            Maximum rows to return.

        Returns
        -------
        list[dict]
            Each dict contains all mapping fields plus enrichment
            metadata (``_notes``, ``_asr_flagged``, ``_additive``).
        """
        df = self.df
        q = query.lower()

        # Search across text columns
        text_cols = ["coa", "coa_description", "label", "office_field"] + FCC_INDUSTRY_COLS
        mask = pd.Series(False, index=df.index)
        for col in text_cols:
            if col in df.columns:
                mask |= df[col].fillna("").astype(str).str.contains(query, case=False, regex=False, na=False)

        result = df[mask].copy()

        # ── Fuzzy fallback when exact/substring matching returns nothing ──
        if result.empty:
            result = self._fuzzy_fallback(query, limit=limit)

        # Optional filters
        if statement:
            result = result[
                result["statement"].str.contains(statement, case=False, regex=False, na=False)
            ]
        if industry:
            ind_lower = industry.lower().replace(" ", "_")
            # Map industry to its boolean applicability column
            app_col_map = {
                "industrial": "industry_applicable",
                "bank": "bank_applicable",
                "insurance": "insurance_applicable",
                "utility": "utility_applicable",
            }
            # Fallback to industry_applicable if specific sector lacks a boolean column
            applicability_col = app_col_map.get(ind_lower, "industry_applicable")
            if applicability_col in result.columns:
                result = result[result[applicability_col]]

        result = result.head(limit)

        # Enrich each row with notes
        records: list[dict[str, Any]] = []
        for _, row in result.iterrows():
            rec = row.dropna().to_dict()
            rec = self._enrich(rec, industry)
            records.append(rec)

        return records

    def get_rules(self) -> dict[str, Any]:
        """Return the global mapping rules and definitions."""
        return {
            "explanations": self.explanations,
            "categories": {
                "1_identical": "Standardization methodologies are the same; COA and FCC values are identical.",
                "2_comparable": "Values may not be identical, but considered a 1:1 relationship.",
                "3_not_comparable": "No reliable mapping exists (NC).",
            },
            "special_cases": {
                "no_fcc_match": "No single FCC or combination of FCCs generates a matching value.",
                "no_fcc_match_operating": "Operating vs non-operating does not exist in LSEG Company Fundamentals; items are all non-operating.",
                "asr_bracket_notation": "FCC codes in brackets like [ABCD] are from the As Reported (ASR) layer, also available in STD layer.",
                "primary_instrument": "COA+Primary Instrument needed for share/dividend data items.",
                "instrument_id": "COA+Instrument ID needed for per-instrument data items.",
                "additive_formulas": "Some FCCs are additive combinations (e.g. SOLL+SLAP+SCAL+SDIL+SRLN) that must be fetched separately and summed.",
            },
            "cash_flow_notes": (
                "LSEG Company Fundamentals supports both indirect and direct cash flow "
                "formats with reconciliation.  LSEG Financials supports only the format "
                "reported on the face of the cash flow."
            ),
            "balance_sheet_notes": (
                "LSEG Company Fundamentals supports differentiated (current/non-current) "
                "and non-differentiated (total) balance sheet formats."
            ),
        }

    def validate_formula(
        self,
        fields: list[str],
        industry: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Cross-reference submitted FCC/COA fields against the matrix.

        Returns a list of validation results per field with warnings
        for Not Comparable, missing Primary Instrument, etc.

        When an *industry* filter is active and a field exists in the
        matrix but is not applicable for that industry, the result is
        ``INDUSTRY_MISMATCH`` (not ``NOT_FOUND``), with a helpful message
        listing the industries where the field *is* available.
        """
        results = []
        for field in fields:
            field_upper = field.upper().strip()
            matches = self.search(field_upper, industry=industry, limit=5)

            # ── Industry-scoped miss detection ───────────────────────
            if not matches and industry:
                # Retry without industry filter to distinguish
                # "wrong industry" from "genuinely unknown field"
                unscoped = self.search(field_upper, industry=None, limit=1)
                if unscoped:
                    best = unscoped[0]
                    applicable = []
                    for col, label in [
                        ("bank_applicable", "Bank"),
                        ("industry_applicable", "Industrial"),
                        ("insurance_applicable", "Insurance"),
                        ("utility_applicable", "Utility"),
                    ]:
                        if best.get(col) is True:
                            applicable.append(label)
                    coa = best.get("coa", field)
                    desc = best.get("coa_description", "")
                    avail = ", ".join(applicable) if applicable else "none"
                    results.append({
                        "field": field,
                        "status": "INDUSTRY_MISMATCH",
                        "message": (
                            f"'{coa}' ({desc}) exists in the mapping matrix but "
                            f"is not applicable for industry '{industry}'. "
                            f"Available for: {avail}."
                        ),
                        "warnings": [],
                        "mapping": best,
                    })
                    continue

            if not matches:
                results.append({
                    "field": field,
                    "status": "NOT_FOUND",
                    "message": f"'{field}' not found in the mapping matrix.",
                })
                continue

            best = matches[0]
            status = "OK"
            warnings: list[str] = []

            # Check for Not Comparable
            overall = str(best.get("overall_match", "")).lower()
            if "nc" in overall or "not comparable" in overall:
                status = "NOT_COMPARABLE"
                warnings.append("This field is marked as Not Comparable (NC).")

            # Check for No FCC Match
            for col in FCC_INDUSTRY_COLS:
                val = str(best.get(col, ""))
                if "no fcc match" in val.lower():
                    warnings.append(
                        f"{INDUSTRY_DISPLAY_NAMES.get(col, col)}: No FCC Match. "
                        "Operating concept does not exist in LSEG Company Fundamentals; "
                        "use the non-operating equivalent."
                    )

            # Check for ASR bracket
            if best.get("_asr_flagged"):
                warnings.append("This FCC uses the As Reported (ASR) layer. Adjust API payload to request ASR.")

            # Check for additive formula
            if best.get("_additive"):
                warnings.append(
                    f"Additive formula detected: {best['_additive']}. "
                    "Fetch constituent parts separately and sum locally."
                )

            results.append({
                "field": field,
                "status": status,
                "warnings": warnings,
                "mapping": best,
            })

        return results

    # ── Internal: Fuzzy fallback ──────────────────────────────────────────

    def _fuzzy_fallback(
        self, query: str, limit: int = 25, cutoff: float = 0.45,
    ) -> pd.DataFrame:
        """Return rows whose description/label fuzzy-matches *query*.

        Uses :func:`difflib.get_close_matches` against all unique
        descriptions and labels.  Returns an empty DataFrame when
        nothing is close enough.
        """
        df = self.df
        # Build a lookup from lowercase candidate → original values
        candidates: dict[str, str] = {}
        for col in ("coa_description", "label"):
            if col not in df.columns:
                continue
            for val in df[col].dropna().unique():
                s = str(val).strip()
                if s:
                    candidates[s.lower()] = s

        close = difflib.get_close_matches(
            query.lower(), list(candidates.keys()), n=limit, cutoff=cutoff,
        )
        if not close:
            return pd.DataFrame(columns=df.columns)

        matched_originals = {candidates[c] for c in close}
        mask = pd.Series(False, index=df.index)
        for col in ("coa_description", "label"):
            if col in df.columns:
                mask |= df[col].isin(matched_originals)
        return df[mask].copy()

    # ── Internal Enrichment ──────────────────────────────────────────────

    def _enrich(self, rec: dict[str, Any], industry: str | None = None) -> dict[str, Any]:
        """Add computed notes to a record."""
        notes: list[str] = []

        # Determine the target FCC column based on industry
        target_fcc_col = None
        if industry:
            ind_lower = industry.lower().replace(" ", "_")
            candidate = f"fcc_{ind_lower}"
            if candidate in FCC_INDUSTRY_COLS:
                target_fcc_col = candidate

        # Pick the best FCC value
        fcc_val = ""
        if target_fcc_col and target_fcc_col in rec:
            fcc_val = str(rec[target_fcc_col])
            rec["_target_fcc"] = fcc_val
        else:
            # Fall back to first non-empty FCC
            for col in FCC_INDUSTRY_COLS:
                if col in rec and pd.notna(rec[col]) and str(rec[col]).strip():
                    fcc_val = str(rec[col])
                    rec["_target_fcc"] = fcc_val
                    break

        fcc_lower = fcc_val.lower()

        # ── Detect additive formulas (e.g. SOLL+SLAP+SCAL) ──────────
        if "+" in fcc_val and "no fcc" not in fcc_lower and "instrument" not in fcc_lower:
            rec["_additive"] = fcc_val
            components = [c.strip() for c in fcc_val.split("+")]
            notes.append(f"Additive formula: fetch {components} separately and sum.")

        # ── Detect ASR bracket notation (e.g. [AFUL]) ───────────────
        bracket_match = re.search(r"\[([A-Z]{4,})\]", fcc_val)
        if bracket_match:
            rec["_asr_flagged"] = True
            rec["_asr_code"] = bracket_match.group(1)
            rec["_target_fcc"] = bracket_match.group(1)  # Strip brackets from target
            notes.append(f"As-Reported layer: use ASR layer for {bracket_match.group(1)}.")

        # ── Detect Multiple-to-one mappings (e.g. SNTU/SHRV/SNTS) ───
        if "/" in fcc_val and "no fcc" not in fcc_lower:
            alternatives = [a.strip() for a in fcc_val.split("/")]
            notes.append(f"Multiple-to-one mapping: value matches any of {alternatives}. Defaulting to {alternatives[0]}.")
            if not rec.get("_asr_flagged"):  # Prevent overwriting the ASR fix above
                rec["_target_fcc"] = alternatives[0]

        # ── Detect "No FCC Match" ────────────────────────────────────
        if "no fcc match" in fcc_lower:
            notes.append(
                "No FCC Match: operating concept does not exist in LSEG Company "
                "Fundamentals. Use the non-operating equivalent instead."
            )

        # ── Primary Instrument detection ─────────────────────────────
        if "primary instrument" in fcc_lower:
            notes.append("Requires Primary Instrument ID to be appended for share/dividend items.")

        # ── Instrument ID detection ──────────────────────────────────
        if "instrument id" in fcc_lower:
            notes.append("Requires specific Instrument ID for per-instrument matching.")

        # ── Industry applicability flags ─────────────────────────────
        applicable_industries = []
        for col, label in [
            ("bank_applicable", "Bank"),
            ("industry_applicable", "Industrial"),
            ("insurance_applicable", "Insurance"),
            ("utility_applicable", "Utility"),
        ]:
            if rec.get(col) is True:
                applicable_industries.append(label)
        not_applicable = []
        for col, label in [
            ("bank_applicable", "Bank"),
            ("industry_applicable", "Industrial"),
            ("insurance_applicable", "Insurance"),
            ("utility_applicable", "Utility"),
        ]:
            if rec.get(col) is False:
                not_applicable.append(label)
        if not_applicable and applicable_industries:
            notes.append(f"Industry scope: available for {', '.join(applicable_industries)}. NOT available for {', '.join(not_applicable)}.")

        rec["_notes"] = notes
        return rec
