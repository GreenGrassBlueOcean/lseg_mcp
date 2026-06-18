"""Tests for the extended Data Dictionary engine."""
import pandas as pd
import pytest

from lseg_mcp.data_dictionary import DataDictionary


# ── Built-in seed ────────────────────────────────────────────────────


def test_builtin_seed_loads():
    """A bare DataDictionary loads the curated built-in seed."""
    dd = DataDictionary()
    assert not dd.df.empty
    # Lazy property triggers _load()
    fields = dd.df["field"].tolist()
    assert "TR.PriceClose" in fields


def test_search_by_field_name():
    dd = DataDictionary()
    hits = dd.search("TR.PriceClose")
    assert any(h["field"] == "TR.PriceClose" for h in hits)


def test_search_by_description():
    dd = DataDictionary()
    hits = dd.search("closing price")
    assert hits
    assert all("field" in h for h in hits)


def test_search_with_category_filter():
    dd = DataDictionary()
    hits = dd.search("price", category="Pricing")
    assert hits
    assert all("pricing" in h["category"].lower() for h in hits)


def test_search_no_match_returns_empty():
    dd = DataDictionary()
    assert dd.search("zzz_definitely_not_a_field_xyz") == []


def test_search_empty_dataframe(monkeypatch):
    """search short-circuits when the dataframe is empty."""
    dd = DataDictionary()
    dd._df = pd.DataFrame(columns=["field", "description", "category", "parameters", "notes", "source"])
    assert dd.search("anything") == []


def test_search_scoring_prefers_exact_field():
    """An exact field match should rank ahead of a substring/description match."""
    dd = DataDictionary()
    hits = dd.search("TR.EPS")
    assert hits
    # Exact match TR.EPS should come first over TR.EPSMean etc.
    assert hits[0]["field"] == "TR.EPS"


def test_list_categories():
    dd = DataDictionary()
    cats = dd.list_categories()
    assert "Pricing" in cats
    assert cats == sorted(cats)


def test_get_field_hit_and_miss():
    dd = DataDictionary()
    hit = dd.get_field("tr.priceclose")  # case-insensitive
    assert hit is not None
    assert hit["field"] == "TR.PriceClose"
    assert dd.get_field("not_a_field") is None


# ── suggest_specialized routing ──────────────────────────────────────


def test_suggest_specialized_estimates():
    dd = DataDictionary()
    out = dd.suggest_specialized(category="Estimates")
    assert "rd_GetEstimates" in out["recommended_function"]


def test_suggest_specialized_esg():
    dd = DataDictionary()
    out = dd.suggest_specialized(category="ESG")
    assert "rd_GetESG" in out["recommended_function"]


def test_suggest_specialized_pricing():
    dd = DataDictionary()
    out = dd.suggest_specialized(category="Pricing")
    assert "rd_GetHistory" in out["recommended_function"]


def test_suggest_specialized_default():
    dd = DataDictionary()
    out = dd.suggest_specialized(category="Reference")
    assert out["recommended_function"] == "rd_GetData / ld.get_data"


def test_suggest_specialized_by_fields():
    dd = DataDictionary()
    out = dd.suggest_specialized(fields=["TR.EPSMean"])
    assert "rd_GetEstimates" in out["recommended_function"]


# ── CSV / Excel ingestion ────────────────────────────────────────────


def test_load_from_csv(tmp_path):
    csv = tmp_path / "custom.csv"
    csv.write_text(
        "Field,Description,Category,Parameters,Notes\n"
        "TR.MyCustomField,My custom thing,CustomCat,SDate,some note\n",
        encoding="utf-8",
    )
    dd = DataDictionary(csv_path=csv)
    hits = dd.search("MyCustomField")
    assert any(h["field"] == "TR.MyCustomField" for h in hits)
    assert any(h["category"] == "CustomCat" for h in hits)


def test_load_from_xlsx_custom_sheet(tmp_path):
    xlsx = tmp_path / "dict.xlsx"
    df = pd.DataFrame(
        {
            "Field": ["TR.SheetField"],
            "Description": ["From a Custom_Fields sheet"],
            "Category": ["Pricing"],
            "Parameters": ["SDate"],
            "Notes": [""],
        }
    )
    with pd.ExcelWriter(xlsx) as xw:
        df.to_excel(xw, sheet_name="Custom_Fields", index=False)
    dd = DataDictionary(xlsx_path=xlsx)
    hits = dd.search("SheetField")
    assert any(h["field"] == "TR.SheetField" for h in hits)


def test_env_var_csv_routing(monkeypatch, tmp_path):
    """A .csv pointed to by LSEG_DATA_DICTIONARY_PATH is routed to _csv_path."""
    csv = tmp_path / "env_dict.csv"
    csv.write_text(
        "Field,Description,Category,Parameters,Notes\n"
        "TR.EnvField,From env,EnvCat,,\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LSEG_DATA_DICTIONARY_PATH", str(csv))
    dd = DataDictionary()
    assert any(h["field"] == "TR.EnvField" for h in dd.search("EnvField"))


def test_env_var_xlsx_routing(monkeypatch, tmp_path):
    """A .xlsx pointed to by LSEG_DATA_DICTIONARY_PATH is routed to _xlsx_path."""
    xlsx = tmp_path / "env_dict.xlsx"
    df = pd.DataFrame({"Field": ["TR.EnvXlsxField"], "Description": ["x"], "Category": ["Reference"]})
    with pd.ExcelWriter(xlsx) as xw:
        df.to_excel(xw, sheet_name="Data Dictionary", index=False)
    monkeypatch.setenv("LSEG_DATA_DICTIONARY_PATH", str(xlsx))
    dd = DataDictionary()
    assert any(h["field"] == "TR.EnvXlsxField" for h in dd.search("EnvXlsxField"))


# ── _parse_flat_sheet edge cases ─────────────────────────────────────


def test_parse_flat_sheet_too_small():
    dd = DataDictionary()
    raw = pd.DataFrame([["only one row"]])
    assert dd._parse_flat_sheet(raw).empty


def test_parse_flat_sheet_header_detection_and_aliases():
    dd = DataDictionary()
    # Header detected on row 0 via "Field"; alias columns "Desc" -> description,
    # "Group" -> category.
    raw = pd.DataFrame(
        [
            ["Field", "Desc", "Group"],
            ["TR.AliasField", "aliased description", "Valuation"],
        ]
    )
    parsed = dd._parse_flat_sheet(raw)
    assert "field" in parsed.columns
    assert (parsed["field"] == "TR.AliasField").any()


def test_parse_flat_sheet_field_fallback_column():
    """When no header maps to 'field', fall back to a column containing TR. values."""
    dd = DataDictionary()
    # Header detected on row 0 (the label contains "tr."), but no column maps to
    # 'field' -> the loader scans for a column whose values look like TR.* items.
    raw = pd.DataFrame(
        [
            ["metric tr. label", "info"],
            ["TR.FallbackField", "value"],
        ]
    )
    parsed = dd._parse_flat_sheet(raw)
    assert (parsed["field"] == "TR.FallbackField").any()


def test_search_empty_query_matches_all():
    """A blank query degrades to matching everything (tokens fallback)."""
    dd = DataDictionary()
    hits = dd.search("   ", limit=5)
    assert isinstance(hits, list)
    assert len(hits) == 5


# ── normalization ────────────────────────────────────────────────────


def test_normalize_drops_short_fields_and_defaults_category():
    dd = DataDictionary()
    raw = pd.DataFrame({"field": ["TR.Good", "x"], "description": ["d", "d2"]})
    out = dd._normalize_df(raw)
    assert "TR.Good" in out["field"].tolist()
    assert "x" not in out["field"].tolist()  # length <= 2 dropped
    assert (out["category"] == "General").all()
