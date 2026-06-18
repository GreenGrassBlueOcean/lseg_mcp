"""
Centralized path resolution for LSEG-MCP.

All runtime paths are resolved here so the package works correctly
whether installed from PyPI (``pip install lseg-mcp`` / ``uvx lseg-mcp``)
or from a local editable checkout (``pip install -e .``).

Layout:
    Package data  → ``src/lseg_mcp/data/LSEG_Mapping.xlsx`` (bundled in wheel)
    Runtime cache → ``%LOCALAPPDATA%/lseg-mcp/`` (Windows)
                    ``~/.cache/lseg-mcp/``       (Linux / macOS)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent          # src/lseg_mcp/
_APP_NAME = "lseg-mcp"


def get_data_dir() -> Path:
    """Return the path to bundled package data (read-only at runtime)."""
    return _PACKAGE_DIR / "data"


def get_mapping_xlsx() -> Path:
    """Return the path to the bundled LSEG mapping Excel workbook.

    Resolution order:
    1. ``LSEG_MAPPING_PATH`` environment variable (explicit override).
    2. Bundled ``src/lseg_mcp/data/LSEG_Mapping.xlsx`` inside the package.
    """
    env = os.environ.get("LSEG_MAPPING_PATH")
    if env:
        return Path(env)

    data_dir = get_data_dir()
    if data_dir.exists():
        for f in data_dir.iterdir():
            if f.name.lower() == "lseg_mapping.xlsx":
                return f
    # Absolute fallback (should never happen if wheel is built correctly)
    return data_dir / "LSEG_Mapping.xlsx"  # pragma: no cover


def get_cache_dir() -> Path:
    """Return the platform-specific runtime cache directory.

    - Windows:  ``%LOCALAPPDATA%/lseg-mcp/``
    - Linux:    ``$XDG_CACHE_HOME/lseg-mcp/``  (defaults to ``~/.cache/lseg-mcp/``)
    - macOS:    ``~/Library/Caches/lseg-mcp/``

    The directory is created on first call.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))

    cache = base / _APP_NAME
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def get_r_repo_path() -> Path:
    """Return the expected RefinitivR clone location.

    Resolution order:
    1. ``REFINITIVR_PATH`` environment variable (explicit override).
    2. ``<cache_dir>/RefinitivR/`` auto-bootstrap location.
    """
    env = os.environ.get("REFINITIVR_PATH")
    if env:
        return Path(env)
    return get_cache_dir() / "RefinitivR"


def get_log_dir() -> Path:
    """Return the log directory (inside the cache dir)."""
    log_dir = get_cache_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_data_dictionary_path() -> Path | None:
    """
    Optional override path for an extended Data Dictionary Excel/CSV.

    Set LSEG_DATA_DICTIONARY_PATH to point at a .xlsx or .csv containing
    Custom_Fields / DIB exports (columns: Field, Description, Category, Parameters, Notes).
    If unset, the DataDictionary will still scan the main LSEG_Mapping.xlsx for
    sheets named *Custom*, *Data Dictionary*, *DIB*, *Extended*, etc.
    """
    env = os.environ.get("LSEG_DATA_DICTIONARY_PATH")
    if env:
        p = Path(env)
        return p if p.exists() else p  # return even if missing; loader will handle
    return None
