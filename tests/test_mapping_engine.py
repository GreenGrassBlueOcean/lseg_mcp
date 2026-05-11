import pytest
import pandas as pd
from lseg_mcp.mapping_engine import MappingEngine, COLUMN_NAMES

def test_load_and_parse(mock_pandas_read_excel):
    engine = MappingEngine(xlsx_path="dummy.xlsx")
    df = engine.df
    assert len(df) == 6
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
    res = engine.search("RDEBT")
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
