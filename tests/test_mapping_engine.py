import pytest
import pandas as pd
from lseg_mcp.mapping_engine import MappingEngine, COLUMN_NAMES

def test_load_and_parse(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    df = engine.df
    assert len(df) == 7
    assert engine.explanations == "Line 1\nLine 2"

def test_search_fuzzy_matching(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    
    # Search by COA
    res = engine.search("RREV")
    assert len(res) == 1
    assert res[0]["coa"] == "RREV"

    # Search by Label
    res = engine.search("Gross Revenue")
    assert len(res) == 1
    assert res[0]["fcc_industrial"] == "SREV"

def test_industry_routing(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    
    # RDIV is applicable to bank and industrial.
    # But for bank it uses SOLL+SLAP from fcc_bank
    res = engine.search("RDIV", industry="bank")
    assert len(res) == 1
    assert res[0]["fcc_bank"] == "SOLL+SLAP"
    
    # RREV is not applicable to bank
    res2 = engine.search("RREV", industry="bank")
    assert len(res2) == 0

def test_statement_filtering(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("OpEx", statement="Cash Flow")
    assert len(res) == 1
    assert res[0]["coa"] == "ROPE"

def test_enrichment_additive(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("RDIV")
    assert len(res) == 1
    assert res[0].get("_additive") == "SOLL+SLAP"
    assert any("Additive formula" in n for n in res[0]["_notes"])

def test_enrichment_asr_bracket(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = [r for r in engine.search("RDEBT") if r["coa"] == "RDEBT"]
    assert len(res) == 1
    assert res[0].get("_asr_flagged") is True
    assert res[0].get("_asr_code") == "AFUL"
    assert any("As-Reported layer" in n for n in res[0]["_notes"])

def test_enrichment_no_fcc(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("ROPE")
    assert len(res) == 1
    assert any("No FCC Match" in n for n in res[0]["_notes"])

def test_enrichment_primary_instrument_and_multi(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("RNTS")
    assert len(res) == 1
    notes = " ".join(res[0]["_notes"])
    assert "Multiple-to-one mapping" in notes
    assert "Primary Instrument ID" in notes

def test_enrichment_instrument_id(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("RINST")
    assert len(res) == 1
    notes = " ".join(res[0]["_notes"])
    assert "Instrument ID" in notes

def test_get_rules(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    rules = engine.get_rules()
    assert "1_identical" in rules["categories"]
    assert rules["explanations"] == "Line 1\nLine 2"

def test_validate_formula_ok(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RREV", "RINST"])
    assert len(results) == 2
    assert results[0]["status"] == "OK"
    assert results[1]["status"] == "OK"
    assert len(results[0]["warnings"]) == 0
    assert len(results[1]["warnings"]) == 0

def test_validate_formula_not_found(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["NONEXISTENT"])
    assert len(results) == 1
    assert results[0]["status"] == "NOT_FOUND"

def test_validate_formula_not_comparable_and_no_fcc(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["ROPE"])
    assert len(results) == 1
    assert results[0]["status"] == "NOT_COMPARABLE"
    assert any("Not Comparable (NC)" in w for w in results[0]["warnings"])
    assert any("No FCC Match" in w for w in results[0]["warnings"])

def test_validate_formula_additive_and_asr(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RDIV", "RDEBT"])
    assert len(results) == 2
    # RDIV is additive
    assert any("Additive formula detected: SOLL+SLAP" in w for w in results[0]["warnings"])
    # RDEBT is ASR
    assert any("As Reported (ASR) layer" in w for w in results[1]["warnings"])

def test_mapping_engine_default_path_and_missing_sheets(mocker, mock_mapping_data):
    # This hits line 75 (default path) and lines 127-128, 133-134 (missing sheets)
    def fake_read_excel_error(xl, sheet_name=None, header=None, **kwargs):
        if sheet_name in ("Segments ", "Aggregates"):
            raise Exception("No sheet")
        # Reuse logic for Standardized Financials
        if sheet_name == "Explanations":
            return pd.DataFrame([["Line 1"]])
        dummy = pd.DataFrame(columns=COLUMN_NAMES)
        dummy.loc[0] = [None] * len(COLUMN_NAMES)
        dummy.loc[1] = [None] * len(COLUMN_NAMES)
        dummy.loc[2] = [None] * len(COLUMN_NAMES)
        return dummy

    mocker.patch("pandas.read_excel", side_effect=fake_read_excel_error)
    mock_xl = mocker.MagicMock()
    mock_xl.sheet_names = ["Explanations", "Standardized Financials "]
    mocker.patch("pandas.ExcelFile", return_value=mock_xl)
    engine = MappingEngine() # No path given
    df = engine.df
    assert len(df) == 0
    assert engine._segments_df.empty
    assert engine._aggregates_df.empty

def test_enrichment_industry_scope_notes(mock_pandas_read_excel):
    """Verify industry applicability flags are surfaced in _notes."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    # RREV: bank=False, industrial=True, insurance=False, utility=False
    res = engine.search("RREV")
    assert len(res) == 1
    notes = " ".join(res[0]["_notes"])
    assert "NOT available for" in notes
    assert "Bank" in notes
    assert "Industrial" in notes  # should be in the available list

def test_enrichment_all_applicable_no_scope_note(mock_pandas_read_excel):
    """When all industries are applicable, no scope note should be emitted."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    # RINST: all False — no scope note either (no applicable ones either -> edge)
    res = engine.search("RINST")
    assert len(res) == 1
    scope_notes = [n for n in res[0]["_notes"] if "Industry scope" in n]
    # All False means not_applicable has items but applicable_industries is empty
    # So the condition `if not_applicable and applicable_industries` is False -> no note
    assert len(scope_notes) == 0

def test_enrichment_bank_only_scope_note(mock_pandas_read_excel):
    """Verify industry applicability flags are surfaced in _notes for bank-only field."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("RDEBT_BANK")
    assert len(res) == 1
    notes = " ".join(res[0]["_notes"])
    assert "available for Bank" in notes
    assert "NOT available for Industrial, Insurance, Utility" in notes


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Bug #1 — Fuzzy fallback for typos
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_fuzzy_fallback_typo_gross_revenue(mock_pandas_read_excel):
    """Misspelling 'Groos Reveneu' should fuzzy-match to 'Gross Revenue'."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("Groos Reveneu")
    assert len(res) >= 1
    assert res[0]["coa"] == "RREV"


def test_fuzzy_fallback_typo_total_dbt(mock_pandas_read_excel):
    """Misspelling 'Totl Debt' should fuzzy-match to 'Total Debt'."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("Totl Debt")
    assert len(res) >= 1
    assert res[0]["coa"] == "RDEBT"


def test_fuzzy_fallback_no_match(mock_pandas_read_excel):
    """Completely unrelated query should still return empty."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("xyzzy_gibberish_12345")
    assert len(res) == 0


def test_fuzzy_fallback_returns_dataframe(mock_pandas_read_excel):
    """Direct call to _fuzzy_fallback returns a DataFrame."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    df = engine._fuzzy_fallback("Groos Reveneu")
    assert not df.empty
    assert "RREV" in df["coa"].values


def test_fuzzy_fallback_empty_columns_on_no_match(mock_pandas_read_excel):
    """_fuzzy_fallback returns empty DF with correct columns when nothing matches."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    df = engine._fuzzy_fallback("xyzzy_gibberish_12345")
    assert df.empty
    # Columns should still match the main df
    assert list(df.columns) == list(engine.df.columns)


def test_fuzzy_exact_match_takes_priority(mock_pandas_read_excel):
    """An exact substring match must NOT trigger fuzzy fallback."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    # "Gross Revenue" is an exact match — must return deterministically
    res = engine.search("Gross Revenue")
    assert len(res) == 1
    assert res[0]["coa"] == "RREV"


def test_fuzzy_fallback_single_char_typo(mock_pandas_read_excel):
    """A single-character typo should still fuzzy-match."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("Gross Revenve")  # 'v' instead of 'u'
    assert len(res) >= 1
    assert res[0]["coa"] == "RREV"


def test_fuzzy_fallback_matches_label_not_description(mock_pandas_read_excel):
    """Fuzzy matching should also work against 'label' column."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    # 'Dividnds' is a typo for label 'Dividends'
    res = engine.search("Dividnds")
    assert len(res) >= 1
    assert res[0]["coa"] == "RDIV"


def test_fuzzy_fallback_case_insensitive(mock_pandas_read_excel):
    """Fuzzy match is case-insensitive."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("GROOS REVENEU")
    assert len(res) >= 1
    assert res[0]["coa"] == "RREV"


def test_fuzzy_with_industry_filter_applied_after_fuzzy(mock_pandas_read_excel):
    """Fuzzy match 'Totl Debt' → 'Total Debt', then industry filter bank should still return it."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("Totl Debt", industry="bank")
    assert len(res) >= 1
    assert res[0]["coa"] == "RDEBT"


def test_fuzzy_with_industry_filter_excludes(mock_pandas_read_excel):
    """Fuzzy match 'Groos Reveneu' → 'Gross Revenue', but bank filter should exclude it."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("Groos Reveneu", industry="bank")
    assert len(res) == 0


def test_fuzzy_with_statement_filter(mock_pandas_read_excel):
    """Fuzzy match combined with statement filter."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    # Typo for 'Total Debt' which is on Balance Sheet
    res_bs = engine.search("Totl Debt", statement="Balance Sheet")
    assert len(res_bs) >= 1
    assert res_bs[0]["coa"] == "RDEBT"
    # Same typo filtered to Income Statement should return nothing
    res_is = engine.search("Totl Debt", statement="Income Statement")
    assert len(res_is) == 0


def test_fuzzy_results_are_enriched(mock_pandas_read_excel):
    """Fuzzy-matched results should still be enriched with _notes."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("Totl Debt")
    assert len(res) >= 1
    # RDEBT has ASR bracket [AFUL] so it should be enriched
    assert "_asr_flagged" in res[0]
    assert "_notes" in res[0]


def test_fuzzy_fallback_respects_limit(mock_pandas_read_excel):
    """Limit parameter should cap results even in fuzzy mode."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    res = engine.search("Debt", limit=1)
    assert len(res) <= 1


def test_fuzzy_fallback_missing_column_guard(mock_pandas_read_excel):
    """When a text column is missing from df, _fuzzy_fallback should skip it gracefully."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    # Access .df to trigger lazy _load(), then drop 'label' to exercise
    # the `if col not in df.columns: continue` guard (line 375)
    _ = engine.df
    engine._df = engine._df.drop(columns=["label"])
    df = engine._fuzzy_fallback("Groos Reveneu")
    # Should still match via coa_description
    assert not df.empty
    assert "RREV" in df["coa"].values


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Bug #2 — Industry mismatch vs NOT_FOUND
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_validate_formula_industry_mismatch(mock_pandas_read_excel):
    """RREV exists for Industrial but NOT for Bank.
    Should return INDUSTRY_MISMATCH, not NOT_FOUND."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RREV"], industry="bank")
    assert len(results) == 1
    assert results[0]["status"] == "INDUSTRY_MISMATCH"
    assert "not applicable for industry 'bank'" in results[0]["message"]
    assert "Industrial" in results[0]["message"]
    assert results[0]["mapping"]["coa"] == "RREV"


def test_validate_formula_still_not_found(mock_pandas_read_excel):
    """A genuinely unknown field should still be NOT_FOUND even with industry."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["NONEXISTENT"], industry="bank")
    assert len(results) == 1
    assert results[0]["status"] == "NOT_FOUND"


def test_validate_formula_no_industry_unchanged(mock_pandas_read_excel):
    """Without industry filter, valid field stays OK, unknown stays NOT_FOUND."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RREV", "NONEXISTENT"])
    assert results[0]["status"] == "OK"
    assert results[1]["status"] == "NOT_FOUND"


def test_validate_formula_reverse_mismatch_bank_only_for_industrial(mock_pandas_read_excel):
    """RDEBT_BANK is bank-only; validating for industrial should return INDUSTRY_MISMATCH."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RDEBT_BANK"], industry="industrial")
    assert len(results) == 1
    assert results[0]["status"] == "INDUSTRY_MISMATCH"
    assert "not applicable for industry 'industrial'" in results[0]["message"]
    assert "Bank" in results[0]["message"]


def test_validate_formula_zero_applicable_industries(mock_pandas_read_excel):
    """RINST has all applicability flags False. Validating for bank should
    show INDUSTRY_MISMATCH with 'Available for: none'."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RINST"], industry="bank")
    assert len(results) == 1
    assert results[0]["status"] == "INDUSTRY_MISMATCH"
    assert "Available for: none" in results[0]["message"]


def test_validate_formula_mixed_batch_three_statuses(mock_pandas_read_excel):
    """Mixed batch: one OK, one INDUSTRY_MISMATCH, one NOT_FOUND."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    # RDIV is applicable for both bank and industrial → OK for bank
    # RREV is industrial-only → MISMATCH for bank
    # NONEXISTENT → NOT_FOUND
    results = engine.validate_formula(["RDIV", "RREV", "NONEXISTENT"], industry="bank")
    by_field = {r["field"]: r for r in results}
    assert by_field["RDIV"]["status"] == "OK"
    assert by_field["RREV"]["status"] == "INDUSTRY_MISMATCH"
    assert by_field["NONEXISTENT"]["status"] == "NOT_FOUND"


def test_validate_formula_mismatch_preserves_mapping_metadata(mock_pandas_read_excel):
    """INDUSTRY_MISMATCH result should include full mapping record."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RREV"], industry="bank")
    mapping = results[0]["mapping"]
    assert mapping["office_field"] == "TR.GrossRevenue"
    assert mapping["coa_description"] == "Gross Revenue"
    assert "_notes" in mapping


def test_validate_formula_mismatch_has_empty_warnings(mock_pandas_read_excel):
    """INDUSTRY_MISMATCH should have an empty warnings list (the message field carries the info)."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RREV"], industry="bank")
    assert results[0]["warnings"] == []


def test_validate_formula_ok_field_same_industry(mock_pandas_read_excel):
    """A field valid for the requested industry should still return OK."""
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    results = engine.validate_formula(["RREV"], industry="industrial")
    assert results[0]["status"] == "OK"


