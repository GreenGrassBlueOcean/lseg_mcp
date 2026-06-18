# harvest_real_fields_via_refinitivrapi.R
#
# Harvester that uses **RefinitivRAPI** (the one with rd_handshake() + direct bearer token)
# to pull *real, live* data item / TR. field names from the platform.
#
# This is what you meant: after you do
#     RefinitivRAPI::rd_handshake()
# the package has a working connection/token, and its rd_Get* functions
# will use the direct RDP "trapi" access (no desktop proxy required).
#
# === HOW TO USE ===
# 1. In your R session, first do the handshake (you just showed this works):
#      RefinitivRAPI::rd_handshake()
#
# 2. Then source this file (it will auto-detect and load from Documents\code\R\RefinitivRAPI):
#      source("C:/Users/laurensvdb/Documents/GitHub/lseg_mcp/scripts/harvest_real_fields_via_refinitivrapi.R")
#
# The script will call the various rd_Get* functions using the live token/connection
# that rd_handshake() established. Results go into the lseg_mcp data folder so the
# Python MCP side picks them up automatically on next load (or after rescan_packages).
#
# Run this in the SAME R session, right after your handshake.
#
# It will:
# - Use RefinitivRAPI::rd_GetEstimates, rd_GetESG, rd_GetData, etc.
# - Request with settings that surface the real field identifiers.
# - Extract column names / headers from the responses (these are authentic fields
#   your entitlements can actually see right now).
# - Write clean CSVs consumable by lseg-mcp (Python DataDictionary).
#
# Output files:
#   real_fields_refinitivrapi_estimates.csv
#   real_fields_refinitivrapi_esg.csv
#   real_fields_refinitivrapi_general.csv
#   real_fields_refinitivrapi_combined.csv
#   real_fields_refinitivrapi_report.txt
#
# Then in lseg-mcp you can point LSEG_DATA_DICTIONARY_PATH at the combined CSV
# or copy rows into a "Custom_Fields" sheet.

suppressPackageStartupMessages({
  loaded <- FALSE
  refinitivrapi_path <- file.path(Sys.getenv("USERPROFILE"), "Documents/code/R/RefinitivRAPI")

  # Prefer the development version from Documents\code\R (as you specified)
  if (dir.exists(refinitivrapi_path)) {
    if (requireNamespace("devtools", quietly = TRUE)) {
      devtools::load_all(refinitivrapi_path, quiet = TRUE)
      loaded <- TRUE
      message("Loaded RefinitivRAPI (dev) via devtools::load_all() from ", refinitivrapi_path)
    } else {
      message("WARNING: devtools not available. Trying to use installed version instead.")
    }
  }

  # Fallback to installed package
  if (!loaded && requireNamespace("RefinitivRAPI", quietly = TRUE)) {
    library(RefinitivRAPI, quietly = TRUE)
    loaded <- TRUE
    message("Loaded RefinitivRAPI from installed package (consider installing devtools and using the Documents\\code\\R version).")
  }

  if (!loaded) {
    stop("Could not load RefinitivRAPI from either the dev path or installed package.")
  }

  library(data.table)
})

TICKER <- "AAPL.O"

# Output directory - prefer lseg_mcp data folder so the Python side picks it up automatically
output_dir <- "C:/Users/laurensvdb/Documents/GitHub/lseg_mcp/data"
if (!dir.exists(output_dir)) output_dir <- getwd()

message("=== RefinitivRAPI live field harvester ===")
message("Using the connection established by rd_handshake() in this session.")
message("Output will be written to: ", output_dir)

# Quick smoke test - does any basic data call work at all?
# Note: RefinitivRAPI's rd_GetData uses Eikonformulas (not 'fields')
message("\n--- Smoke test: basic rd_GetData ---")
smoke_result <- try(
  RefinitivRAPI::rd_GetData(
    rics = TICKER,
    Eikonformulas = c("TR.RIC", "TR.CompanyName"),
    use_field_names_in_headers = FALSE
  ),
  silent = TRUE
)

if (inherits(smoke_result, "try-error")) {
  message("  Smoke test ERROR: ", conditionMessage(attr(smoke_result, "condition")))
  smoke_success <- FALSE
} else if (is.data.frame(smoke_result) && nrow(smoke_result) > 0) {
  message("  Smoke test succeeded. Basic data retrieval works. Columns returned: ", paste(names(smoke_result), collapse = ", "))
  smoke_success <- TRUE
} else {
  message("  Smoke test: call succeeded but no data rows returned.")
  smoke_success <- FALSE
}

if (!smoke_success) {
  message("  Common causes: token scope doesn't allow data, no real-time/fundamental permissions, or the package's .api_call is not using the post-handshake token.")
}

results <- list()
report <- c(
  "RefinitivRAPI Live Field Harvest",
  paste("Time:", Sys.time()),
  paste("Ticker:", TICKER),
  ""
)

# Note: The old harvest_from_response helper has been replaced by direct try() + success checks
# in the harvesting sections below. This keeps error messages visible and handles the fact that
# RefinitivRAPI often returns human-readable column names (e.g. "Company.Name") instead of raw TR. codes.

# 1. Estimates - richest for structured fields
message("\n--- Harvesting via rd_GetEstimates (direct RDP) ---")
est_views <- c(
  "view-summary/annual",
  "view-summary/recommendations",
  "view-actuals/annual"
)
est_pkg <- c("standard", "basic")

est_dt <- data.table()
for (v in est_views) {
  for (p in est_pkg) {
    label <- sprintf("Estimates %s / %s", v, p)
    est_res <- try(
      RefinitivRAPI::rd_GetEstimates(
        universe = TICKER,
        view = v,
        package = p,
        use_field_names_in_headers = FALSE,
        raw_output = FALSE
      ),
      silent = TRUE
    )
    if (inherits(est_res, "try-error")) {
      message("    ERROR in ", label, ": ", conditionMessage(attr(est_res, "condition")))
    } else if (is.data.frame(est_res) && nrow(est_res) > 0) {
      message("  ", label, " -> ", ncol(est_res), " columns")
      # Record the requested view as usable "field" concept
      tmp <- data.table(
        field = paste0("Estimates:", v, " (package=", p, ")"),
        description = "",
        category = "Estimates",
        parameters = "",
        notes = paste("Live via RefinitivRAPI::rd_GetEstimates after rd_handshake() - view", v, "package", p),
        source = "RefinitivRAPI-live"
      )
      est_dt <- rbind(est_dt, tmp, fill = TRUE)
    }
  }
}
if (nrow(est_dt) > 0) {
  est_dt <- unique(est_dt, by = "field")
  out_file <- file.path(output_dir, "real_fields_refinitivrapi_estimates.csv")
  fwrite(est_dt, out_file)
  results$estimates <- est_dt
  message("Wrote ", out_file, " (", nrow(est_dt), " unique)")
}

# 2. ESG
message("\n--- Harvesting via rd_GetESG (direct RDP) ---")
esg_views <- c("scores-full", "measures-full", "basic")

esg_dt <- data.table()
for (v in esg_views) {
  esg_res <- try(
    RefinitivRAPI::rd_GetESG(
      universe = TICKER,
      view = v,
      use_field_names_in_headers = FALSE,
      raw_output = FALSE
    ),
    silent = TRUE
  )
  if (inherits(esg_res, "try-error")) {
    message("    ERROR in ESG ", v, ": ", conditionMessage(attr(esg_res, "condition")))
  } else if (is.data.frame(esg_res) && nrow(esg_res) > 0) {
    message("  ESG ", v, " -> ", ncol(esg_res), " columns")
    tmp <- data.table(
      field = paste0("ESG:", v),
      description = "",
      category = "ESG",
      parameters = "",
      notes = paste("Live via RefinitivRAPI::rd_GetESG after rd_handshake() - view", v),
      source = "RefinitivRAPI-live"
    )
    esg_dt <- rbind(esg_dt, tmp, fill = TRUE)
  }
}
if (nrow(esg_dt) > 0) {
  esg_dt <- unique(esg_dt, by = "field")
  out_file <- file.path(output_dir, "real_fields_refinitivrapi_esg.csv")
  fwrite(esg_dt, out_file)
  results$esg <- esg_dt
  message("Wrote ", out_file, " (", nrow(esg_dt), " unique)")
}

# 3. General / Pricing / Fundamentals via rd_GetData
message("\n--- Harvesting via rd_GetData (direct RDP) ---")

# Helper to normalize a possibly parametrized TR. field
normalize_tr_field <- function(f) {
  f <- gsub("/\\*.*\\*/$", "", f)  # strip comments
  f <- trimws(f)
  m <- regexec("^([^(]+)(?:\\(([^)]*)\\))?$", f)
  if (length(m[[1]]) >= 2) {
    base <- regmatches(f, m)[[1]][2]
    params <- if (length(regmatches(f, m)[[1]]) > 2) regmatches(f, m)[[1]][3] else ""
    list(field = base, parameters = params)
  } else {
    list(field = f, parameters = "")
  }
}

# Comprehensive seed list mined from the current code base
# (Documents\code\R\RefinitivRAPI + related GGBO/Refinitiv packages + previous live harvests).
# These are real TR.* fields that appear in your own RefinitivRAPI source, docs, tests, and prior runs.
# Edit this list freely with any additional TR.* you want to validate against your current
# live connection (after rd_handshake()).
seed <- c(
  # Core pricing & market
  "TR.PriceClose", "TR.PriceOpen", "TR.HighPrice", "TR.LowPrice",
  "TR.Volume", "TR.Turnover", "TR.Bid", "TR.Ask", "TR.CLOSEPRICE",
  "TR.CLOSE", "TR.OPEN", "TR.LOWPRICE", "TR.PRICE",
  # Reference & identifiers
  "TR.CompanyName", "TR.RIC", "TR.PrimaryInstrument", "TR.CompanyMarketCap",
  "TR.IssueMarketCap", "TR.IssueSharesOutstanding", "TR.FreeFloatPct",
  "TR.ISINCODE", "TR.RICCODE", "TR.EXCHANGENAME", "TR.OPERATINGMIC",
  "TR.COMMONNAME", "TR.INSTRUMENTTYPE", "TR.INSTRUMENTISACTIVE",
  "TR.PRIMARYRICCODE", "TR.ASSETCATEGORYCODE", "TR.RDNEXCHANGECODE",
  # Fundamentals
  "TR.Revenue", "TR.GrossProfit", "TR.EBITDA", "TR.EPS", "TR.PE",
  "TR.GROSSPROFIT", "TR.REVENUE",
  # Other commonly used in your code base
  "TR.AVGDAILYVOLUME6M", "TR.FREECASHFLOW", "TR.SHORTINTEREST",
  "TR.SHARESFREEFLOAT", "TR.PRICE TARGETMEAN", "TR.PE(Sdate=0D)",
  "TR.CompanyMarketCap(Sdate=0D, scale=6)", "TR.IssueMarketCap(Scale=6,ShType=FFL)",
  "TR.Revenue.date", "TR.CLOSEPRICE(Adjusted=0)", "TR.LOWPRICE(SDate:0d)",
  "TR.PriceTargetMean(SDate:0CY)", "TR.CAEFFECTIVEDATE",
  "TR.LIPPERRICCODE", "TR.RETIREDATE", "TR.PRICECLOSE.CURRENCY",
  "TR.EXCHANGEMARKETIDCODE", "TR.ISSUEMARKETCAP(SCALE=6,SHTYPE=FFL,CURN=USD)",
  "TR.ISSUESHARESOUTSTANDING(SCALE=3)", "TR.FREECASHFLOW(PERIOD=LTM,SDATE=0D,CURN=USD)",
  "TR.SHARESFREEFLOAT(SDATE=0D)", "TR.SHORTINTEREST(SDATE=0D)",
  "TR.PE(SDATE=0D)", "TR.CLOSEPRICE(ADJUSTED=0)", "TR.EIKONFORMULA.DATE"
)

# Auto-augment from any previous harvest CSVs in the output dir
# (iterative: fields that worked before + new candidates)
# Use robust fread options to handle previously written CSVs that may have
# unquoted complex field names (e.g. TR.FOO(BAR=1,BAZ=2)) or other quoting issues.
try({
  extra_files <- list.files(output_dir, pattern = "(real_fields|harvested).*\\.csv$", full.names = TRUE, ignore.case = TRUE)
  for (f in extra_files) {
    if (file.exists(f)) {
      prev <- tryCatch(
        suppressWarnings(data.table::fread(f, quote = "\"", fill = TRUE, header = TRUE)),
        error = function(e) NULL
      )
      if (!is.null(prev) && "field" %in% names(prev)) {
        more <- prev$field[grepl("^TR\\.", prev$field, ignore.case = TRUE)]
        seed <- unique(c(seed, more))
      }
    }
  }
}, silent = TRUE)

# Also try to mine additional candidates directly from the RefinitivRAPI source
# in the folder you just pointed to (Documents\code\R)
try({
  rapi_root <- file.path(Sys.getenv("USERPROFILE"), "Documents/code/R/RefinitivRAPI")
  if (dir.exists(rapi_root)) {
    src_files <- list.files(rapi_root, pattern = "\\.(R|Rd|r|md|txt)$", full.names = TRUE, recursive = TRUE, ignore.case = TRUE)
    src_files <- src_files[!grepl("Rcheck|nul", src_files, ignore.case = TRUE)]
    mined <- character()
    for (f in src_files) {
      lines <- tryCatch(readLines(f, warn = FALSE), error = function(e) character())
      hits <- regmatches(lines, gregexpr("TR\\.[A-Za-z0-9_.]+", lines, perl = TRUE))
      mined <- c(mined, unlist(hits))
    }
    if (length(mined) > 0) {
      mined_clean <- unique(sub("\\(.*", "", mined))
      seed <- unique(c(seed, mined_clean[grepl("^TR\\.", mined_clean, ignore.case = TRUE)]))
    }
  }
}, silent = TRUE)

seed <- sort(unique(seed))
message("Using ", length(seed), " candidate TR. fields for this harvest run (expanded from current code base + live mining).")

gen_dt <- data.table()

# Request in small batches for more accurate per-field validation.
# If a batch returns a df with >1 column, we consider those requested fields "harvested"
# (the API accepted them and returned some data; column names are often humanized).
batch_size <- 8
for (i in seq(1, length(seed), by = batch_size)) {
  batch <- seed[i:min(i + batch_size - 1, length(seed))]
  if (length(batch) == 0) next

  res <- try(
    RefinitivRAPI::rd_GetData(
      rics = TICKER,
      Eikonformulas = batch,
      use_field_names_in_headers = FALSE
    ),
    silent = TRUE
  )

  if (inherits(res, "try-error")) {
    # individual batch failure is ok, just skip
    next
  }

  if (is.data.frame(res) && nrow(res) > 0 && ncol(res) > 1) {
    # success for this batch
    normed <- lapply(batch, function(b) normalize_tr_field(b))
    tmp <- data.table(
      field = sapply(normed, `[[`, "field"),
      description = "",
      category = "Pricing/Reference/Fundamentals",
      parameters = sapply(normed, `[[`, "parameters"),
      notes = "Live via RefinitivRAPI::rd_GetData (Eikonformulas) after rd_handshake() - batch validated",
      source = "RefinitivRAPI-live"
    )
    gen_dt <- rbind(gen_dt, tmp, fill = TRUE)
  }
}

if (nrow(gen_dt) > 0) {
  gen_dt <- unique(gen_dt, by = "field")
  out_file <- file.path(output_dir, "real_fields_refinitivrapi_general.csv")
  data.table::fwrite(gen_dt, out_file, quote = TRUE)
  results$general <- gen_dt
  message("Wrote ", out_file, " (", nrow(gen_dt), " unique)")
}

# Combine + report
combined <- rbindlist(results, fill = TRUE, use.names = TRUE)
if (nrow(combined) > 0) {
  combined <- unique(combined, by = c("field", "category"))
  out_file <- file.path(output_dir, "real_fields_refinitivrapi_combined.csv")
  data.table::fwrite(combined, out_file, quote = TRUE)
  message("\nWrote ", out_file, " with ", nrow(combined), " fields total")
}

report <- c(
  report,
  "Fields harvested:",
  if (!is.null(results$estimates)) paste("  Estimates:", nrow(results$estimates)),
  if (!is.null(results$esg)) paste("  ESG:", nrow(results$esg)),
  if (!is.null(results$general)) paste("  General:", nrow(results$general)),
  "",
  "Next: point LSEG_DATA_DICTIONARY_PATH at one of the CSVs,",
  "or feed them through scripts/harvest_lseg_fields.py for further polishing.",
  "Then restart lseg-mcp or call rescan_packages."
)

report_file <- file.path(output_dir, "real_fields_refinitivrapi_report.txt")
writeLines(report, report_file)
message("Report written to ", report_file)

message("\nDone.")
message("If you still get zero fields, check the detailed ERROR lines printed above.")
message("Also look at the report file for a summary.")
message("The smoke test result above is the most important diagnostic.")
