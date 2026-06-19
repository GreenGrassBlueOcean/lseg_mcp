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

def test_draft_api_call_python_data_dictionary_field():
    """Extended data-dictionary hits (keyed by 'field') must appear in fields,
    not be dropped as 'unknown' raw FCC codes."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["TR.PriceClose"],
        mapping_notes=[{
            "field": "TR.PriceClose",
            "category": "Pricing",
            "_source": "data_dictionary",
        }],
    )
    assert "fields=['TR.PriceClose']" in res
    assert "raw FCC code" not in res


def test_draft_api_call_r_data_dictionary_field():
    """Same as above for the R generator."""
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["TR.PriceClose"],
        mapping_notes=[{
            "field": "TR.PriceClose",
            "category": "Pricing",
            "_source": "data_dictionary",
        }],
    )
    assert 'fields <- c("TR.PriceClose")' in res
    assert "raw FCC code" not in res


def test_draft_api_call_mixed_matrix_and_dictionary_fields():
    """A financials matrix field and a data-dictionary field together: both
    must survive into the generated fields list."""
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Gross Profit", "TR.PriceClose"],
        mapping_notes=[
            {"office_field": "TR.GrossProfit", "_target_fcc": "SGRP", "coa": "SGRP"},
            {"field": "TR.PriceClose", "category": "Pricing", "_source": "data_dictionary"},
        ],
    )
    assert "TR.GrossProfit" in res
    assert "TR.PriceClose" in res


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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Bug #3 — Unresolved fields must not be silently dropped
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_draft_api_call_python_unresolved_field():
    """An unresolved field should appear in the generated Python code with a WARNING comment."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["TR.GrossProfit", "TR.BogusField"],
        mapping_notes=[
            {"office_field": "TR.GrossProfit", "_target_fcc": "SGRP", "coa": "SGRP"},
            {"field": "TR.BogusField", "_unresolved": True, "_notes": [
                "WARNING: 'TR.BogusField' was not found in the financials mapping matrix or data dictionary."
            ]},
        ],
    )
    assert "TR.GrossProfit" in res
    assert "TR.BogusField" in res
    assert "WARNING" in res


def test_draft_api_call_r_unresolved_field():
    """An unresolved field should appear in the generated R code with a WARNING comment."""
    res = draft_api_call(
        language="r",
        tickers=["JPM"],
        fields=["TR.NetInterestIncome", "TR.ProvisionForLoanLoss"],
        mapping_notes=[
            {"office_field": "TR.NetInterestIncome", "_target_fcc": "SIDI", "coa": "ENII"},
            {"field": "TR.ProvisionForLoanLoss", "_unresolved": True, "_notes": [
                "WARNING: 'TR.ProvisionForLoanLoss' was not found in the financials mapping matrix or data dictionary."
            ]},
        ],
    )
    assert "TR.NetInterestIncome" in res
    assert "TR.ProvisionForLoanLoss" in res
    assert "WARNING" in res


def test_draft_api_call_all_unresolved():
    """When ALL fields are unresolved, they should still appear in generated code."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["TR.Bogus1", "TR.Bogus2"],
        mapping_notes=[
            {"field": "TR.Bogus1", "_unresolved": True, "_notes": ["WARNING: not found"]},
            {"field": "TR.Bogus2", "_unresolved": True, "_notes": ["WARNING: not found"]},
        ],
    )
    assert "TR.Bogus1" in res
    assert "TR.Bogus2" in res
    assert "WARNING" in res


def test_draft_api_call_unresolved_preserves_field_casing():
    """Unresolved field names must preserve their original casing."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["TR.MyCustomCasedField"],
        mapping_notes=[
            {"field": "TR.MyCustomCasedField", "_unresolved": True,
             "_notes": ["WARNING: not found"]},
        ],
    )
    assert "TR.MyCustomCasedField" in res


def test_draft_api_call_unresolved_mixed_with_additive():
    """Unresolved + additive + resolved fields in the same call should all appear."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["Gross Profit", "Dividends", "TR.BogusField"],
        mapping_notes=[
            {"office_field": "TR.GrossProfit", "_target_fcc": "SGRP", "coa": "SGRP"},
            {"_additive": "SOLL+SLAP", "coa": "RDIV", "coa_description": "RDIV"},
            {"field": "TR.BogusField", "_unresolved": True,
             "_notes": ["WARNING: 'TR.BogusField' was not found"]},
        ],
    )
    assert "TR.GrossProfit" in res
    assert "TR.BogusField" in res
    assert "SOLL" in res  # additive components
    assert "WARNING" in res


def test_draft_api_call_unresolved_mixed_with_data_dict():
    """Resolved (matrix) + resolved (data dictionary) + unresolved should all appear."""
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["Gross Profit", "TR.PriceClose", "TR.Nonsense"],
        mapping_notes=[
            {"office_field": "TR.GrossProfit", "_target_fcc": "SGRP", "coa": "SGRP"},
            {"field": "TR.PriceClose", "category": "Pricing", "_source": "data_dictionary"},
            {"field": "TR.Nonsense", "_unresolved": True,
             "_notes": ["WARNING: 'TR.Nonsense' not found"]},
        ],
    )
    assert "TR.GrossProfit" in res
    assert "TR.PriceClose" in res
    assert "TR.Nonsense" in res
    assert "WARNING" in res


def test_draft_api_call_r_unresolved_in_c_vector():
    """In R output, unresolved fields should appear inside the c() vector."""
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["TR.GrossProfit", "TR.Missing"],
        mapping_notes=[
            {"office_field": "TR.GrossProfit", "_target_fcc": "SGRP", "coa": "SGRP"},
            {"field": "TR.Missing", "_unresolved": True, "_notes": ["WARNING: not found"]},
        ],
    )
    # Both fields should be in the fields <- c(...) line
    assert '"TR.GrossProfit"' in res
    assert '"TR.Missing"' in res


def test_draft_api_call_unresolved_field_count():
    """N mapping notes in → N fields in generated code (no silent dropping)."""
    notes = [
        {"office_field": "TR.A", "_target_fcc": "SA", "coa": "RA"},
        {"field": "TR.B", "category": "Pricing", "_source": "data_dictionary"},
        {"field": "TR.C", "_unresolved": True, "_notes": ["WARNING: not found"]},
        {"field": "TR.D", "_unresolved": True, "_notes": ["WARNING: not found"]},
    ]
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["TR.A", "TR.B", "TR.C", "TR.D"],
        mapping_notes=notes,
    )
    assert "TR.A" in res
    assert "TR.B" in res
    assert "TR.C" in res
    assert "TR.D" in res


def test_draft_api_call_unresolved_with_parameters():
    """Unresolved fields should not interfere with parameter generation."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["TR.Missing"],
        mapping_notes=[
            {"field": "TR.Missing", "_unresolved": True, "_notes": ["WARNING: not found"]},
        ],
        parameters={"SDate": "2020-01-01", "EDate": "2024-12-31"},
    )
    assert "TR.Missing" in res
    assert "parameters=" in res
    assert "SDate" in res


def test_draft_api_call_r_unresolved_with_parameters():
    """R: Unresolved fields should not interfere with Parameters = list(...)."""
    sig = {
        "name": "rd_GetData",
        "args": ["RDObject = rd_connection()", "rics", "Eikonformulas"],
        "doc": "Test",
    }
    res = draft_api_call(
        language="r",
        tickers=["AAPL.O"],
        fields=["TR.Missing"],
        mapping_notes=[
            {"field": "TR.Missing", "_unresolved": True, "_notes": ["WARNING: not found"]},
        ],
        signature=sig,
        parameters={"Curn": "USD"},
    )
    assert "TR.Missing" in res
    assert 'Parameters = list(Curn = "USD")' in res


def test_draft_api_call_unresolved_empty_field_name():
    """An unresolved note with an empty field name should be skipped gracefully."""
    res = draft_api_call(
        language="python",
        tickers=["AAPL.O"],
        fields=["TR.Real", ""],
        mapping_notes=[
            {"office_field": "TR.Real", "_target_fcc": "SR", "coa": "RR"},
            {"field": "", "_unresolved": True, "_notes": ["WARNING: not found"]},
        ],
    )
    # TR.Real should appear, empty field should be skipped
    assert "TR.Real" in res
    # Should not crash
    assert "import lseg.data" in res


