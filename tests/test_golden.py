"""Golden-file (snapshot) tests for code generation output.

These tests compare the full generated output against stored reference files.
If the code generator's output structure changes, regenerate the golden files
by running: python tests/generate_golden.py
"""
from pathlib import Path

from lseg_mcp.code_generator import draft_api_call

GOLDEN_DIR = Path(__file__).parent / "golden"


def _read_golden(name: str) -> str:
    """Read a golden file and normalise line endings."""
    return (GOLDEN_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_golden_python_with_params():
    result = draft_api_call(
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
    expected = _read_golden("python_with_params.txt")
    assert result.replace("\r\n", "\n") == expected, (
        f"Output mismatch vs golden file. Regenerate with: python tests/generate_golden.py\n"
        f"--- EXPECTED ---\n{expected}\n--- GOT ---\n{result}"
    )


def test_golden_r_simple():
    result = draft_api_call(
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
    expected = _read_golden("r_simple.txt")
    assert result.replace("\r\n", "\n") == expected, (
        f"Output mismatch vs golden file. Regenerate with: python tests/generate_golden.py\n"
        f"--- EXPECTED ---\n{expected}\n--- GOT ---\n{result}"
    )


def test_golden_python_additive():
    result = draft_api_call(
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
    expected = _read_golden("python_additive.txt")
    assert result.replace("\r\n", "\n") == expected, (
        f"Output mismatch vs golden file. Regenerate with: python tests/generate_golden.py\n"
        f"--- EXPECTED ---\n{expected}\n--- GOT ---\n{result}"
    )
