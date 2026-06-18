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
import time
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from lseg_mcp.mapping_engine import MappingEngine
from lseg_mcp.package_indexer import PackageIndexer
from lseg_mcp.rescan_manager import RescanManager
from lseg_mcp.data_dictionary import DataDictionary
from lseg_mcp import code_generator

# ── OS-level fd redirection to protect JSON-RPC on stdio ─────────────
# The MCP SDK reads sys.stdout.buffer at runtime to send JSON-RPC
# responses.  A Python-level `sys.stdout = sys.stderr` redirect would
# cause the SDK to write responses to stderr, breaking the protocol.
#
# Strategy (same fd-swap used by GGBOIndex's run_server.cmd):
#   1. Duplicate the real stdout fd so we can restore it later.
#   2. Redirect Python's sys.stdout to stderr so stray print() /
#      warnings from pandas / openpyxl / gitpython go to stderr.
#   3. In main(), restore sys.stdout from the saved fd right before
#      mcp.run() so the MCP SDK gets the real stdout pipe.
_real_stdout_fd = os.dup(sys.stdout.fileno())   # save real fd 1
_real_stderr = sys.stderr
sys.stdout = sys.stderr                          # Python-level guard

logger = logging.getLogger("lseg_mcp")

# ── Configure logging: stderr + file so startup messages are visible ──
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_handler)

# Also log to a file so the user can always review startup progress
from lseg_mcp._paths import get_log_dir, get_mapping_xlsx, get_r_repo_path
_LOG_DIR = get_log_dir()
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
_DEFAULT_XLSX = get_mapping_xlsx()
_DEFAULT_R_REPO = get_r_repo_path()
class AsyncTTLCache:
    """Async TTL cache with LRU eviction and active expiry purge."""
    def __init__(self, name: str, ttl_seconds: int, maxsize: int = 256):
        self.name = name
        self.ttl = ttl_seconds
        self.maxsize = maxsize
        self.cache: OrderedDict = OrderedDict()

    async def get_or_set(self, key, coro_func, *args, **kwargs):
        now = time.time()
        if key in self.cache:
            val, expiry = self.cache[key]
            if now < expiry:
                self.cache.move_to_end(key)
                logger.debug("[CACHE HIT] %s (key: %s)", self.name, key)
                return val
            logger.debug("[CACHE EXPIRED] %s (key: %s)", self.name, key)
            del self.cache[key]
        else:
            logger.debug("[CACHE MISS] %s (key: %s)", self.name, key)

        start_time = time.time()
        val = await coro_func(*args, **kwargs)
        elapsed = (time.time() - start_time) * 1000.0
        logger.debug("[CACHE LOAD] %s resolved in %.1fms", self.name, elapsed)

        if not (isinstance(val, str) and val.startswith("**Error**")):
            # Evict LRU entry if at capacity
            while len(self.cache) >= self.maxsize:
                evicted_key, _ = self.cache.popitem(last=False)
                logger.debug("[CACHE EVICT] %s (key: %s)", self.name, evicted_key)
            self.cache[key] = (val, now + self.ttl)
        return val

    def purge_expired(self):
        """Actively remove all expired entries."""
        now = time.time()
        expired = [k for k, (_, exp) in self.cache.items() if now >= exp]
        for k in expired:
            del self.cache[k]
            logger.debug("[CACHE PURGE] %s (key: %s)", self.name, k)

    def clear(self):
        self.cache.clear()


def _make_hashable(val: Any) -> Any:
    """Convert unhashable types (like lists, dicts) into hashable ones recursively."""
    if isinstance(val, list):
        return tuple(_make_hashable(x) for x in val)
    if isinstance(val, dict):
        return tuple((k, _make_hashable(v)) for k, v in sorted(val.items()))
    return val


_search_mapping_cache = AsyncTTLCache("search_financial_mapping", ttl_seconds=300)
_mapping_rules_cache = AsyncTTLCache("get_mapping_rules", ttl_seconds=1800)
_package_signature_cache = AsyncTTLCache("get_package_signature", ttl_seconds=300)
_validate_formula_cache = AsyncTTLCache("validate_lseg_formula", ttl_seconds=300)
_data_dict_cache = AsyncTTLCache("search_data_dictionary", ttl_seconds=300)


# ── Singletons (initialised lazily on first tool call) ───────────────
_mapping: MappingEngine | None = None
_indexer: PackageIndexer | None = None
_rescan: RescanManager | None = None
_data_dict: DataDictionary | None = None
_startup_complete = threading.Event()
_mapping_lock = asyncio.Lock()
_data_dict_lock = asyncio.Lock()


async def _get_mapping_async() -> MappingEngine:
    global _mapping
    if _mapping is not None:          # fast path — no lock needed
        return _mapping
    async with _mapping_lock:         # serialise cold-start init
        if _mapping is None:          # double-check after acquiring lock
            engine = MappingEngine(str(_DEFAULT_XLSX))
            await asyncio.to_thread(engine._load)
            _mapping = engine         # only assign once fully loaded
    return _mapping


async def _get_data_dict_async() -> DataDictionary:
    global _data_dict
    if _data_dict is not None:
        return _data_dict
    async with _data_dict_lock:
        if _data_dict is None:
            dd = DataDictionary()  # will auto-discover main xlsx for Custom_Fields etc.
            await asyncio.to_thread(dd._load)
            _data_dict = dd
    return _data_dict


def _get_indexer() -> PackageIndexer:
    global _indexer
    if _indexer is None:
        _indexer = PackageIndexer(r_repo_path=str(_DEFAULT_R_REPO))
    return _indexer


def _get_rescan() -> RescanManager:
    global _rescan
    if _rescan is None:
        _rescan = RescanManager(r_repo_path=str(_DEFAULT_R_REPO))
    return _rescan


def _needs_index() -> bool:
    """Return True if either index source is missing (cold start).

    Set the environment variable ``LSEG_FORCE_REINDEX=1`` to force
    a full re-index on the next server restart.
    """
    if os.environ.get("LSEG_FORCE_REINDEX", "").strip() == "1":
        return True
    r_missing = not _DEFAULT_R_REPO.joinpath("R").exists()
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
    
    async def _impl():
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

    cache_key = (_make_hashable(query), industry, statement, limit)
    return await _search_mapping_cache.get_or_set(cache_key, _impl)


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
    
    async def _impl():
        try:
            engine = await _get_mapping_async()
            rules = engine.get_rules()
            return json.dumps(rules, indent=2, default=str)
        except Exception as e:
            return f"**Error**: {e}"

    return await _mapping_rules_cache.get_or_set("rules", _impl)


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
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
    
    async def _impl():
        try:
            indexer = _get_indexer()
            result = indexer.get_signature(language, function)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"**Error**: {e}"

    cache_key = (language.lower(), function)
    return await _package_signature_cache.get_or_set(cache_key, _impl)


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

    Fields that are not in the financials COA/FCC matrix but exist in the
    extended data dictionary (Pricing / Estimates / ESG / Reference, e.g.
    TR.PriceClose) are reported as OK with source="data_dictionary" rather
    than NOT_FOUND, keeping this tool consistent with search_data_dictionary.

    Args:
        fields: List of FCC or COA codes to validate.
        industry: Optional industry context for validation.

    Returns:
        Per-field validation results with status and warnings.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
    
    async def _impl():
        try:
            engine = await _get_mapping_async()
            results = engine.validate_formula(fields, industry=industry)

            # Fields absent from the financials COA/FCC matrix may still be
            # valid extended dictionary items (Pricing / Estimates / ESG / ...).
            # Fall back to the data dictionary before declaring NOT_FOUND so the
            # tool stays consistent with search_data_dictionary.
            dd = await _get_data_dict_async()
            for entry in results:
                if entry.get("status") != "NOT_FOUND":
                    continue
                field_name = entry["field"]
                hits = dd.search(field_name, limit=1)
                if hits:
                    entry.clear()
                    entry.update({
                        "field": field_name,
                        "status": "OK",
                        "source": "data_dictionary",
                        "warnings": [],
                        "note": "Valid extended dictionary field (not in the financials COA/FCC matrix).",
                        "mapping": hits[0],
                    })

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            return f"**Error**: {e}"

    cache_key = (_make_hashable(fields), industry)
    return await _validate_formula_cache.get_or_set(cache_key, _impl)


@mcp.tool()
async def search_data_dictionary(
    query: str | list[str],
    category: str | None = None,
    limit: int = 30,
) -> str:
    """
    Fuzzy-search the extended LSEG Data Dictionary (Pricing, Estimates, ESG,
    Reference, Valuation, Fundamentals, etc.).

    This complements search_financial_mapping. Use it for TR.* fields that are
    not part of the standardized financials COA/FCC matrix (e.g. TR.PriceClose,
    TR.EPSMean, TR.ESGScore, TR.CompanyMarketCap, analyst targets, etc.).

    The dictionary is seeded from RefinitivR usage examples + curated production
    fields and can be extended by the user via:
      - A "Custom_Fields", "Data Dictionary", or "DIB Export" sheet in LSEG_Mapping.xlsx
      - A dedicated Excel/CSV pointed to by LSEG_DATA_DICTIONARY_PATH

    Args:
        query: Search term or list of terms (field name, description keyword, e.g. "price close", "eps mean", "esg").
        category: Optional filter e.g. "Pricing", "Estimates", "ESG", "Reference".
        limit: Max results.

    Returns:
        JSON list of matching fields with description, category, suggested parameters, and notes.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."

    async def _impl():
        try:
            dd = await _get_data_dict_async()
            queries = query if isinstance(query, list) else [query]
            out: dict[str, Any] = {}
            for q in queries:
                hits = dd.search(q, category=category, limit=limit)
                out[q] = hits
            if isinstance(query, str):
                if not out.get(query):
                    cats = ", ".join(dd.list_categories()[:8])
                    return f"No matches for '{query}'" + (f" in category '{category}'." if category else ".") + f" Available categories include: {cats}."
                return json.dumps(out[query], indent=2, default=str)
            return json.dumps(out, indent=2, default=str)
        except Exception as e:
            return f"**Error**: {e}"

    cache_key = (_make_hashable(query), category, limit)
    return await _data_dict_cache.get_or_set(cache_key, _impl)


@mcp.tool()
async def draft_api_call(
    language: str,
    tickers: list[str],
    fields: list[str],
    industry: str | None = None,
    parameters: dict[str, Any] | None = None,
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
        parameters: Optional API parameters dict for time-series queries
                    (e.g. {"SDate": "2020-01-01", "EDate": "2024-12-31",
                     "Frq": "FY", "Curn": "USD"}).

    Returns:
        Complete, runnable code with mapping-aware field resolution.
    """
    if not _startup_complete.is_set():
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
    try:
        engine = await _get_mapping_async()
        indexer = _get_indexer()
        dd = await _get_data_dict_async()

        # Resolve each field through the mapping engine (financials) + data dict fallback
        mapping_notes: list[dict[str, Any]] = []
        for field in fields:
            matches = engine.search(field, industry=industry, limit=1)
            if matches:
                mapping_notes.append(matches[0])
            else:
                # Fallback to extended dictionary (Pricing / Estimates / ESG / etc.)
                dhit = dd.search(field, limit=1)
                if dhit:
                    note = dhit[0]
                    note["_source"] = "data_dictionary"
                    # Inject a helpful note for the generator, but only when we
                    # actually have descriptive content (avoids empty noise like
                    # "Extended dict hit (General): . Parameters example: ").
                    desc = str(note.get("description", "")).strip()
                    params = str(note.get("parameters", "")).strip()
                    if note.get("category") and (desc or params):
                        bits = [f"Extended dict hit ({note['category']})"]
                        if desc:
                            bits.append(f": {desc}")
                        if params:
                            bits.append(f". Parameters example: {params}")
                        note.setdefault("_notes", []).append("".join(bits))
                    mapping_notes.append(note)

        # Get the appropriate function signature (prefer specialized for certain categories)
        func_name = "get_data" if language.lower() == "python" else "rd_GetData"
        # Simple heuristic: if any note points at Estimates/ESG, the caller can still choose
        # rd_GetEstimates etc.; we keep the generic signature here and let search_data_dictionary
        # surface the recommendation.
        sig = indexer.get_signature(language, func_name)
        if "error" in sig:
            sig = None

        result = code_generator.draft_api_call(
            language=language,
            tickers=tickers,
            fields=fields,
            mapping_notes=mapping_notes,
            signature=sig,
            parameters=parameters,
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
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover

    # Guard: block pip/git mutations outside a virtual environment
    if update_packages and os.environ.get("LSEG_ALLOW_ENV_MUTATION", "").strip() != "1":
        if not (hasattr(sys, "prefix") and sys.prefix != sys.base_prefix):
            return json.dumps({
                "status": "blocked",
                "message": (
                    "update_packages=True is blocked outside a virtual environment. "
                    "Set LSEG_ALLOW_ENV_MUTATION=1 to override, or run the server "
                    "inside a venv/uvx."
                ),
            })
    try:
        indexer = _get_indexer()
        rescan = _get_rescan()
        
        # Clear caches proactively
        _search_mapping_cache.clear()
        _mapping_rules_cache.clear()
        _package_signature_cache.clear()
        _validate_formula_cache.clear()
        _data_dict_cache.clear()
        
        if background:
            async def run_in_bg():
                try:
                    await rescan.rescan(indexer, update_packages=update_packages)
                finally:
                    # Clear caches again upon completion
                    _search_mapping_cache.clear()
                    _mapping_rules_cache.clear()
                    _package_signature_cache.clear()
                    _validate_formula_cache.clear()
                    _data_dict_cache.clear()
            asyncio.create_task(run_in_bg())
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
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
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
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
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
        return "⏳ **Status**: Server is downloading and indexing packages. Please wait 10 seconds and try again."  # pragma: no cover
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

    # ── Restore the real stdout for the MCP SDK ──────────────────────
    # The MCP SDK's stdio_server() reads sys.stdout.buffer to send
    # JSON-RPC responses.  We saved the real stdout fd at module load
    # time; now we re-wrap it as sys.stdout so the SDK writes to the
    # correct pipe.  The Python-level guard (sys.stdout = sys.stderr)
    # was only needed during import / startup to catch stray prints.
    from io import TextIOWrapper

    sys.stdout = TextIOWrapper(
        os.fdopen(_real_stdout_fd, "wb"),
        encoding="utf-8",
        line_buffering=True,
    )

    # Start the MCP stdio event loop
    mcp.run()



if __name__ == "__main__":  # pragma: no cover
    main()
