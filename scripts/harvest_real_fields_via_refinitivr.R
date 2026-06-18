# harvest_real_fields_via_refinitivr.R
#
# Experimental harvester that uses a *live* RefinitivR connection to a running
# LSEG Workspace desktop session to pull *real* field names and metadata.
#
# Why this exists:
#   - There is no public "download entire Data Dictionary" endpoint.
#   - The best way to get authentic, entitlement-aware TR.* fields is to ask
#     the actual platform what it returns for different content types.
#   - Specialized functions (Estimates, ESG) expose rich structured views.
#   - By requesting with use_field_names_in_headers = FALSE we often get the
#     internal `name` (the real TR. code or data item identifier).
#
# Usage (on a machine with LSEG Workspace running + RefinitivR available):
#
#   # Option A: if you have the package installed
#   Rscript scripts/harvest_real_fields_via_refinitivr.R
#
#   # Option B: from source checkout (common during development)
#   R -e "
#     devtools::load_all('C:/Users/laurensvdb/Documents/GitHub/RefinitivR')
#     source('scripts/harvest_real_fields_via_refinitivr.R')
#   "
#
# Output:
#   - real_fields_estimates.csv
#   - real_fields_esg.csv
#   - real_fields_pricing.csv (etc.)
#   - real_fields_combined.csv
#   - real_fields_report.txt
#
# These CSVs can be fed directly to the Python harvester or used with
# LSEG_DATA_DICTIONARY_PATH / dropped into a Custom_Fields sheet.
#
# Notes / Limitations:
#   - Requires a running LSEG Workspace with a valid desktop session.
#   - Results are limited to what *your* entitlements can see.
#   - Some fields only appear with specific parameters / instruments.
#   - This is "best effort" discovery, not an official dictionary dump.

suppressPackageStartupMessages({
  library(data.table)
})

# --- Configuration -----------------------------------------------------------

TICKER <- "AAPL.O"          # A liquid equity most people can access
TICKERS <- c("AAPL.O", "MSFT.O", "LSEG.L")

# Try to load Refinitiv package. Adjust if your installed name differs.
load_refinitiv <- function() {
  if (requireNamespace("Refinitiv", quietly = TRUE)) {
    library(Refinitiv, quietly = TRUE)
    return(TRUE)
  }
  # Fallback for development: try to load from the common local checkout
  ref_path <- Sys.getenv("REFINITIVR_PATH", "C:/Users/laurensvdb/Documents/GitHub/RefinitivR")
  if (dir.exists(ref_path)) {
    if (requireNamespace("devtools", quietly = TRUE)) {
      devtools::load_all(ref_path, quiet = TRUE)
      return(TRUE)
    }
  }
  stop("Could not load Refinitiv package. Install it or set REFINITIVR_PATH and use devtools::load_all().")
}

# --- Helper to safely call and capture columns ------------------------------

# Simple robust caller (avoids quote/eval scoping problems in loops)
safe_rd_call <- function(call_expr, label, env = parent.frame()) {
  res <- tryCatch(
    {
      out <- eval(call_expr, envir = env)
      list(success = TRUE, data = out, label = label)
    },
    error = function(e) {
      list(success = FALSE, error = conditionMessage(e), label = label)
    }
  )
  res
}

# --- Main harvesting logic ---------------------------------------------------

harvest_real_fields <- function() {
  load_refinitiv()

  # Support "refinitivrapi that has connection"
  # If the user already has a connection object in their R session (e.g. from
  # their normal workflow, GGBOIndex, or explicit RefinitivJsonConnect for RDP),
  # we reuse it. This is the "use refinitivrapi that has connection" path.
  #
  # Recommended in user's R session:
  #   library(Refinitiv)
  #   RDObject <- rd_connection()   # or your pre-configured one
  #   source("scripts/harvest_real_fields_via_refinitivr.R")
  #
  # Or for direct RDP (no desktop proxy):
  #   RDObject <- RefinitivJsonConnect(credentials = list(...))
  #   source(...)

  RDObject <- NULL
  if (exists("RDObject", envir = .GlobalEnv, inherits = FALSE) && !is.null(get("RDObject", envir = .GlobalEnv))) {
    RDObject <- get("RDObject", envir = .GlobalEnv)
    message("Reusing pre-existing RDObject from global environment (the one with connection).")
  } else if (exists("conn", envir = .GlobalEnv, inherits = FALSE) && !is.null(get("conn", envir = .GlobalEnv))) {
    RDObject <- get("conn", envir = .GlobalEnv)
    message("Reusing pre-existing 'conn' object from global environment.")
  } else {
    message("Attempting to create connection via rd_connection() (requires LSEG Workspace desktop or valid RDP credentials)...")
    RDObject <- tryCatch(
      rd_connection(),
      error = function(e) {
        message("Could not create connection: ", conditionMessage(e))
        NULL
      }
    )
  }

  if (is.null(RDObject)) {
    message("No usable connection object. Live harvesting will fail, but we will still record what we can.")
  }

  results <- list()
  report_lines <- c(
    "LSEG Real Field Harvest Report",
    paste("Timestamp:", Sys.time()),
    paste("Ticker used:", TICKER),
    ""
  )

  # 1. Estimates - very rich structured content
  message("\n=== Harvesting Estimates views ===")
  estimate_views <- c(
    "view-summary/annual",
    "view-summary/interim",
    "view-summary/recommendations",
    "view-actuals/annual",
    "view-actuals/interim"
  )
  packages <- c("basic", "standard")

  est_fields <- data.table()

  for (v in estimate_views) {
    for (pkg in packages) {
      label <- paste0("Estimates:", v, " (", pkg, ")")
      res <- tryCatch({
        df <- rd_GetEstimates(
          RDObject = RDObject,
          universe = TICKER,
          view = v,
          package = pkg,
          use_field_names_in_headers = FALSE,
          raw_output = FALSE
        )
        list(success = TRUE, data = df)
      }, error = function(e) list(success = FALSE, error = conditionMessage(e)))

      if (isTRUE(res$success) && is.data.frame(res$data) && ncol(res$data) > 0) {
        cols <- names(res$data)
        message("  OK ", label, " -> ", length(cols), " columns")
        tmp <- data.table(
          field = cols,
          description = NA_character_,
          category = "Estimates",
          parameters = "",
          notes = paste("Live from rd_GetEstimates view=", v, " package=", pkg),
          source = "live-refinitivr"
        )
        est_fields <- rbind(est_fields, tmp, fill = TRUE)
      } else {
        msg <- if (!isTRUE(res$success)) res$error else "no columns returned"
        message("  FAIL ", label, " : ", msg)
        report_lines <- c(report_lines, paste(label, "->", msg))
      }
    }
  }

  if (nrow(est_fields) > 0) {
    est_fields <- unique(est_fields, by = "field")
    fwrite(est_fields, "real_fields_estimates.csv")
    message("Wrote real_fields_estimates.csv (", nrow(est_fields), " fields)")
    results$estimates <- est_fields
  }

  # 2. ESG
  message("\n=== Harvesting ESG views ===")
  esg_views <- c("scores-full", "scores-standard", "measures-full", "measures-standard", "basic")

  esg_fields <- data.table()

  for (v in esg_views) {
    label <- paste0("ESG:", v)
    res <- tryCatch({
      df <- rd_GetESG(
        RDObject = RDObject,
        universe = TICKER,
        view = v,
        use_field_names_in_headers = FALSE,
        raw_output = FALSE
      )
      list(success = TRUE, data = df)
    }, error = function(e) list(success = FALSE, error = conditionMessage(e)))

    if (isTRUE(res$success) && is.data.frame(res$data) && ncol(res$data) > 0) {
      cols <- names(res$data)
      message("  OK ", label, " -> ", length(cols), " columns")
      tmp <- data.table(
        field = cols,
        description = NA_character_,
        category = "ESG",
        parameters = "",
        notes = paste("Live from rd_GetESG view=", v),
        source = "live-refinitivr"
      )
      esg_fields <- rbind(esg_fields, tmp, fill = TRUE)
    } else {
      msg <- if (!isTRUE(res$success)) res$error else "no columns"
      message("  FAIL ", label, " : ", msg)
    }
  }

  if (nrow(esg_fields) > 0) {
    esg_fields <- unique(esg_fields, by = "field")
    fwrite(esg_fields, "real_fields_esg.csv")
    message("Wrote real_fields_esg.csv (", nrow(esg_fields), " fields)")
    results$esg <- esg_fields
  }

  # 3. General / Pricing via rd_GetData
  message("\n=== Harvesting general fields via rd_GetData ===")
  seed_fields <- c(
    "TR.PriceClose", "TR.PriceOpen", "TR.HighPrice", "TR.LowPrice",
    "TR.Volume", "TR.Turnover", "TR.Bid", "TR.Ask",
    "TR.CompanyName", "TR.RIC", "TR.PrimaryInstrument",
    "TR.CompanyMarketCap", "TR.IssueMarketCap", "TR.FreeFloatPct",
    "TR.Revenue", "TR.GrossProfit", "TR.EBITDA", "TR.EPS",
    "TR.PE", "TR.DividendYield"
  )

  gen_fields <- data.table()

  res <- tryCatch({
    df <- rd_GetData(
      RDObject = RDObject,
      rics = TICKER,
      fields = seed_fields,
      use_field_names_in_headers = FALSE
    )
    list(success = TRUE, data = df)
  }, error = function(e) list(success = FALSE, error = conditionMessage(e)))

  if (isTRUE(res$success) && is.data.frame(res$data) && ncol(res$data) > 0) {
    cols <- names(res$data)
    message("  OK general -> ", length(cols), " columns returned")
    tmp <- data.table(
      field = cols,
      description = NA_character_,
      category = "Pricing/Reference/Fundamentals",
      parameters = "",
      notes = "Live from rd_GetData on seed list (use_field_names_in_headers=FALSE)",
      source = "live-refinitivr"
    )
    gen_fields <- rbind(gen_fields, tmp, fill = TRUE)
  } else {
    message("  General call failed or returned nothing: ", if (!isTRUE(res$success)) res$error else "empty")
  }

  # Also capture a titled version for reference / descriptions
  res_titles <- tryCatch({
    df <- rd_GetData(RDObject = RDObject, rics = TICKER, fields = seed_fields[1:8], use_field_names_in_headers = TRUE)
    list(success = TRUE, data = df)
  }, error = function(e) list(success = FALSE))

  if (isTRUE(res_titles$success) && is.data.frame(res_titles$data)) {
    message("  Also captured titled version (", ncol(res_titles$data), " cols) for future enrichment.")
  }

  if (nrow(gen_fields) > 0) {
    gen_fields <- unique(gen_fields, by = "field")
    fwrite(gen_fields, "real_fields_general.csv")
    message("Wrote real_fields_general.csv (", nrow(gen_fields), " fields)")
    results$general <- gen_fields
  }

  # --- Combine & report ------------------------------------------------------
  combined <- rbindlist(results, fill = TRUE, use.names = TRUE)
  if (nrow(combined) > 0) {
    combined <- unique(combined, by = c("field", "category"))
    fwrite(combined, "real_fields_combined.csv")
    message("\nWrote real_fields_combined.csv with ", nrow(combined), " unique fields")
  }

  report_lines <- c(
    report_lines,
    "",
    "Fields harvested per category:",
    if (!is.null(results$estimates)) paste("  Estimates:", nrow(results$estimates)),
    if (!is.null(results$esg)) paste("  ESG:", nrow(results$esg)),
    if (!is.null(results$general)) paste("  General:", nrow(results$general)),
    "",
    "Combined file: real_fields_combined.csv",
    "You can now use these with the Python harvester or set LSEG_DATA_DICTIONARY_PATH."
  )

  writeLines(report_lines, "real_fields_report.txt")
  message("Report written to real_fields_report.txt")

  invisible(combined)
}

# Run when sourced or executed
if (!interactive() || identical(environment(), globalenv())) {
  tryCatch(
    harvest_real_fields(),
    error = function(e) {
      message("\n=== Harvest failed ===")
      message(conditionMessage(e))
      message("\nCommon causes:")
      message("  - LSEG Workspace is not running / not logged in")
      message("  - RefinitivR package not installed or not loadable")
      message("  - No desktop session available to this R process")
      message("\nYou can still run the script on your normal development machine where Workspace is active.")
    }
  )
}
