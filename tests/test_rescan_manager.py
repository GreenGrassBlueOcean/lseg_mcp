import pytest
import tempfile
import os
from pathlib import Path
from lseg_mcp.rescan_manager import RescanManager

@pytest.fixture
def mock_subprocess(mocker):
    class MockStream:
        def __init__(self, data):
            self.chunks = [data] if isinstance(data, bytes) else data
            
        async def read(self, n=-1):
            if self.chunks:
                return self.chunks.pop(0)
            return b""
            
    class MockProcess:
        def __init__(self, stdout, stderr, returncode):
            self.stdout = MockStream(stdout)
            self.stderr = MockStream(stderr)
            self.returncode = returncode
            
        async def communicate(self):
            return b"", b""
            
        async def wait(self):
            return self.returncode
            
    def make_mock(stdout=b"", stderr=b"", returncode=0):
        async def _mock_exec(*args, **kwargs):
            return MockProcess(stdout, stderr, returncode)
        return _mock_exec
        
    return make_mock

@pytest.mark.asyncio
async def test_update_r_package_pull(mocker, mock_subprocess):
    # Setup mock subprocess
    mocker.patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess(stdout=b"Already up to date."))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RescanManager(r_repo_path=tmpdir)
        res = await manager.update_r_package()
        assert res["status"] == "updated"
        assert "Already up to date." in res["message"]

@pytest.mark.asyncio
async def test_update_r_package_clone(mocker, mock_subprocess):
    mocker.patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess(stdout=b"Cloning into..."))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a path that DOES NOT exist to force clone
        repo_path = os.path.join(tmpdir, "RefinitivR_Not_There")
        manager = RescanManager(r_repo_path=repo_path)
        res = await manager.update_r_package()
        
        assert res["status"] == "cloned"
        assert "Successfully cloned" in res["message"]
        
@pytest.mark.asyncio
async def test_update_r_package_error(mocker, mock_subprocess):
    mocker.patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess(stderr=b"Git error", returncode=1))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RescanManager(r_repo_path=tmpdir)
        res = await manager.update_r_package()
        assert res["status"] == "error"
        assert "Git error" in res["message"]

@pytest.mark.asyncio
async def test_update_python_package_pip(mocker, mock_subprocess):
    call_count = {"n": 0}
    # 3 calls: pip show (before), pip install, pip show (after)
    async def multi_exec(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] in (1, 3):
            # pip show
            return await mock_subprocess(stdout=b"Name: lseg-data\nVersion: 2.1.0\n")(*args, **kwargs)
        else:
            # pip install
            chunks = [b"Successf", b"ully installed \r\n", b"lseg-data\n", b"Done\r"]
            return await mock_subprocess(stdout=chunks)(*args, **kwargs)
    mocker.patch("asyncio.create_subprocess_exec", side_effect=multi_exec)
    manager = RescanManager()
    res = await manager.update_python_package()
    assert res["status"] == "updated"
    assert "Successfully installed" in res["message"]
    assert res["version_before"] == "2.1.0"
    assert res["version_after"] == "2.1.0"
    assert "version_before" in res
    assert "version_after" in res

@pytest.mark.asyncio
async def test_update_python_package_error(mocker, mock_subprocess):
    mocker.patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess(stderr=b"Pip error", returncode=1))
    manager = RescanManager()
    res = await manager.update_python_package()
    assert res["status"] == "error"
    assert "version_before" in res
    assert "version_after" in res

@pytest.mark.asyncio
async def test_update_python_package_timeout(mocker):
    import asyncio
    class MockProcessHangs:
        def __init__(self):
            class MockStream:
                async def read(self, n=-1):
                    await asyncio.sleep(10)
                    return b""
            self.stdout = MockStream()
            self.stderr = MockStream()
            self.returncode = None
        async def wait(self):
            await asyncio.sleep(10)
            return 0
        def kill(self):
            raise OSError("Access denied")

    async def timeout_exec(*args, **kwargs):
        return MockProcessHangs()

    mocker.patch("asyncio.create_subprocess_exec", side_effect=timeout_exec)
    mocker.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError())
    manager = RescanManager()
    res = await manager.update_python_package()
    assert res["status"] == "error"
    assert "timed out" in res["message"]

@pytest.mark.asyncio
async def test_rescan_cycle(mocker, mock_subprocess):
    mocker.patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess(stdout=b"OK"))
    
    # Mock the indexer
    class MockIndex:
        _functions = []
    class MockIndexer:
        def __init__(self):
            self.python_index = MockIndex()
            self.r_index = MockIndex()
        def get_exports(self, lang):
            return {"total_exports": 10}
        def reindex(self):
            return {
                "python": {"status": "indexed"},
                "r": {"status": "indexed"}
            }
            
    indexer = MockIndexer()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RescanManager(r_repo_path=tmpdir)
        res = await manager.rescan(indexer)
        
        assert "r_update" in res
        assert "python_update" in res
        assert "diff" in res
        assert res["diff"]["r"]["delta"] == 0
        assert res["diff"]["python"]["delta"] == 0

@pytest.mark.asyncio
async def test_rescan_cycle_no_update(mocker):
    # Mock the indexer
    class MockIndex:
        _functions = []
    class MockIndexer:
        def __init__(self):
            self.python_index = MockIndex()
            self.r_index = MockIndex()
        def get_exports(self, lang):
            return {"total_exports": 10}
        def reindex(self):
            return {
                "python": {"status": "indexed"},
                "r": {"status": "indexed"}
            }
            
    indexer = MockIndexer()
    manager = RescanManager()
    
    res = await manager.rescan(indexer, update_packages=False)
    assert "r_update" not in res
    assert "python_update" not in res
    assert "diff" in res

@pytest.mark.asyncio
async def test_update_r_package_clone_error(mocker, mock_subprocess):
    # This hits line 78 (git clone error)
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "RefinitivR"
        manager = RescanManager(r_repo_path=str(repo_path))
        mocker.patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess(returncode=1, stderr=b"Clone failed"))
        res = await manager.update_r_package()
        assert res["status"] == "error"
        assert "Clone failed" in res["message"]

@pytest.mark.asyncio
async def test_run_cmd_file_not_found(mocker):
    # This hits lines 38-39
    import asyncio
    async def not_found(*args, **kwargs):
        raise FileNotFoundError("cmd not found")
    mocker.patch("asyncio.create_subprocess_exec", side_effect=not_found)
    manager = RescanManager()
    res = await manager.update_python_package()
    assert res["status"] == "error"
    assert "cmd not found" in res["message"]

def test_pip_path_resolution(mocker):
    # This hits lines 57 and 61
    manager1 = RescanManager(python_pip="custom_pip")
    assert manager1.python_pip == ["custom_pip"]
    
    manager2 = RescanManager()
    assert "-m" in manager2.python_pip
    assert "pip" in manager2.python_pip

@pytest.mark.asyncio
async def test_get_pip_version_success(mocker, mock_subprocess):
    """Verify _get_pip_version parses Version: line from pip show output."""
    mocker.patch(
        "asyncio.create_subprocess_exec",
        side_effect=mock_subprocess(stdout=b"Name: lseg-data\nVersion: 2.1.3\nSummary: LSEG SDK\n"),
    )
    manager = RescanManager()
    version = await manager._get_pip_version()
    assert version == "2.1.3"

@pytest.mark.asyncio
async def test_get_pip_version_not_installed(mocker, mock_subprocess):
    """Verify _get_pip_version returns 'unknown' when pip show fails."""
    mocker.patch(
        "asyncio.create_subprocess_exec",
        side_effect=mock_subprocess(returncode=1, stderr=b"not found"),
    )
    manager = RescanManager()
    version = await manager._get_pip_version()
    assert version == "unknown"

@pytest.mark.asyncio
async def test_get_pip_version_malformed_output(mocker, mock_subprocess):
    """Verify _get_pip_version returns 'unknown' when Version line is missing."""
    mocker.patch(
        "asyncio.create_subprocess_exec",
        side_effect=mock_subprocess(stdout=b"Name: lseg-data\nSummary: LSEG SDK\n"),
    )
    manager = RescanManager()
    version = await manager._get_pip_version()
    assert version == "unknown"
