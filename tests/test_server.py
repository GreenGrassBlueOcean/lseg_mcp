import pytest
import json
import os
from lseg_mcp import server

@pytest.fixture(autouse=True)
def mock_environment(mocker, mock_pandas_read_excel):
    # Set the mapping path to our dummy so `_get_mapping` loads the mock
    mocker.patch.dict(os.environ, {"LSEG_MAPPING_PATH": "dummy.xlsx"})
    
    server._mapping = None
    server._indexer = None
    server._rescan = None
    server._startup_complete.set()
    
    # Reset caches for isolation
    server._search_mapping_cache.clear()
    server._mapping_rules_cache.clear()
    server._package_signature_cache.clear()
    server._validate_formula_cache.clear()

@pytest.mark.asyncio
async def test_search_financial_mapping():
    # Valid search
    res = await server.search_financial_mapping("RREV")
    assert "RREV" in res
    
    # Missing search
    res2 = await server.search_financial_mapping("NOTHING")
    assert "No mapping found" in res2

@pytest.mark.asyncio
async def test_search_financial_mapping_list():
    # Multiple valid searches
    res = await server.search_financial_mapping(["RREV", "RDEBT"])
    assert "RREV" in res
    assert "RDEBT" in res

@pytest.mark.asyncio
async def test_search_financial_mapping_error(mocker):
    mocker.patch("lseg_mcp.server._get_mapping_async", side_effect=FileNotFoundError())
    res = await server.search_financial_mapping("RREV")
    assert "**Error**: Mapping Excel file not found" in res
    
    mocker.patch("lseg_mcp.server._get_mapping_async", side_effect=Exception("Generic error"))
    res2 = await server.search_financial_mapping("RREV")
    assert "**Error**: Generic error" in res2

@pytest.mark.asyncio
async def test_get_mapping_rules():
    res = await server.get_mapping_rules()
    assert "1_identical" in res

@pytest.mark.asyncio
async def test_get_mapping_rules_error(mocker):
    mocker.patch("lseg_mcp.server._get_mapping_async", side_effect=Exception("Generic error"))
    res = await server.get_mapping_rules()
    assert "**Error**: Generic error" in res

@pytest.mark.asyncio
async def test_get_package_signature(mocker):
    class MockIndexer:
        def get_signature(self, lang, func):
            return {"name": func, "args": []}
            
    mocker.patch("lseg_mcp.server._get_indexer", return_value=MockIndexer())
    res = await server.get_package_signature("python", "get_data")
    assert "get_data" in res

@pytest.mark.asyncio
async def test_get_package_signature_error(mocker):
    mocker.patch("lseg_mcp.server._get_indexer", side_effect=Exception("Generic error"))
    res = await server.get_package_signature("python", "get_data")
    assert "**Error**: Generic error" in res

@pytest.mark.asyncio
async def test_validate_lseg_formula():
    res = await server.validate_lseg_formula(["RREV"])
    parsed = json.loads(res)
    assert parsed[0]["status"] == "OK"

@pytest.mark.asyncio
async def test_validate_lseg_formula_error(mocker):
    mocker.patch("lseg_mcp.server._get_mapping_async", side_effect=Exception("Generic error"))
    res = await server.validate_lseg_formula(["RREV"])
    assert "**Error**: Generic error" in res

@pytest.mark.asyncio
async def test_draft_api_call(mocker):
    class MockIndexer:
        def get_signature(self, lang, func):
            return {"name": func, "args": [], "doc": "mocked doc"}
            
    mocker.patch("lseg_mcp.server._get_indexer", return_value=MockIndexer())
    
    res = await server.draft_api_call("python", ["AAPL.O"], ["RREV"])
    assert "import lseg.data as ld" in res
    assert "TR.GrossRevenue" in res # The office_field resolved from the dummy.xlsx mapping

@pytest.mark.asyncio
async def test_draft_api_call_error(mocker):
    mocker.patch("lseg_mcp.server._get_mapping_async", side_effect=Exception("Generic error"))
    res = await server.draft_api_call("python", ["AAPL.O"], ["RREV"])
    assert "**Error**: Generic error" in res

@pytest.mark.asyncio
async def test_rescan_packages(mocker):
    class MockRescan:
        async def rescan(self, indexer, update_packages):
            return {"status": "ok"}
            
    mocker.patch("lseg_mcp.server._get_rescan", return_value=MockRescan())
    mocker.patch("lseg_mcp.server._get_indexer", return_value="dummy_indexer")
    
    res = await server.rescan_packages()
    assert "ok" in res

@pytest.mark.asyncio
async def test_rescan_packages_background(mocker):
    class MockRescan:
        async def rescan(self, indexer, update_packages):
            return {"status": "ok"}
            
    mocker.patch("lseg_mcp.server._get_rescan", return_value=MockRescan())
    mocker.patch("lseg_mcp.server._get_indexer", return_value="dummy_indexer")
    
    import asyncio
    res = await server.rescan_packages(background=True)
    
    assert "started" in res
    assert "background" in res
    await asyncio.sleep(0.05)

@pytest.mark.asyncio
async def test_rescan_packages_error(mocker):
    mocker.patch("lseg_mcp.server._get_rescan", side_effect=Exception("Generic error"))
    res = await server.rescan_packages()
    assert "**Error**: Generic error" in res

@pytest.mark.asyncio
async def test_matrix_resource():
    res = await server.matrix_resource()
    assert "LSEG Financials" in res
    assert "1_identical" in res

@pytest.mark.asyncio
async def test_matrix_resource_error(mocker):
    mocker.patch("lseg_mcp.server._get_mapping_async", side_effect=Exception("Generic error"))
    res = await server.matrix_resource()
    assert "Error loading matrix resource: Generic error" in res

@pytest.mark.asyncio
async def test_python_exports_resource(mocker):
    class MockIndexer:
        def get_exports(self, lang):
            return {"total_exports": 10}
            
    mocker.patch("lseg_mcp.server._get_indexer", return_value=MockIndexer())
    res = await server.python_exports_resource()
    assert "total_exports" in res

@pytest.mark.asyncio
async def test_python_exports_resource_error(mocker):
    mocker.patch("lseg_mcp.server._get_indexer", side_effect=Exception("Generic error"))
    res = await server.python_exports_resource()
    assert "Error loading Python exports: Generic error" in res

@pytest.mark.asyncio
async def test_r_exports_resource(mocker):
    class MockIndexer:
        def get_exports(self, lang):
            return {"total_exports": 20}
            
    mocker.patch("lseg_mcp.server._get_indexer", return_value=MockIndexer())
    res = await server.r_exports_resource()
    assert "total_exports" in res

@pytest.mark.asyncio
async def test_r_exports_resource_error(mocker):
    mocker.patch("lseg_mcp.server._get_indexer", side_effect=Exception("Generic error"))
    res = await server.r_exports_resource()
    assert "Error loading R exports: Generic error" in res

def test_main(mocker):
    # Test the synchronous entrypoint — now includes background threading
    mock_thread = mocker.patch("lseg_mcp.server.threading.Thread")
    mocker.patch("lseg_mcp.server.mcp.run")
    server.main()
    mock_thread.assert_called_once()
    mock_thread.return_value.start.assert_called_once()
    server.mcp.run.assert_called_once()

@pytest.mark.asyncio
async def test_singletons(mocker, mock_pandas_read_excel):
    # Ensure they create new instances when None
    server._mapping = None
    server._indexer = None
    server._rescan = None
    
    mocker.patch.dict(os.environ, {"LSEG_MAPPING_PATH": "dummy.xlsx", "REFINITIVR_PATH": "dummy_r_path"})
    
    m1 = await server._get_mapping_async()
    assert m1 is not None
    assert server._mapping is m1
    
    i1 = server._get_indexer()
    assert i1 is not None
    assert server._indexer is i1
    
    r1 = server._get_rescan()
    assert r1 is not None
    assert server._rescan is r1


def test_needs_index_cold_start(mocker, tmp_path):
    """Both R and Python missing -> needs index."""
    mocker.patch.object(server, "_DEFAULT_R_REPO", tmp_path / "no_repo")
    mocker.patch("lseg_mcp.server.importlib.util.find_spec", return_value=None)
    assert server._needs_index() is True


def test_needs_index_warm_start(mocker, tmp_path):
    """Both R and Python present -> no index needed."""
    r_dir = tmp_path / "RefinitivR" / "R"
    r_dir.mkdir(parents=True)
    mocker.patch.object(server, "_DEFAULT_R_REPO", tmp_path / "RefinitivR")
    mocker.patch("lseg_mcp.server.importlib.util.find_spec", return_value="dummy_spec")
    assert server._needs_index() is False


def test_needs_index_force_reindex(mocker, tmp_path):
    """LSEG_FORCE_REINDEX=1 forces re-index even when warm."""
    r_dir = tmp_path / "RefinitivR" / "R"
    r_dir.mkdir(parents=True)
    mocker.patch.object(server, "_DEFAULT_R_REPO", tmp_path / "RefinitivR")
    mocker.patch.dict(os.environ, {"LSEG_FORCE_REINDEX": "1"})
    mocker.patch("lseg_mcp.server.importlib.util.find_spec", return_value="dummy_spec")
    assert server._needs_index() is True


def test_needs_index_only_r_missing(mocker, tmp_path):
    """R missing but Python present -> needs index."""
    mocker.patch.object(server, "_DEFAULT_R_REPO", tmp_path / "no_repo")
    mocker.patch("lseg_mcp.server.importlib.util.find_spec", return_value="dummy_spec")
    assert server._needs_index() is True


def test_needs_index_only_python_missing(mocker, tmp_path):
    """Python missing but R present -> needs index."""
    r_dir = tmp_path / "RefinitivR" / "R"
    r_dir.mkdir(parents=True)
    mocker.patch.object(server, "_DEFAULT_R_REPO", tmp_path / "RefinitivR")
    mocker.patch("lseg_mcp.server.importlib.util.find_spec", return_value=None)
    assert server._needs_index() is True


def test_needs_index_python_module_not_found(mocker, tmp_path):
    """Python parent module missing -> needs index (gracefully handles exception)."""
    r_dir = tmp_path / "RefinitivR" / "R"
    r_dir.mkdir(parents=True)
    mocker.patch.object(server, "_DEFAULT_R_REPO", tmp_path / "RefinitivR")
    mocker.patch("lseg_mcp.server.importlib.util.find_spec", side_effect=ModuleNotFoundError("No module named 'lseg'"))
    assert server._needs_index() is True


@pytest.mark.asyncio
async def test_auto_index_skips_warm_start(mocker):
    """No action taken when indexes are already populated."""
    mocker.patch("lseg_mcp.server._needs_index", return_value=False)
    spy_rescan = mocker.patch("lseg_mcp.server._get_rescan")
    await server._auto_index_on_startup()
    spy_rescan.assert_not_called()


@pytest.mark.asyncio
async def test_auto_index_full_cold_start(mocker, tmp_path):
    """Both R and Python missing: clones R and pip-installs Python."""
    mocker.patch("lseg_mcp.server._needs_index", return_value=True)

    # Mock rescan manager
    mock_rescan = mocker.MagicMock()
    mock_rescan.r_repo_path = tmp_path / "RefinitivR"  # no R/ subdir -> triggers clone
    mock_rescan.update_r_package = mocker.AsyncMock(return_value={"status": "cloned"})
    mock_rescan.update_python_package = mocker.AsyncMock(return_value={"status": "updated"})
    mocker.patch("lseg_mcp.server._get_rescan", return_value=mock_rescan)

    # Mock indexer
    mock_indexer = mocker.MagicMock()
    mock_indexer.reindex.return_value = {"python": {"count": 50}, "r": {"count": 30}}
    mocker.patch("lseg_mcp.server._get_indexer", return_value=mock_indexer)

    # Python missing
    mocker.patch("lseg_mcp.server.importlib.util.find_spec", return_value=None)

    await server._auto_index_on_startup()

    mock_rescan.update_r_package.assert_awaited_once()
    mock_rescan.update_python_package.assert_awaited_once()
    mock_indexer.reindex.assert_called_once()


@pytest.mark.asyncio
async def test_auto_index_python_module_not_found(mocker, tmp_path):
    """Python parent module missing: gracefully handles exception and installs Python."""
    mocker.patch("lseg_mcp.server._needs_index", return_value=True)

    r_dir = tmp_path / "RefinitivR" / "R"
    r_dir.mkdir(parents=True)

    mock_rescan = mocker.MagicMock()
    mock_rescan.r_repo_path = tmp_path / "RefinitivR"
    mock_rescan.update_r_package = mocker.AsyncMock()
    mock_rescan.update_python_package = mocker.AsyncMock(return_value={"status": "updated"})
    mocker.patch("lseg_mcp.server._get_rescan", return_value=mock_rescan)

    mock_indexer = mocker.MagicMock()
    mock_indexer.reindex.return_value = {"python": {"count": 50}, "r": {"count": 30}}
    mocker.patch("lseg_mcp.server._get_indexer", return_value=mock_indexer)

    mocker.patch("lseg_mcp.server.importlib.util.find_spec", side_effect=ModuleNotFoundError("No module named 'lseg'"))

    await server._auto_index_on_startup()

    mock_rescan.update_python_package.assert_awaited_once()
    mock_indexer.reindex.assert_called_once()


@pytest.mark.asyncio
async def test_auto_index_partial_cold_r_present(mocker, tmp_path):
    """R present but Python missing: skips clone, installs Python."""
    mocker.patch("lseg_mcp.server._needs_index", return_value=True)

    r_dir = tmp_path / "RefinitivR" / "R"
    r_dir.mkdir(parents=True)

    mock_rescan = mocker.MagicMock()
    mock_rescan.r_repo_path = tmp_path / "RefinitivR"
    mock_rescan.update_r_package = mocker.AsyncMock()
    mock_rescan.update_python_package = mocker.AsyncMock(return_value={"status": "updated"})
    mocker.patch("lseg_mcp.server._get_rescan", return_value=mock_rescan)

    mock_indexer = mocker.MagicMock()
    mock_indexer.reindex.return_value = {"python": {"count": 50}, "r": {"count": 30}}
    mocker.patch("lseg_mcp.server._get_indexer", return_value=mock_indexer)

    mocker.patch("lseg_mcp.server.importlib.util.find_spec", return_value=None)

    await server._auto_index_on_startup()

    mock_rescan.update_r_package.assert_not_awaited()  # R was present, no clone
    mock_rescan.update_python_package.assert_awaited_once()
    mock_indexer.reindex.assert_called_once()


@pytest.mark.asyncio
async def test_caching_behavior(mocker):
    # Reset caches
    server._search_mapping_cache.clear()
    server._mapping_rules_cache.clear()
    
    # Mock search
    mock_engine = mocker.MagicMock()
    mock_engine.search.return_value = [{"ric": "AAPL.O", "coa": "RREV"}]
    mock_engine.get_rules.return_value = {"categories": {"1_identical": "Identical"}}
    mocker.patch("lseg_mcp.server._get_mapping_async", return_value=mock_engine)
    
    # First call: should query engine
    res1 = await server.search_financial_mapping("RREV")
    mock_engine.search.assert_called_once_with("RREV", industry=None, statement=None, limit=25)
    
    # Second call: should hit cache
    mock_engine.search.reset_mock()
    res2 = await server.search_financial_mapping("RREV")
    mock_engine.search.assert_not_called()
    assert res1 == res2
    
    # rules first call
    rules1 = await server.get_mapping_rules()
    mock_engine.get_rules.assert_called_once()
    
    # rules second call: hits cache
    mock_engine.get_rules.reset_mock()
    rules2 = await server.get_mapping_rules()
    mock_engine.get_rules.assert_not_called()
    assert rules1 == rules2
    
    # Call rescan_packages: should clear caches
    class MockRescan:
        async def rescan(self, indexer, update_packages):
            return {"status": "ok"}
            
    mocker.patch("lseg_mcp.server._get_rescan", return_value=MockRescan())
    mocker.patch("lseg_mcp.server._get_indexer", return_value="dummy_indexer")
    await server.rescan_packages()
    
    # Calling again should not hit cache (should call engine again)
    mock_engine.search.reset_mock()
    await server.search_financial_mapping("RREV")
    mock_engine.search.assert_called_once_with("RREV", industry=None, statement=None, limit=25)


def test_make_hashable_dict():
    val = {"b": 2, "a": {"d": 4, "c": 3}}
    res = server._make_hashable(val)
    assert res == (("a", (("c", 3), ("d", 4))), ("b", 2))


@pytest.mark.asyncio
async def test_async_ttl_cache_expiry():
    import time
    cache = server.AsyncTTLCache("test_expiry", ttl_seconds=1)
    call_count = 0
    async def mock_coro():
        nonlocal call_count
        call_count += 1
        return f"val_{call_count}"
    
    # First call
    r1 = await cache.get_or_set("key", mock_coro)
    assert r1 == "val_1"
    assert call_count == 1
    
    # Second call (hits cache)
    r2 = await cache.get_or_set("key", mock_coro)
    assert r2 == "val_1"
    assert call_count == 1
    
    # Force expiry by tampering with the cache entry's timestamp
    cache.cache["key"] = (r1, time.time() - 2)
    
    # Third call (should delete and recalculate)
    r3 = await cache.get_or_set("key", mock_coro)
    assert r3 == "val_2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_async_ttl_cache_error_not_cached():
    cache = server.AsyncTTLCache("test_error", ttl_seconds=10)
    call_count = 0
    async def mock_coro():
        nonlocal call_count
        call_count += 1
        return "**Error**: Something failed"
        
    r1 = await cache.get_or_set("key", mock_coro)
    assert r1 == "**Error**: Something failed"
    assert "key" not in cache.cache


@pytest.mark.asyncio
async def test_draft_api_call_signature_error(mocker):
    class MockIndexer:
        def get_signature(self, lang, func):
            return {"error": "Failed to parse"}
    mocker.patch("lseg_mcp.server._get_indexer", return_value=MockIndexer())
    
    # This should succeed even if get_signature returns an error dict
    res = await server.draft_api_call("python", ["AAPL.O"], ["RREV"])
    assert "import lseg.data as ld" in res


def test_flushing_file_handler_os_error(mocker, tmp_path):
    import logging
    log_file = tmp_path / "test_flush.log"
    handler = server.FlushingFileHandler(log_file)
    
    # Mock os.fsync to raise OSError
    mocker.patch("os.fsync", side_effect=OSError("Mocked OS Error"))
    
    record = logging.LogRecord("test", logging.INFO, "path", 1, "msg", (), None)
    # This should not raise an error because of the try-except block
    handler.emit(record)
    handler.close()
