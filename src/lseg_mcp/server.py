"""
LSEG-MCP Server — FastMCP Gateway.

Exposes 6 tools and 3 resources for bridging Refinitiv Financials
to LSEG Company Fundamentals, with live codebase introspection.

Strict stdio fd redirection ensures that stray print() / warnings
from underlying libraries never corrupt the JSON-RPC pipeline.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from lseg_mcp.mapping_engine import MappingEngine
from lseg_mcp.package_indexer import PackageIndexer
from lseg_mcp.rescan_manager import RescanManager
from lseg_mcp import code_generator

# ── Redirect stray stdout to stderr to protect JSON-RPC on stdio ─────
# Any print() or warning from pandas / openpyxl / gitpython will go to
# stderr instead of corrupting the MCP message stream.
_real_stdout = sys.stdout
_real_stderr = sys.stderr
sys.stdout = sys.stderr

logger = logging.getLogger("lseg_mcp")

# ── Configure logging: stderr + file so startup messages are visible ──
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_handler)

# Also log to a file so the user can always review startup progress
_LOG_DIR = Path(__file__).resolve().parents[2] / ".lseg_cache"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
class FlushingFileHandler(logging.FileHandler):
    """FileHandler that flushes to disk immediately so tails (Get-Content -Wait) work."""
    def emit(self, record):
        super().emit(record)
        self.flush()
        # Force OS-level write to disk for aggressive Linux buffers
        try:
            os.fsync(self.stream.fileno())
        except OSError:
            pass  # pragma: no cover

_file_handler = FlushingFileHandler(_LOG_DIR / "startup.log", mode="a", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger.addHandler(_file_handler)
logger.setLevel(logging.INFO)

# ── Resolve paths ────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _find_mapping_file(base_dir: Path) -> Path:
    """Robust cross-platform fallback for case-sensitive Linux file systems."""
    data_dir = base_dir / "data"
    if data_dir.exists():
        for f in data_dir.iterdir():
            if f.name.lower() == "lseg_mapping.xlsx":
                return f
    return base_dir / "data" / "LSEG_Mapping.xlsx"  # pragma: no cover

_DEFAULT_XLSX = _find_mapping_file(_PROJECT_ROOT)
_DEFAULT_R_REPO = _PROJECT_ROOT / ".lseg_cache" / "RefinitivR"

# ── Singletons (initialised lazily on first tool call) ───────────────
_mapping: MappingEngine | None = None
_indexer: PackageIndexer | None = None
_rescan: RescanManager | None = None
_startup_complete = threading.Event()


async def _get_mapping_async() -> MappingEngine:
    global _mapping
    if _mapping is None:
        xlsx_path = os.environ.get("LSEG_MAPPING_PATH", str(_DEFAULT_XLSX))
        _mapping = MappingEngine(xlsx_path)
        # Offload the blocking CPU work to a background thread
        await asyncio.to_thread(_mapping._load)
    return _mapping


def _get_indexer() -> PackageIndexer:
    global _indexer
    if _indexer is None:
        r_repo = os.environ.get("REFINITIVR_PATH", str(_DEFAULT_R_REPO))
        _indexer = PackageIndexer(r_repo_path=r_repo)
    return _indexer


def _get_rescan() -> RescanManager:
    global _rescan
    if _rescan is None:
        r_repo = os.environ.get("REFINITIVR_PATH", str(_DEFAULT_R_REPO))
        _rescan = RescanManager(r_repo_path=r_repo)
    return _rescan


def _needs_index() -> bool:
    """Return True if either index source is missing (cold start).

    Set the environment variable ``LSEG_FORCE_REINDEX=1`` to force
    a full re-index on the next server restart.
    """
    if os.environ.get("LSEG_FORCE_REINDEX", "").strip() == "1":
        return True
    r_repo = os.environ.get("REFINITIVR_PATH", str(_DEFAULT_R_REPO))
    r_missing = not Path(r_repo).joinpath("R").exists()
    try:
        py_missing = importlib.util.find_spec("lseg.data") is None
    except (ModuleNotFoundError, ValueError):
        py_missing = True
    return r_missing or py_missing


async def _auto_index_on_startup() -> None:
    """Run a full rescan on first launch if indexes are cold."""
    try:
        if not _needs_index():
            return

        logger.info("[STARTUP] First-run detected -- populating AST indexes...")

        rescan = _get_rescan()
        indexer = _get_indexer()

        # Update R package
        r_repo = Path(rescan.r_repo_path)
        if not r_repo.joinpath("R").exists():
            logger.info("  [CLONE] Indexing RefinitivR -- cloning from GitHub...")
            r_result = await rescan.update_r_package()
            logger.info("  [OK] RefinitivR: %s", r_result.get("status", "unknown"))
        else:
            logger.info("  [OK] RefinitivR already present")

        # Update Python package
        try:
            py_installed = importlib.util.find_spec("lseg.data") is not None
        except (ModuleNotFoundError, ValueError):
            py_installed = False
        if not py_installed:
            logger.info("  [PIP] Indexing lseg-data -- installing via pip...")
            py_result = await rescan.update_python_package()
            if py_result.get("status") == "error":
                logger.error("  [FAIL] pip install failed: %s", py_result.get("message"))  # pragma: no cover
            logger.info("  [OK] lseg-data: %s", py_result.get("status", "unknown"))
        else:
            logger.info("  [OK] lseg-data already installed")  # pragma: no cover

        # Build indexes
        logger.info("  [INDEX] Building AST indexes...")
        reindex_result = indexer.reindex()
        py_count = reindex_result.get("python", {}).get("count", 0)
        r_count = reindex_result.get("r", {}).get("count", 0)
        logger.info("  [OK] Indexed %d Python + %d R functions", py_count, r_count)
        logger.info("[READY] First-run indexing complete -- server ready")
    finally:
        _startup_complete.set()


# ── FastMCP instance ─────────────────────────────────────────────────
mcp = FastMCP("LSEG-MCP")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TOOLS (6)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@mcp.tool()
async def search_financial_mapping(
    query: str | list[str],
    industry: str | None = None,
    statement: str | None = None,
    limit: int = 25,
) -> str:
    """
    Fuzzy-search the LSEG Financials → Company Fundamentals mapping matrix.

    Args:
        query: Search term (e.g. "Gross Profit", "RNTS", "Diluted EPS"). Can also be a list of terms.
        industry: Optional industry filter: "industrial", "bank", "insurance",
                  "property", "financial", "inv_trust", or "utility".
        statement: Optional statement filter: "Income Statement",
                   "Balance Sheet", "Cash Flow".
        limit: Max results to return per query (default 25).

    Returns:
        Matching rows with legacy COA codes, target FCC formulas, polarity,
        and implementation notes (additive formulas, ASR flags, etc.).
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
    try:
        engine = await _get_mapping_async()
        queries = query if isinstance(query, list) else [query]
        all_results = {}
        
        for q in queries:
            results = engine.search(q, industry=industry, statement=statement, limit=limit)
            all_results[q] = results
            
        if isinstance(query, str):
            if not all_results[query]:
                return f"No mapping found for query '{query}'" + (
                    f" in industry '{industry}'" if industry else ""
                ) + "."
            return json.dumps(all_results[query], indent=2, default=str)
            
        return json.dumps(all_results, indent=2, default=str)
    except FileNotFoundError:
        return "**Error**: Mapping Excel file not found. Set LSEG_MAPPING_PATH or place the file in data/LSEG_Mapping.xlsx."
    except Exception as e:
        return f"**Error**: {e}"


@mcp.tool()
async def get_mapping_rules() -> str:
    """
    Retrieve the overarching mapping definitions and rules from the LSEG matrix.

    Returns the 3 comparability categories (Identical / Comparable / Not Comparable),
    special-case handling rules (No FCC Match, ASR bracket notation, additive
    formulas, Primary Instrument requirements), and cash-flow / balance-sheet notes.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
    try:
        engine = await _get_mapping_async()
        rules = engine.get_rules()
        return json.dumps(rules, indent=2, default=str)
    except Exception as e:
        return f"**Error**: {e}"


@mcp.tool()
async def get_package_signature(language: str, function: str) -> str:
    """
    Fetch the live function signature from the local AST index.

    Args:
        language: "python" (for lseg-data) or "r" (for RefinitivR).
        function: Function name to look up (e.g. "get_data", "rd_GetData").

    Returns:
        The exact arguments, defaults, typing hints, and docstring
        as parsed from the currently installed source code.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."
    try:
        indexer = _get_indexer()
        result = indexer.get_signature(language, function)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"**Error**: {e}"


@mcp.tool()
async def validate_lseg_formula(
    fields: list[str],
    industry: str | None = None,
) -> str:
    """
    Validate drafted LSEG fields against the mapping matrix.

    The LLM submits its planned FCC/COA fields and the server checks for:
    - Not Comparable (NC) fields
    - Missing Primary Instrument requirements
    - "No FCC Match" operating fields (with non-operating redirect)
    - ASR layer requirements
    - Additive formula requirements

    Args:
        fields: List of FCC or COA codes to validate.
        industry: Optional industry context for validation.

    Returns:
        Per-field validation results with status and warnings.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."
    try:
        engine = await _get_mapping_async()
        results = engine.validate_formula(fields, industry=industry)
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"**Error**: {e}"


@mcp.tool()
async def draft_api_call(
    language: str,
    tickers: list[str],
    fields: list[str],
    industry: str | None = None,
) -> str:
    """
    Generate a syntactically correct LSEG data retrieval code boilerplate.

    Merges mapping rules and live AST-verified function signatures to produce
    ready-to-run code.

    Args:
        language: "python" (lseg-data) or "r" (RefinitivR).
        tickers: List of RIC codes (e.g. ["AAPL.O", "JPM"]).
        fields: List of requested data items (COA codes or descriptions).
        industry: Optional industry for correct FCC routing.

    Returns:
        Complete, runnable code with mapping-aware field resolution.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."
    try:
        engine = await _get_mapping_async()
        indexer = _get_indexer()

        # Resolve each field through the mapping engine
        mapping_notes: list[dict[str, Any]] = []
        for field in fields:
            matches = engine.search(field, industry=industry, limit=1)
            if matches:
                mapping_notes.append(matches[0])

        # Get the appropriate function signature
        func_name = "get_data" if language.lower() == "python" else "rd_GetData"
        sig = indexer.get_signature(language, func_name)
        if "error" in sig:
            sig = None

        result = code_generator.draft_api_call(
            language=language,
            tickers=tickers,
            fields=fields,
            mapping_notes=mapping_notes,
            signature=sig,
        )
        return f"```{language.lower()}\n{result}\n```"
    except Exception as e:
        return f"**Error**: {e}"


@mcp.tool()
async def rescan_packages(update_packages: bool = True, background: bool = False) -> str:
    """
    Force re-index of both Python (lseg-data) and R (RefinitivR) packages.

    When update_packages is True (default), this will:
    1. Run `git pull` on the RefinitivR repository
    2. Run `pip install --upgrade lseg-data`
    3. Flush AST caches and re-index both packages
    4. Return a diff of modified/added function counts

    Args:
        update_packages: If True, pull latest code before re-indexing.
                        Set False to just rebuild the index from current files.
        background: If True, run the rescan in the background to avoid 
                    client JSON-RPC timeouts on slow connections.

    Returns:
        Update status and diff summary.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."
    try:
        indexer = _get_indexer()
        rescan = _get_rescan()
        
        if background:
            asyncio.create_task(rescan.rescan(indexer, update_packages=update_packages))
            return json.dumps({
                "status": "started", 
                "message": "Rescan initiated in the background. Check logs for completion."
            })
            
        result = await rescan.rescan(indexer, update_packages=update_packages)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"**Error**: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RESOURCES (3)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@mcp.resource("matrix://financials_to_fundamentals")
async def matrix_resource() -> str:
    """
    Read-only Markdown resource of the global LSEG mapping rules
    and categorical definitions.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."
    try:
        engine = await _get_mapping_async()
        rules = engine.get_rules()

        lines = [
            "# LSEG Financials → Company Fundamentals Mapping Rules",
            "",
            "## Comparability Categories",
        ]
        for key, desc in rules["categories"].items():
            lines.append(f"- **{key}**: {desc}")

        lines.append("")
        lines.append("## Special Cases")
        for key, desc in rules["special_cases"].items():
            lines.append(f"- **{key}**: {desc}")

        lines.append("")
        lines.append(f"## Cash Flow Notes\n{rules['cash_flow_notes']}")
        lines.append("")
        lines.append(f"## Balance Sheet Notes\n{rules['balance_sheet_notes']}")
        lines.append("")
        lines.append("## Full Explanations")
        lines.append(rules["explanations"])

        return "\n".join(lines)
    except Exception as e:
        return f"Error loading matrix resource: {e}"


@mcp.resource("pkg://lseg-data/exports")
async def python_exports_resource() -> str:
    """Live hierarchical view of all Python functions in the current lseg-data package."""
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."
    try:
        indexer = _get_indexer()
        tree = indexer.get_exports("python")
        return json.dumps(tree, indent=2, default=str)
    except Exception as e:
        return f"Error loading Python exports: {e}"


@mcp.resource("pkg://RefinitivR/exports")
async def r_exports_resource() -> str:
    """Live hierarchical view of all R functions exported by the current RefinitivR commit."""
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."
    try:
        indexer = _get_indexer()
        tree = indexer.get_exports("r")
        return json.dumps(tree, indent=2, default=str)
    except Exception as e:
        return f"Error loading R exports: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Entry Point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    # Run the auto-indexer in a background thread so we don't block
    # the main thread. This ensures mcp.run() can immediately answer
    # the JSON-RPC initialize handshake, preventing client timeouts.
    t = threading.Thread(target=lambda: asyncio.run(_auto_index_on_startup()), daemon=True)
    t.start()
    
    # Start the MCP stdio event loop
    mcp.run()


if __name__ == "__main__":
    main()
