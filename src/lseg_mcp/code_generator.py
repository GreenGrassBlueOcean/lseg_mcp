"""
Code Generator for LSEG data retrieval pipelines.

Merges mapping rules and AST-verified function signatures to produce
syntactically correct boilerplate code in Python (lseg-data) or R (RefinitivR).
"""

from __future__ import annotations

import json
from typing import Any


def _format_python_call(
    tickers: list[str],
    fields: list[str],
    mapping_notes: list[dict[str, Any]],
    signature: dict[str, Any] | None,
) -> str:
    """Generate a Python lseg-data boilerplate."""
    lines: list[str] = []
    lines.append("import lseg.data as ld")
    lines.append("")
    lines.append("# Open a session (requires LSEG Workspace running)")
    lines.append("ld.open_session()")
    lines.append("")

    # Add notes as comments
    for note in mapping_notes:
        for n in note.get("_notes", []):
            lines.append(f"# NOTE: {n}")
    if mapping_notes:
        lines.append("")

    # Check for additive formulas that need post-processing
    additive_fields: list[dict[str, Any]] = []
    simple_fields: list[str] = []

    for note in mapping_notes:
        if note.get("_additive"):
            additive_fields.append(note)
        else:
            val = note.get("office_field")
            if not val or str(val) == "nan":
                val = note.get("_target_fcc")
                if val and str(val).strip() and "no fcc" not in str(val).lower():
                    if not str(val).startswith("TR."):
                        val = f"TR.F.{val}"
            
            if val and str(val).strip() and "no fcc" not in str(val).lower():
                simple_fields.append(str(val))

    if not simple_fields and not additive_fields:
        simple_fields = fields  # pragma: no cover

    ticker_str = str(tickers)

    lines.append(f"# Fetch data for {tickers}")
    if simple_fields:
        lines.append(f"df = ld.get_data(")
        lines.append(f"    universe={ticker_str},")
        lines.append(f"    fields={simple_fields},")
        lines.append(f")")
    else:
        lines.append("import pandas as pd")
        lines.append(f"df = pd.DataFrame(index={ticker_str})")
    lines.append("")

    # Handle additive formulas
    for af in additive_fields:
        formula = af["_additive"]
        components = [
            c.strip() if c.strip().startswith("TR.") else f"TR.F.{c.strip()}"
            for c in formula.split("+")
        ]
        col_name = af.get("coa_description", formula).replace(" ", "_")
        lines.append(f"# Additive formula for {af.get('coa_description', formula)}: {formula}")
        lines.append(f"df_components = ld.get_data(")
        lines.append(f"    universe={ticker_str},")
        lines.append(f"    fields={components},")
        lines.append(f")")
        lines.append(f"df['{col_name}'] = df_components[{components}].sum(axis=1, min_count=1)")
        lines.append("")

    lines.append("print(df)")
    lines.append("")
    lines.append("ld.close_session()")

    return "\n".join(lines)


def _format_r_call(
    tickers: list[str],
    fields: list[str],
    mapping_notes: list[dict[str, Any]],
    signature: dict[str, Any] | None,
) -> str:
    """Generate an R RefinitivR boilerplate."""
    lines: list[str] = []
    lines.append("library(Refinitiv)")
    lines.append("")

    # Add notes as comments
    for note in mapping_notes:
        for n in note.get("_notes", []):
            lines.append(f"# NOTE: {n}")
    if mapping_notes:
        lines.append("")

    # Determine the correct function signature
    func_name = "rd_GetData"
    if signature:
        func_name = signature.get("name", "rd_GetData")
        lines.append(f"# Function signature from local index: {signature.get('args', [])}")
        lines.append("")

    # Build field list
    simple_fields: list[str] = []
    additive_fields: list[dict[str, Any]] = []

    for note in mapping_notes:
        if note.get("_additive"):
            additive_fields.append(note)
        else:
            val = note.get("office_field")
            if not val or str(val) == "nan":
                val = note.get("_target_fcc")
                if val and str(val).strip() and "no fcc" not in str(val).lower():
                    if not str(val).startswith("TR."):
                        val = f"TR.F.{val}"
            
            if val and str(val).strip() and "no fcc" not in str(val).lower():
                simple_fields.append(str(val))

    if not simple_fields and not additive_fields:
        simple_fields = fields  # pragma: no cover

    ticker_r = ", ".join(json.dumps(t) for t in tickers)
    fields_r = ", ".join(json.dumps(f) for f in simple_fields)

    # Extract correct parameter names from signature
    arg_rics = "rics"
    arg_fields = "fields"
    if signature:
        for a in signature.get("args", []):
            if isinstance(a, str):
                arg_name = a.split("=")[0].strip()
                if arg_name == "Eikonformulas":
                    arg_fields = "Eikonformulas"
                elif arg_name == "instruments":
                    arg_rics = "instruments"  # pragma: no cover

    lines.append(f"rics  <- c({ticker_r})")
    lines.append(f"fields <- c({fields_r})")
    lines.append("")
    if simple_fields:
        lines.append(f"result <- {func_name}(")
        lines.append(f"  {arg_rics} = rics,")
        lines.append(f"  {arg_fields} = fields")
        lines.append(f")")
    else:
        lines.append("result <- data.frame(Instrument = rics)")
    lines.append("")

    # Handle additive formulas
    for af in additive_fields:
        formula = af["_additive"]
        components = [
            c.strip() if c.strip().startswith("TR.") else f"TR.F.{c.strip()}"
            for c in formula.split("+")
        ]
        col_name = af.get("coa_description", formula).replace(" ", "_")
        comp_r = ", ".join(json.dumps(c) for c in components)
        lines.append(f"# Additive formula for {af.get('coa_description', formula)}: {formula}")
        lines.append(f"components <- {func_name}(")
        lines.append(f"  {arg_rics} = rics,")
        lines.append(f"  {arg_fields} = c({comp_r})")
        lines.append(f")")
        lines.append(f"result[['{col_name}']] <- rowSums(components[, c({comp_r}), drop=FALSE], na.rm = FALSE)")
        lines.append("")

    lines.append("print(result)")

    return "\n".join(lines)


def draft_api_call(
    language: str,
    tickers: list[str],
    fields: list[str],
    mapping_notes: list[dict[str, Any]] | None = None,
    signature: dict[str, Any] | None = None,
) -> str:
    """
    Generate a syntactically correct API call boilerplate.

    Parameters
    ----------
    language
        ``"python"`` or ``"r"``.
    tickers
        List of RIC codes (e.g. ``["AAPL.O", "JPM"]``).
    fields
        List of FCC or COA field codes.
    mapping_notes
        Enriched mapping records from the MappingEngine.
    signature
        Live function signature from the PackageIndexer.

    Returns
    -------
    str
        Ready-to-use code string.
    """
    if mapping_notes is None:
        mapping_notes = []

    if language.lower() in ("python", "py"):
        return _format_python_call(tickers, fields, mapping_notes, signature)
    elif language.lower() in ("r",):
        return _format_r_call(tickers, fields, mapping_notes, signature)
    else:
        return f"# Unsupported language: {language}. Use 'python' or 'r'."
