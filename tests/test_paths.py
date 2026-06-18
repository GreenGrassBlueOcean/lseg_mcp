"""Tests for the centralized path resolution module."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from lseg_mcp._paths import (
    get_cache_dir,
    get_data_dictionary_path,
    get_data_dir,
    get_log_dir,
    get_mapping_xlsx,
    get_r_repo_path,
)


def test_get_data_dir():
    """Data dir should be inside the package."""
    d = get_data_dir()
    assert d.name == "data"
    assert "lseg_mcp" in str(d)


def test_get_mapping_xlsx_default():
    """Default xlsx should resolve to the bundled package copy."""
    xlsx = get_mapping_xlsx()
    assert xlsx.name.lower() == "lseg_mapping.xlsx"
    assert "lseg_mcp" in str(xlsx)


def test_get_mapping_xlsx_env_override(monkeypatch, tmp_path):
    """LSEG_MAPPING_PATH env var should override the default."""
    fake = tmp_path / "custom.xlsx"
    fake.touch()
    monkeypatch.setenv("LSEG_MAPPING_PATH", str(fake))
    result = get_mapping_xlsx()
    assert result == fake


def test_get_cache_dir_windows(monkeypatch, tmp_path):
    """On Windows, cache should be under LOCALAPPDATA."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = get_cache_dir()
    assert result == tmp_path / "lseg-mcp"
    assert result.exists()


def test_get_cache_dir_linux(monkeypatch, tmp_path):
    """On Linux, cache should be under XDG_CACHE_HOME."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    result = get_cache_dir()
    assert result == tmp_path / "lseg-mcp"
    assert result.exists()


def test_get_cache_dir_macos(monkeypatch, tmp_path):
    """On macOS, cache should be under ~/Library/Caches."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = get_cache_dir()
    assert result == tmp_path / "Library" / "Caches" / "lseg-mcp"
    assert result.exists()


def test_get_r_repo_path_default():
    """Default R repo should be inside the cache dir."""
    result = get_r_repo_path()
    assert result.name == "RefinitivR"
    assert "lseg-mcp" in str(result)


def test_get_r_repo_path_env_override(monkeypatch, tmp_path):
    """REFINITIVR_PATH env var should override the default."""
    fake = tmp_path / "MyRRepo"
    fake.mkdir()
    monkeypatch.setenv("REFINITIVR_PATH", str(fake))
    result = get_r_repo_path()
    assert result == fake


def test_get_log_dir():
    """Log dir should be a 'logs' subdirectory of the cache dir."""
    result = get_log_dir()
    assert result.name == "logs"
    assert result.exists()


def test_get_data_dictionary_path_unset(monkeypatch):
    """With no env var set, the data dictionary path is None."""
    monkeypatch.delenv("LSEG_DATA_DICTIONARY_PATH", raising=False)
    assert get_data_dictionary_path() is None


def test_get_data_dictionary_path_env_override(monkeypatch, tmp_path):
    """LSEG_DATA_DICTIONARY_PATH env var should be returned as a Path."""
    fake = tmp_path / "my_dict.csv"
    fake.touch()
    monkeypatch.setenv("LSEG_DATA_DICTIONARY_PATH", str(fake))
    assert get_data_dictionary_path() == fake
