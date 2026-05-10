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
    assert "fields=['TR.F.SGRP']" in res
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
    assert 'fields <- c("TR.F.SGRP")' in res
    assert "rd_GetData(" in res
    assert "# NOTE: A test note" in res

def test_draft_api_call_additive_python():
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Dividends"],
        mapping_notes=[{"_additive": "SOLL+SLAP", "coa": "RDIV", "coa_description": "RDIV"}]
    )
    assert "fields=['SOLL', 'SLAP']" in res
    assert "df['RDIV'] = df_components[['SOLL', 'SLAP']].sum(axis=1, min_count=1)" in res

def test_draft_api_call_additive_r():
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Dividends"],
        mapping_notes=[{"_additive": "SOLL+SLAP", "coa": "RDIV", "coa_description": "RDIV"}]
    )
    assert 'components <- rd_GetData(' in res
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
        mapping_notes=[{"_target_fcc": "SGRP", "coa": "SGRP"}],
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
