import pytest
from lseg_mcp.code_generator import draft_api_call

def test_draft_api_call_python_simple():
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Gross Profit"],
        mapping_notes=[{"_target_fcc": "SGRP", "coa": "SGRP", "_notes": ["A test note"]}]
    )
    assert "import lseg.data as ld" in res
    assert "ld.open_session()" in res
    assert "universe=['AAPL.O']" in res
    # FCC code without office_field should NOT appear in fields, only as a WARNING
    assert "SGRP" not in res.split("fields=")[-1].split(")")[0] if "fields=" in res else True
    assert "# ACTION REQUIRED FOR AI: 'SGRP' is a raw FCC code." in res
    assert "# NOTE: A test note" in res

def test_draft_api_call_r_simple():
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Gross Profit"],
        mapping_notes=[{"_target_fcc": "SGRP", "coa": "SGRP", "_notes": ["A test note"]}]
    )
    assert "library(Refinitiv)" in res
    assert 'rics  <- c("AAPL.O")' in res
    # FCC code without office_field should trigger WARNING, not appear in fields
    assert "# ACTION REQUIRED FOR AI: 'SGRP' is a raw FCC code." in res
    assert "rd_GetData(" in res  # Fallback to user-provided fields
    assert "# NOTE: A test note" in res

def test_draft_api_call_additive_python():
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Dividends"],
        mapping_notes=[{"_additive": "SOLL+SLAP", "coa": "RDIV", "coa_description": "RDIV"}]
    )
    assert "fields=['SOLL', 'SLAP']" in res
    assert "# ACTION REQUIRED FOR AI: Components ['SOLL', 'SLAP'] are raw FCC codes." in res
    assert "df['RDIV'] = df_components[['SOLL', 'SLAP']].sum(axis=1, min_count=1)" in res

def test_draft_api_call_additive_r():
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Dividends"],
        mapping_notes=[{"_additive": "SOLL+SLAP", "coa": "RDIV", "coa_description": "RDIV"}]
    )
    assert 'components <- rd_GetData(' in res
    assert "# ACTION REQUIRED FOR AI: Components ['SOLL', 'SLAP'] are raw FCC codes." in res
    assert 'result[[\'RDIV\']] <- rowSums(components[, c("SOLL", "SLAP"), drop=FALSE], na.rm = FALSE)' in res

def test_draft_api_call_with_signature():
    sig = {
        "name": "get_data",
        "args": [{"name": "universe"}, {"name": "fields"}],
        "doc": "Testing doc"
    }
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Gross Profit"],
        mapping_notes=[{"fcc_industrial": "SGRP", "coa": "SGRP"}],
        signature=sig
    )
    assert "Function signature from local index:" in res

def test_draft_api_call_dynamic_r_args():
    sig = {
        "name": "rd_GetData",
        "args": ["RDObject = rd_connection()", "rics", "Eikonformulas"],
        "doc": "Testing doc"
    }
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Gross Profit"],
        mapping_notes=[{"office_field": "TR.GrossProfit", "_target_fcc": "SGRP", "coa": "SGRP"}],
        signature=sig
    )
    assert "Eikonformulas = fields" in res
    assert "rics = rics" in res

def test_draft_api_call_office_field_priority():
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Total Assets"],
        mapping_notes=[{
            "office_field": "TR.TotalAssetsReported",
            "_target_fcc": "ATOT",
            "coa": "ATOT"
        }]
    )
    assert "fields=['TR.TotalAssetsReported']" in res
    assert "TR.F.ATOT" not in res

def test_draft_api_call_unknown_language():
    res = draft_api_call(
        language="java",
        tickers=["AAPL.O"],
        fields=["Gross Profit"]
    )
    assert "Unsupported language" in res

def test_draft_api_call_python_with_parameters():
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Revenue"],
        mapping_notes=[{"office_field": "TR.TotalRevenue", "_target_fcc": "STLR", "coa": "RTLR"}],
        parameters={"SDate": "2020-01-01", "EDate": "2024-12-31", "Frq": "FY"},
    )
    assert "parameters={'SDate': '2020-01-01', 'EDate': '2024-12-31', 'Frq': 'FY'}" in res
    assert "fields=['TR.TotalRevenue']" in res

def test_draft_api_call_r_with_parameters():
    sig = {
        "name": "rd_GetData",
        "args": ["RDObject = rd_connection()", "rics", "Eikonformulas"],
        "doc": "Test",
    }
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Revenue"],
        mapping_notes=[{"office_field": "TR.TotalRevenue", "_target_fcc": "STLR", "coa": "RTLR"}],
        signature=sig,
        parameters={"SDate": "0CY", "Frq": "FQ"},
    )
    assert 'Parameters = list(SDate = "0CY", Frq = "FQ")' in res
    assert "Eikonformulas = fields," in res  # trailing comma before Parameters

def test_draft_api_call_python_no_parameters():
    """Verify parameters= None produces no parameters line."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Revenue"],
        mapping_notes=[{"office_field": "TR.TotalRevenue", "_target_fcc": "STLR", "coa": "RTLR"}],
    )
    assert "parameters=" not in res

def test_draft_api_call_r_no_parameters():
    """Verify parameters= None produces no parameters line in R."""
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Revenue"],
        mapping_notes=[{"office_field": "TR.TotalRevenue", "_target_fcc": "STLR", "coa": "RTLR"}],
    )
    assert "Parameters =" not in res

def test_draft_api_call_python_parameters_empty():
    """Verify parameters={} is handled gracefully."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Revenue"],
        mapping_notes=[{"office_field": "TR.TotalRevenue", "_target_fcc": "STLR", "coa": "RTLR"}],
        parameters={},
    )
    # An empty dict evaluates to False in python boolean contexts, but here it's truthy if passed directly, 
    # but wait, `if parameters:` is false for `{}`! So it should NOT output parameters.
    assert "parameters=" not in res

def test_draft_api_call_r_parameters_mixed_types():
    """Verify parameters with numbers, booleans, and strings format correctly in R."""
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Revenue"],
        mapping_notes=[{"office_field": "TR.TotalRevenue", "_target_fcc": "STLR", "coa": "RTLR"}],
        parameters={"SDate": "0CY", "Period": 1, "IncludeHistory": True},
    )
    assert 'Parameters = list(SDate = "0CY", Period = 1, IncludeHistory = True)' in res
