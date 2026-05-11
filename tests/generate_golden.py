"""Generate golden files for snapshot tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from lseg_mcp.code_generator import draft_api_call

# Golden 1: Python with office_field + parameters
res1 = draft_api_call(
    language="python",
    tickers=["AAPL.O"],
    fields=["Total Revenue"],
    mapping_notes=[{
        "office_field": "TR.TotalRevenue",
        "_target_fcc": "STLR",
        "coa": "RTLR",
        "coa_description": "Total Revenue",
        "_notes": [],
    }],
    parameters={"SDate": "2020-01-01", "EDate": "2024-12-31", "Frq": "FY"},
)
with open(os.path.join(os.path.dirname(__file__), "golden", "python_with_params.txt"), "w") as f:
    f.write(res1)

# Golden 2: R with office_field, no parameters
res2 = draft_api_call(
    language="r",
    tickers=["MSFT.O", "AAPL.O"],
    fields=["Total Assets"],
    mapping_notes=[{
        "office_field": "TR.TotalAssetsReported",
        "_target_fcc": "ATOT",
        "coa": "ATOT",
        "coa_description": "Total Assets",
        "_notes": [],
    }],
    signature={
        "name": "rd_GetData",
        "args": ["RDObject = rd_connection()", "rics", "Eikonformulas"],
        "doc": "Fetch data",
    },
)
with open(os.path.join(os.path.dirname(__file__), "golden", "r_simple.txt"), "w") as f:
    f.write(res2)

# Golden 3: Python with additive formula
res3 = draft_api_call(
    language="python",
    tickers=["JPM"],
    fields=["Depreciation"],
    mapping_notes=[{
        "_additive": "SDCS+SDES",
        "coa": "EDEP",
        "coa_description": "Depreciation",
        "_notes": ["Additive formula: fetch ['SDCS', 'SDES'] separately and sum."],
    }],
)
with open(os.path.join(os.path.dirname(__file__), "golden", "python_additive.txt"), "w") as f:
    f.write(res3)

print("Golden files generated successfully!")
