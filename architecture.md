# LSEG-MCP Server Technical Architecture

## 1. System Overview

`lseg-mcp` is an asynchronous, introspective Model Context Protocol (MCP) server built in Python 3.11+ using the official `FastMCP` framework. It acts as a definitive, hallucination-free bridge between LLMs and the London Stock Exchange Group (LSEG) data APIs.

It is designed to remain constantly synchronized with the underlying Python ([`lseg-data`](https://pypi.org/project/lseg-data/)) and R ([`RefinitivR`](https://github.com/GreenGrassBlueOcean/RefinitivR)) packages via live AST parsing, enabling AI agents to draft perfectly formatted data retrieval pipelines.

The server fulfills three critical objectives:

1. **Financial Ontology Mapping**: Ingests the official *LSEG Financials vs LSEG Company Fundamentals* mapping matrix, enabling precise translation of legacy Refinitiv COA codes to industry-specific modern LSEG FCC formulas — including edge cases like additive arrays (`SOLL+SLAP+SCAL+SDIL+SRLN`), ASR bracket notation (`[AFUL]`), and `COA+Primary Instrument` concatenations.
2. **Polyglot Code Generation**: Assists agents in drafting syntactically correct boilerplate in both Python (`lseg-data`) and R (`RefinitivR`) by merging mapping-aware field resolution with live, AST-verified function signatures.
3. **Self-Healing Synchronization**: Automatically pulls the latest upstream code (`git pull` / `pip install --upgrade`) and rebuilds its internal index, returning a diff of modified functions to the LLM.

The server operates over standard input/output (stdio) using the JSON-RPC 2.0 protocol.

---

## 2. Core Components

### 2.1 Semantic Mapping Engine (`mapping_engine.py`)

Ingests the multi-header `LSEG_Mapping.xlsx` workbook into an in-memory Pandas DataFrame with schema-aware column assignment. Parses the "Explanations", "Standardized Financials", "Segments", and "Aggregates" sheets.

- **Industry & Statement Routing**: Queries are automatically filtered by target sector (Industrial, Bank, Insurance, Property, Financial, Investment Trust) and financial statement type (Income Statement, Balance Sheet, Cash Flow).
- **Fuzzy Search**: Text search across COA codes, descriptions, labels, Office Fields, and all six FCC industry columns. Evaluated natively without regex injections to prevent ReDoS on formulas like `SOLL+SLAP`.
- **Enrichment Pipeline**: Every search result is enriched via `_enrich()` with computed metadata:
  - `_target_fcc`: The resolved LSEG formula dynamically assigned based on the requested industry.
  - `_additive`: Additive formulas detected from `+` operators (e.g., `SOLL+SLAP`).
  - `_asr_flagged` / `_asr_code`: Bracket notation for As-Reported layer fields (e.g., `[AFUL]`).
  - `_notes`: "No FCC Match" interception, Primary Instrument detection, Instrument ID requirements, and multiple-to-one mapping detection (e.g., `SNTU/SHRV/SNTS`).
- **Formula Validation**: The `validate_formula()` method cross-references drafted FCC/COA fields against the matrix, producing per-field status (`OK`, `NOT_FOUND`, `NOT_COMPARABLE`) with actionable warnings.

### 2.2 Polyglot Codebase Introspector (`package_indexer.py`)

Performs static AST analysis of the source code without executing potentially unsafe or network-blocking code, preventing the LLM from hallucinating deprecated arguments.

- **Python Indexer (`PythonPackageIndex`)**: Uses `importlib.util.find_spec()` for zero-import package location, then traverses module-level `.py` files using `tree.body` iteration (avoiding `ast.walk` hallucinations of nested closures). Extracts public function signatures utilizing `ast.unparse` to preserve complex type hints (`list[str]`), `*args`, and `**kwargs`. Skips `_private` symbols.
- **R Indexer (`RPackageIndex`)**: Parses `.R` files using a robust parenthesis-balancing algorithm to accurately extract multi-line function definitions (e.g., `function_name <- function(\n args \n)`), completely replacing fragile regex. Reads the `NAMESPACE` file to determine export status and parses `.Rd` files for Roxygen documentation.
- **JIT Cache & Fingerprinting**: Generates an `md5` hash of `{filepath}:{mtime}` tuples across the entire package directory. Subsequent calls return the cached index in sub-millisecond time unless the fingerprint has changed.
- **Unified Facade (`PackageIndexer`)**: Provides a single entry point for `get_signature(language, function)`, `get_exports(language)`, and `reindex(language)` across both languages.

### 2.3 Code Generator (`code_generator.py`)

Template-based generator that merges mapping-aware field resolution with live signature validation to produce boilerplate code.

- **Python Output**: Generates `import lseg.data as ld` → `ld.open_session()` → `ld.get_data(universe, fields)` → `ld.close_session()` pipelines. Additive formulas are omitted from the main `fields` array and decomposed into separate `get_data()` calls with `df_components.sum(axis=1)` post-processing to prevent backend crashes.
- **R Output**: Generates `library(Refinitiv)` → `rd_GetData()` pipelines. Dynamically extracts argument names from the AST (e.g., mapping arrays to `Eikonformulas` vs `fields`) to prevent unused argument errors. Additive formulas use list-based assignment `result[['col']] <- rowSums(...)` for robust syntactical safety.
- **Mapping Note Injection**: Both generators embed `# NOTE:` comments from enrichment metadata directly into the output code.

### 2.4 Rescan & Update Manager (`rescan_manager.py`)

Handles the continuous integration aspect of the server via asynchronous OS-level subprocess execution.

- **R Package**: Orchestrates `git pull --rebase` on the RefinitivR repository. If the repo does not exist locally, performs `git clone` from [`https://github.com/GreenGrassBlueOcean/RefinitivR.git`](https://github.com/GreenGrassBlueOcean/RefinitivR.git) into the project-local `.lseg_cache/` directory.
- **Python Package**: Runs `pip install --upgrade lseg-data` safely executing `[sys.executable, "-m", "pip"]` to prevent cross-platform virtual environment escaping.
- **Timeout Protection**: All subprocess commands are wrapped with `asyncio.wait_for(timeout=120)` to prevent indefinite hangs.
- **FileNotFoundError Resilience**: Gracefully handles missing `git` or `pip` binaries with clean error messages.
- **Diff Summary**: The `rescan()` method snapshots function counts before and after the update, then reports `{"python": {"before": N, "after": M, "delta": D}, "r": {...}}`.

### 2.5 MCP Gateway (`server.py`)

The FastMCP JSON-RPC communication layer operating over stdio.

- **Headless Observability**: Redirects stray `print()` or warnings from underlying libraries (pandas, openpyxl, gitpython) to stderr to protect the JSON-RPC pipeline. A hardened `FlushingFileHandler` utilizing `os.fsync()` guarantees cross-platform real-time log streaming without OS-level chunking delays.
- **Lazy Singleton Initialization**: Heavy engines (`MappingEngine`, `PackageIndexer`, `RescanManager`) are initialized lazily on first tool call, minimizing MCP startup latency.
- **Environment Variable Overrides**: All paths are overridable via `LSEG_MAPPING_PATH` and `REFINITIVR_PATH` environment variables, falling back to project-relative defaults for out-of-the-box usage.
- **Defensive Error Handling**: Every tool wraps its body in `try/except`, returning clean markdown error messages rather than propagating Python exceptions into the JSON-RPC pipe.

---

## 3. MCP Tools & Resources

### 3.1 Tools (6)

| Tool | Description |
|------|-------------|
| `search_financial_mapping` | Fuzzy-searches the mapping matrix by query, industry, and statement. Returns legacy COA codes, exact target FCCs, polarity, and enrichment notes (additive formulas, ASR flags, No FCC Match). |
| `get_mapping_rules` | Retrieves overarching mapping definitions: 3 comparability categories (Identical / Comparable / Not Comparable), special-case rules, and cash-flow / balance-sheet format notes. |
| `get_package_signature` | Fetches the live, exact usage signature and docstring for a function in `python` or `r` from the AST index. |
| `validate_lseg_formula` | Cross-references drafted FCC/COA fields against the matrix. Returns per-field status (`OK`, `NOT_FOUND`, `NOT_COMPARABLE`) with actionable warnings for Primary Instrument, ASR, and additive formula requirements. |
| `draft_api_call` | Merges mapping rules and AST signatures to return syntactically correct, ready-to-run code boilerplate in Python or R. |
| `rescan_packages` | Triggers an update check (`git pull` / `pip install --upgrade`), flushing caches and rebuilding the index. Returns a diff summary. |

### 3.2 Resources (3)

| URI | Description |
|-----|-------------|
| `matrix://financials_to_fundamentals` | Read-only Markdown rendering of global mapping rules, comparability categories, special cases, and explanatory text. |
| `pkg://lseg-data/exports` | Live hierarchical JSON view of all Python functions exported by the current version of `lseg-data`. |
| `pkg://RefinitivR/exports` | Live hierarchical JSON view of all R functions exported by the current commit of `RefinitivR`. |

---

## 4. Key Design Decisions

### 4.1 Environment-Agnostic Paths
All file paths are resolved relative to the project root (`Path(__file__).resolve().parents[2]`). No hardcoded local paths exist. The mapping Excel file defaults to `data/LSEG_Mapping.xlsx` and the R repository cache to `.lseg_cache/RefinitivR/`, both overridable via environment variables. This enables out-of-the-box cloning and usage on any machine.

### 4.2 Automatic Git Cloning
If the RefinitivR repository is not present locally, the `RescanManager` automatically clones it from GitHub on first `rescan_packages()` call. This eliminates manual setup steps for new deployments.

### 4.3 Static Analysis Only
Both the Python and R indexers operate purely via static analysis (AST / regex). No source code is ever executed, preventing import side effects, network calls, or unsafe code execution.

### 4.4 Schema-Aware Multi-Header Parsing
The LSEG mapping Excel has a complex multi-header layout. The engine explicitly skips the first 3 header rows, assigns canonical column names, forward-fills section headers, and drops separator columns — ensuring robust parsing regardless of minor formatting changes.

### 4.5 Enterprise Resilience & CI/CD
Following a rigorous audit, the architecture incorporates enterprise-grade protections against common MCP vulnerabilities:
- **Asynchronous Stdio Isolation**: Long-running background operations (e.g., `git clone`, `pip install`) are aggressively offloaded to dedicated `asyncio` task pools. This guarantees the JSON-RPC event loop on `sys.stdin` is never starved, entirely preventing client-side timeouts during cold starts or heavy network ops.
- **Cross-Platform Launch Integrity**: Shell wrapper scripts (`run_server.sh` and `run_server.cmd`) are strictly bound by `.gitattributes` to enforce correct OS-level line endings (LF vs CRLF). 
- **Automated CI/CD Validation**: A multi-platform GitHub Actions workflow rigorously tests the launch scripts on Windows, macOS, and Linux runners. It uses advanced non-blocking `subprocess.Popen` orchestration to verify that standard I/O pipes properly remain open and prevent premature EOF closures across all environments.
- **O(1) Batch Queries**: The semantic search engine supports batched query lists natively, reducing the roundtrip latency between the LLM and the MCP server.

---

## 5. End-to-End Workflow

1. **User Prompt**: "Write an R script to get Diluted EPS and Total Debt for Apple (Industrial) and JP Morgan (Bank)."
2. **LLM Execution**:
   - Calls `search_financial_mapping` for "Diluted EPS" — receives industry-specific FCC splits and additive formula detection.
   - Calls `search_financial_mapping` for "Total Debt" — notices the "No FCC Match" warning for certain industries.
   - Calls `get_package_signature` for `language="r", function="get_data"` — receives the exact parameters from the local (or auto-cloned) RefinitivR index.
   - Calls `validate_lseg_formula` to verify all drafted fields are valid before code generation.
3. **Code Generation**: Calls `draft_api_call` — receives correct R boilerplate with industry FCC splits, additive formula decomposition, and validated function signatures.
4. **Rescan (Optional)**: If a function is missing, calls `rescan_packages()` to pull the latest Git commit and refresh the index with a diff summary.

---

## 6. File Map

| File | Lines | Purpose |
|------|-------|---------|
| `pyproject.toml` | 25 | Packaging via `hatchling`. Dependencies: `mcp`, `fastmcp`, `pandas>=2.1,<2.3`, `gitpython`, `openpyxl`. |
| `run_server.cmd` | — | Windows launcher script. |
| `src/lseg_mcp/__init__.py` | 2 | Package marker. |
| `src/lseg_mcp/server.py` | 434 | FastMCP gateway — 6 tools, 3 resources, lazy singletons, `os.fsync` cross-platform streaming. |
| `src/lseg_mcp/mapping_engine.py` | 380 | Semantic mapping engine: multi-header Excel parser, fuzzy search, enrichment pipeline, formula validation. |
| `src/lseg_mcp/package_indexer.py` | 413 | Polyglot AST introspector: Python (`ast`), R (parenthesis-balancing + NAMESPACE + Rd), JIT fingerprinting. |
| `src/lseg_mcp/code_generator.py` | 205 | Template-based code generation: Python `lseg-data` and R `RefinitivR` boilerplate with dynamic AST arguments. |
| `src/lseg_mcp/rescan_manager.py` | 204 | Async subprocess orchestration: `git pull`/`git clone`, `pip install --upgrade`, stream chunking, diff summary. |

---

## 7. Testing & Quality Assurance

The project is backed by a comprehensive test suite achieving **98% absolute line coverage** (844 statements, 18 missed) across 78 test cases.

| Test File | Tests | Targets |
|-----------|-------|---------|
| `tests/conftest.py` | — | Shared fixtures: mock `pandas.read_excel` with 6-row mapping data, temp Python package with AST-parseable `.py` files, temp R package with NAMESPACE/Rd structure. |
| `tests/test_mapping_engine.py` | 15 | Multi-header parsing, fuzzy search, industry/statement filtering, enrichment (additive, ASR, No FCC, Primary Instrument, Instrument ID, multi-to-one), formula validation, default path fallback, missing sheet resilience. |
| `tests/test_package_indexer.py` | 15 | Python AST parsing (functions, classes, methods, `*args`/`**kwargs`), R bracket-balancing parsing (functions, R6 classes), fingerprint caching. |
| `tests/test_code_generator.py` | 8 | Python and R boilerplate generation, dynamic AST parameter mapping (`Eikonformulas`), `office_field` priority overrides. |
| `tests/test_rescan_manager.py` | 12 | Git pull success/error, git clone for missing repos, pip upgrade, async timeout handling, process cleanup, stream line chunking logic. |
| `tests/test_server.py` | 20 | All 6 tools (success + error paths), all 3 resources, `FileNotFoundError` handling, `main()` entrypoint, lazy singleton initialization. |

**Testing strategy**:
- **Hermetic Mocking**: All file system, subprocess, and pandas I/O operations are fully mocked via `pytest-mock` and `tempfile.TemporaryDirectory`. No network calls, no disk state.
- **Async Support**: `pytest-asyncio` with `asyncio_mode = "auto"` for seamless async tool testing.
- **Coverage Enforcement**: `pytest-cov` configured in `pyproject.toml` with `--cov=src/lseg_mcp --cov-report=term-missing`.

---

## 8. Deployment & MCP Integration

The server binds to standard input/output (stdio) when executed as a module, enabling zero-config integration into MCP clients.

**Configuration Block (`mcp_config.json`):**
```json
{
  "lseg-mcp": {
    "command": "/path/to/lseg_mcp/.venv/bin/python",
    "args": ["-m", "lseg_mcp.server"]
  }
}
```

**Environment Variables (optional):**
| Variable | Default | Purpose |
|----------|---------|---------|
| `LSEG_MAPPING_PATH` | `<project>/data/LSEG_Mapping.xlsx` | Override the mapping Excel file location. |
| `REFINITIVR_PATH` | `<project>/.lseg_cache/RefinitivR` | Override the RefinitivR repository path. |

**Quick Start:**
```bash
git clone https://github.com/GreenGrassBlueOcean/lseg-mcp.git
cd lseg-mcp
pip install -e ".[dev]"
# Windows
run_server.cmd
# macOS/Linux
./run_server.sh
```
