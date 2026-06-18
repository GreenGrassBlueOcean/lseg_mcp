# harvest_lseg_fields.R
#
# Practical helper for semi-automated enrichment of lseg-mcp's extended
# Data Dictionary using the R / RefinitivR + LSEG Workspace ecosystem.
#
# Usage (while LSEG Workspace / RefinitivR is connected):
#   source("R/harvest_lseg_fields.R")
#   # Then run one of the helpers below or build your own screeners.
#
# Recommended workflow (matches the "Path 1" DIB export + Screener formulas):
# 1. In LSEG Workspace Excel: Open Data Item Browser (type DIB), browse Pricing /
#    Estimates / ESG / etc. Copy or export interesting fields.
# 2. Or use Screener → "Export All as Formulas" (this is gold — it emits the
#    exact TR.* codes the screener uses).
# 3. Paste the formulas or field list into a data.frame here.
# 4. Use write_for_lseg_mcp() to emit a CSV that lseg-mcp can load via
#    LSEG_DATA_DICTIONARY_PATH or by dropping a "Custom_Fields" sheet into
#    your LSEG_Mapping.xlsx.
#
# The MCP will pick it up on next load (or after rescan).

library(data.table)
library(Refinitiv)  # or the package name you use

#' Build a simple field catalog data.frame from a vector of TR. formulas or names.
#' @param fields character vector of "TR.Foo", "TR.Bar(SDate=0D)", bare names, etc.
#' @param category character, e.g. "Pricing", "Estimates", "ESG"
#' @param descriptions optional character vector of same length (you can fill from DIB)
#' @export
build_field_catalog <- function(fields, category = "General", descriptions = NULL) {
  fields <- trimws(fields)
  fields <- fields[nzchar(fields)]
  if (is.null(descriptions) || length(descriptions) != length(fields)) {
    descriptions <- rep("", length(fields))
  }
  data.table(
    field = fields,
    description = descriptions,
    category = category,
    parameters = "",   # user can enrich later from DIB "Parameters" pane
    notes = "Harvested via harvest_lseg_fields.R + Workspace"
  )
}

#' Write a catalog in the exact flat format lseg-mcp DataDictionary expects.
#' Drop the resulting CSV somewhere and point LSEG_DATA_DICTIONARY_PATH at it,
#' or copy the rows into an Excel sheet named "Custom_Fields" / "Data Dictionary"
#' inside your LSEG_Mapping.xlsx.
#' @export
write_for_lseg_mcp <- function(catalog_dt, path = "lseg_extended_fields.csv") {
  stopifnot(is.data.table(catalog_dt))
  cols <- c("field", "description", "category", "parameters", "notes")
  for (col in cols) if (!col %in% names(catalog_dt)) catalog_dt[[col]] <- ""
  fwrite(catalog_dt[, ..cols], path)
  message("Wrote ", nrow(catalog_dt), " rows to ", normalizePath(path))
  invisible(path)
}

#' Example: quick starter packs you can expand.
#' These are deliberately small but high-signal seeds you can run immediately
#' and then augment from DIB / Screener exports.
get_starter_packs <- function() {
  list(
    Pricing = build_field_catalog(
      c("TR.PriceClose", "TR.PriceOpen", "TR.HighPrice", "TR.LowPrice",
        "TR.Volume", "TR.Turnover", "TR.Bid", "TR.Ask", "TR.MIDPRICE",
        "TR.CLOSEPRICE(Adjusted=0)"),
      category = "Pricing"
    ),
    Reference = build_field_catalog(
      c("TR.CompanyName", "TR.RIC", "TR.PrimaryInstrument", "TR.Ticker",
        "TR.ExchangeName", "TR.ISIN", "TR.SEDOL", "TR.InstrumentType",
        "TR.CompanyMarketCap", "TR.IssueMarketCap", "TR.FreeFloatPct",
        "TR.IssueSharesOutstanding", "TR.EnterpriseValue"),
      category = "Reference"
    ),
    Estimates = build_field_catalog(
      c("TR.EPSMean", "TR.RevenueMean", "TR.EBITMean", "TR.PriceTargetMean",
        "TR.NumEstimates", "TR.EPS"),
      category = "Estimates",
      descriptions = c("Consensus EPS", "Consensus Revenue", "Consensus EBIT",
                       "Mean price target", "# contributing analysts", "EPS context")
    ),
    Valuation = build_field_catalog(
      c("TR.PE", "TR.DividendYield"),
      category = "Valuation"
    )
  )
}

#' One-liner to export all starters at once (good first step).
export_starter_packs <- function(out_dir = ".") {
  packs <- get_starter_packs()
  for (nm in names(packs)) {
    p <- file.path(out_dir, paste0("lseg_fields_", tolower(nm), ".csv"))
    write_for_lseg_mcp(packs[[nm]], p)
  }
  invisible(names(packs))
}

# ── How to harvest from a real Screener "Export All as Formulas" ─────────────
# 1. In Excel + Workspace: create or open a Screener with the columns you care about.
# 2. Screener ribbon → Export → "Export All as Formulas" (or similar).
# 3. You get cells containing things like =@RDP.Data(....,"TR.EPSMean(SDate=0CY)...")
# 4. Copy the formula cells or the underlying TR. strings into a vector and feed
#    to build_field_catalog + write_for_lseg_mcp.
#
# Example after pasting the exported formulas into R:
# formulas <- c("TR.PriceClose", "TR.EPSMean(SDate=0CY)", "TR.ESGScore")
# cat <- build_field_catalog(formulas, category = "ScreenerExport")
# write_for_lseg_mcp(cat, "from_screener.csv")
#
# Then in your environment:
#   Sys.setenv(LSEG_DATA_DICTIONARY_PATH = "C:/path/to/from_screener.csv")
# Restart / rescan the MCP server (or just the dict cache in dev).

message("harvest_lseg_fields.R loaded. Try: export_starter_packs(); or build your own from DIB/Screener exports.")