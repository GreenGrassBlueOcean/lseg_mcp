import pytest
import pandas as pd
from lseg_mcp.mapping_engine import COLUMN_NAMES

@pytest.fixture
def mock_mapping_data():
    """Provides a small, deterministic DataFrame for testing MappingEngine."""
    
    # We will simulate the structure created in MappingEngine._load()
    # It drops the separator column and sets bank_applicable etc to bool.
    
    data = [
        # Normal identical field
        {
            "statement": "Income Statement",
            "line_id": 10,
            "coa": "RREV",
            "coa_description": "Gross Revenue",
            "office_field": "TR.GrossRevenue",
            "label": "Gross Revenue",
            "polarity": "Positive",
            "display": "Regular",
            "bank_applicable": False,
            "industry_applicable": True,
            "insurance_applicable": False,
            "utility_applicable": False,
            "fcc_industrial": "SREV",
            "fcc_inv_trust": "",
            "fcc_financial": "",
            "fcc_property": "",
            "fcc_bank": "",
            "fcc_insurance": "",
            "overall_match": "1. Identical",
        },
        # Additive formula field
        {
            "statement": "Income Statement",
            "line_id": 20,
            "coa": "RDIV",
            "coa_description": "Dividends Paid",
            "office_field": "TR.DivPaid",
            "label": "Dividends",
            "polarity": "Negative",
            "display": "Regular",
            "bank_applicable": True,
            "industry_applicable": True,
            "insurance_applicable": False,
            "utility_applicable": False,
            "fcc_industrial": "SOLL+SLAP",
            "fcc_inv_trust": "",
            "fcc_financial": "",
            "fcc_property": "",
            "fcc_bank": "SOLL+SLAP",
            "fcc_insurance": "",
            "overall_match": "2. Comparable",
        },
        # ASR Layer field
        {
            "statement": "Balance Sheet",
            "line_id": 30,
            "coa": "RDEBT",
            "coa_description": "Total Debt",
            "office_field": "TR.TotalDebt",
            "label": "Total Debt",
            "polarity": "Positive",
            "display": "Regular",
            "bank_applicable": True,
            "industry_applicable": True,
            "insurance_applicable": False,
            "utility_applicable": False,
            "fcc_industrial": "[AFUL]",
            "fcc_inv_trust": "",
            "fcc_financial": "",
            "fcc_property": "",
            "fcc_bank": "[ABNK]",
            "fcc_insurance": "",
            "overall_match": "2. Comparable",
        },
        # No FCC Match field
        {
            "statement": "Cash Flow",
            "line_id": 40,
            "coa": "ROPE",
            "coa_description": "Operating Expenses",
            "office_field": "TR.OpEx",
            "label": "OpEx",
            "polarity": "Negative",
            "display": "Regular",
            "bank_applicable": False,
            "industry_applicable": True,
            "insurance_applicable": False,
            "utility_applicable": False,
            "fcc_industrial": "No FCC Match",
            "fcc_inv_trust": "",
            "fcc_financial": "",
            "fcc_property": "",
            "fcc_bank": "",
            "fcc_insurance": "",
            "overall_match": "3. Not Comparable (NC)",
        },
        # Primary Instrument / Multi-match field
        {
            "statement": "Income Statement",
            "line_id": 50,
            "coa": "RNTS",
            "coa_description": "Net Sales",
            "office_field": "TR.NetSales",
            "label": "Net Sales",
            "polarity": "Positive",
            "display": "Regular",
            "bank_applicable": False,
            "industry_applicable": True,
            "insurance_applicable": False,
            "utility_applicable": False,
            "fcc_industrial": "SNTU/SHRV/SNTS Primary Instrument",
            "fcc_inv_trust": "",
            "fcc_financial": "",
            "fcc_property": "",
            "fcc_bank": "",
            "fcc_insurance": "",
            "overall_match": "2. Comparable",
        },
        # Instrument ID / empty applicability
        {
            "statement": "Income Statement",
            "line_id": 60,
            "coa": "RINST",
            "coa_description": "Instrument ID Check",
            "office_field": "TR.InstID",
            "label": "Inst ID",
            "polarity": "Positive",
            "display": "Regular",
            "bank_applicable": False,
            "industry_applicable": False,
            "insurance_applicable": False,
            "utility_applicable": False,
            "fcc_industrial": "SINS Instrument ID",
            "fcc_inv_trust": "",
            "fcc_financial": "",
            "fcc_property": "",
            "fcc_bank": "",
            "fcc_insurance": "",
            "overall_match": "1. Identical",
        },
        # Bank-only applicability
        {
            "statement": "Balance Sheet",
            "line_id": 70,
            "coa": "RDEBT_BANK",
            "coa_description": "Bank Debt",
            "office_field": "TR.BankDebt",
            "label": "Bank Debt",
            "polarity": "Positive",
            "display": "Regular",
            "bank_applicable": True,
            "industry_applicable": False,
            "insurance_applicable": False,
            "utility_applicable": False,
            "fcc_industrial": "No FCC Match",
            "fcc_inv_trust": "",
            "fcc_financial": "",
            "fcc_property": "",
            "fcc_bank": "BDEBT",
            "fcc_insurance": "",
            "overall_match": "1. Identical",
        }
    ]
    df = pd.DataFrame(data)
    return df

@pytest.fixture
def mock_pandas_read_excel(mocker, mock_mapping_data):
    """Mocks pd.read_excel to return our test DataFrame."""
    def fake_read_excel(xl, sheet_name=None, header=None, **kwargs):
        if sheet_name == "Explanations":
            return pd.DataFrame([["Line 1"], ["Line 2"]])
        elif sheet_name == "Standardized Financials ":
            # We must return a raw dataframe that mapping_engine._load() can parse.
            # mapping_engine skips first 3 rows and uses COLUMN_NAMES.
            # So we prepend 3 dummy rows.
            dummy = pd.DataFrame(columns=COLUMN_NAMES)
            dummy.loc[0] = [None] * len(COLUMN_NAMES)
            dummy.loc[1] = [None] * len(COLUMN_NAMES)
            dummy.loc[2] = [None] * len(COLUMN_NAMES)
            
            # Now build the actual data with the exact COLUMN_NAMES structure
            actual = []
            for row in mock_mapping_data.to_dict("records"):
                new_row = []
                for col in COLUMN_NAMES:
                    if col == "fcc_industrial":
                        new_row.append(row.get("fcc_industrial"))
                    elif col == "fcc_bank":
                        new_row.append(row.get("fcc_bank"))
                    elif col == "fcc_inv_trust":
                        new_row.append(row.get("fcc_inv_trust"))
                    elif col == "fcc_financial":
                        new_row.append(row.get("fcc_financial"))
                    elif col == "fcc_property":
                        new_row.append(row.get("fcc_property"))
                    elif col == "fcc_insurance":
                        new_row.append(row.get("fcc_insurance"))
                    elif col == "_sep":
                        new_row.append(None)
                    else:
                        val = row.get(col)
                        # Revert booleans to 'x' to simulate excel
                        if col.endswith("_applicable"):
                            val = 'x' if val else None
                        new_row.append(val)
                actual.append(new_row)
            
            actual_df = pd.DataFrame(actual, columns=COLUMN_NAMES)
            return pd.concat([dummy, actual_df], ignore_index=True)
        elif sheet_name == "Segments ":
            return pd.DataFrame()
        elif sheet_name == "Aggregates":
            return pd.DataFrame()
        return pd.DataFrame()

    mocker.patch("pandas.read_excel", side_effect=fake_read_excel)
    mock_xl = mocker.MagicMock()
    mock_xl.sheet_names = ["Explanations", "Standardized Financials ", "Segments ", "Aggregates"]
    mocker.patch("pandas.ExcelFile", return_value=mock_xl)
