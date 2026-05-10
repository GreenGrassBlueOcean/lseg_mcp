import pytest
import tempfile
import os
from pathlib import Path
from lseg_mcp.package_indexer import PythonPackageIndex, RPackageIndex, PackageIndexer

@pytest.fixture
def mock_python_package(mocker):
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_dir = os.path.join(tmpdir, "lseg", "data")
        os.makedirs(pkg_dir)
        
        # Valid python file
        with open(os.path.join(pkg_dir, "core.py"), "w") as f:
            f.write('''
def get_data(universe, fields: list = []):
    """Fetches data."""
    pass

class DataSession:
    """A data session."""
    def open(self):
        pass
    def _private_method(self):
        pass

def _internal():
    pass
''')
        
        # Syntax error python file
        with open(os.path.join(pkg_dir, "bad.py"), "w") as f:
            f.write("def bad_syntax() ")
            
        # Mock locate package
        mocker.patch.object(PythonPackageIndex, "_locate_package", return_value=pkg_dir)
        yield pkg_dir

@pytest.fixture
def mock_r_package():
    with tempfile.TemporaryDirectory() as tmpdir:
        r_dir = os.path.join(tmpdir, "R")
        os.makedirs(r_dir)
        man_dir = os.path.join(tmpdir, "man")
        os.makedirs(man_dir)
        
        with open(os.path.join(tmpdir, "NAMESPACE"), "w") as f:
            f.write('export(get_data)\nexportPattern("^rd_")\n')
            
        with open(os.path.join(r_dir, "core.R"), "w") as f:
            f.write('''
#' Get Data
#' @export
get_data <- function(rics, fields = NULL) {
    # do something
}

rd_helper <- function(x) {}

internal_func <- function() {}

MyClass <- R6::R6Class("MyClass", public = list())

#' Complex Signature
#' @export
rd_GetData <- function(
  RDObject = rd_connection(), rics,
  Eikonformulas,
  Parameters = NULL
) {
  # Test multi-line parser
}
''')

        # Dummy Rd file
        with open(os.path.join(man_dir, "get_data.Rd"), "w") as f:
            f.write('''
\\title{Get Data Title}
\\description{Detailed description}
\\usage{get_data(rics, fields)}
''')
            
        yield tmpdir

def test_python_indexer(mock_python_package):
    idx = PythonPackageIndex("lseg.data")
    funcs = idx.index()
    
    # Check count
    assert len(funcs) == 2 # 1 func, 1 class (methods no longer hallucinated as top-level)
    
    sig = idx.get_signature("get_data")
    assert sig is not None
    assert sig["type"] == "function"
    assert sig["name"] == "get_data"
    assert len(sig["args"]) == 2
    assert sig["args"][0]["name"] == "universe"
    assert sig["doc"] == "Fetches data."
    
    # Class check
    cls_sig = idx.get_signature("open")
    assert cls_sig is not None
    assert cls_sig["name"] == "open"
    assert cls_sig["class"] == "DataSession"
    
    # Internal methods skipped
    assert idx.get_signature("_private_method") is None
    assert idx.get_signature("_internal") is None

    # Tree
    tree = idx.get_exports_tree()
    assert tree["total_exports"] == 2
    assert "core.py" in tree["files"]

def test_python_indexer_not_found(mocker):
    mocker.patch.object(PythonPackageIndex, "_locate_package", return_value=None)
    idx = PythonPackageIndex("missing")
    res = idx.index()
    assert "error" in res[0]

def test_r_indexer(mock_r_package):
    idx = RPackageIndex(mock_r_package)
    funcs = idx.index()
    
    assert len(funcs) == 5 # 4 funcs, 1 class
    
    sig = idx.get_signature("get_data")
    assert sig is not None
    assert sig["type"] == "function"
    assert sig["exported"] is True
    assert sig["rd_title"] == "Get Data Title"
    
    sig2 = idx.get_signature("rd_helper")
    assert sig2["exported"] is True # matches pattern ^rd_
    
    sig3 = idx.get_signature("internal_func")
    assert sig3["exported"] is False
    
    cls_sig = idx.get_signature("MyClass")
    assert cls_sig["type"] == "R6Class"
    
    # Test the multi-line parameter parsing logic with nested parens
    sig_complex = idx.get_signature("rd_GetData")
    assert sig_complex is not None
    assert sig_complex["args"] == [
        "RDObject = rd_connection()",
        "rics",
        "Eikonformulas",
        "Parameters = NULL"
    ]
    
    tree = idx.get_exports_tree()
    assert tree["total_exports"] == 3 # get_data, rd_helper, rd_GetData

def test_r_indexer_not_found():
    idx = RPackageIndex("/does/not/exist/ever")
    res = idx.index()
    assert "error" in res[0]
    
    # Dir exists but no R folder
    with tempfile.TemporaryDirectory() as tmpdir:
        idx2 = RPackageIndex(tmpdir)
        res2 = idx2.index()
        assert "error" in res2[0]

def test_fingerprint_caching(mock_python_package):
    idx = PythonPackageIndex("lseg.data")
    funcs1 = idx.index()
    assert len(funcs1) == 2
    fp = idx._fingerprint
    
    # Call again without force, should use cache
    funcs2 = idx.index()
    assert funcs1 is funcs2
    
    # Force re-index
    funcs3 = idx.index(force=True)
    assert funcs1 is not funcs3

def test_package_indexer_facade(mocker, mock_python_package, mock_r_package):
    # The facade unifies them
    idx = PackageIndexer(r_repo_path=mock_r_package)
    
    assert idx.get_signature("python", "get_data")["name"] == "get_data"
    assert idx.get_signature("r", "get_data")["name"] == "get_data"
    assert "error" in idx.get_signature("unknown", "get_data")
    assert "error" in idx.get_signature("python", "missing")
    
    tree_py = idx.get_exports("python")
    assert tree_py["total_exports"] == 2
    
    tree_r = idx.get_exports("r")
    assert tree_r["total_exports"] == 3
    
    assert "error" in idx.get_exports("unknown")
    
    # Reindex
    res = idx.reindex()
    assert res["python"]["status"] == "indexed"
    assert res["r"]["status"] == "indexed"
    
    res2 = idx.reindex("python")
    assert "python" in res2
    assert "r" not in res2

def test_python_indexer_syntax_error(mock_python_package):
    idx = PythonPackageIndex("lseg.data")
    funcs = idx.index()
    # Should catch the SyntaxError in bad.py and log it, moving on.
    assert len(funcs) == 2

def test_r_indexer_missing_namespace():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create an R dir but no NAMESPACE
        r_dir = os.path.join(tmpdir, "R")
        os.makedirs(r_dir)
        with open(os.path.join(r_dir, "core.R"), "w") as f:
            f.write("test <- function() {}")
        # Add a txt file to hit line 180
        with open(os.path.join(r_dir, "test.txt"), "w") as f:
            f.write("ignored")
        idx = RPackageIndex(tmpdir)
        idx.index()
        sig = idx.get_signature("test")
        assert sig is not None
        assert sig["exported"] is False
        
        # Test cache hit (line 171)
        idx.index()
        
        # Test exports tree lazy load (line 318)
        idx2 = RPackageIndex(tmpdir)
        tree = idx2.get_exports_tree()
        assert tree["total_exports"] == 0

def test_r_indexer_bad_rd_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        r_dir = os.path.join(tmpdir, "R")
        os.makedirs(r_dir)
        with open(os.path.join(r_dir, "core.R"), "w") as f:
            f.write("test <- function() {}")
        # Don't create man dir, it should gracefully skip Rd parsing
        idx = RPackageIndex(tmpdir)
        idx.index()
        sig = idx.get_signature("test")
        assert sig is not None
        assert "rd_title" not in sig
        
def test_r_indexer_default_path():
    # Hit line 158
    idx = RPackageIndex()
    assert idx.repo_path.name == "RefinitivR"

def test_python_indexer_edge_cases(mock_python_package):
    # Add a .txt file to hit line 62
    with open(os.path.join(mock_python_package, "test.txt"), "w") as f:
        f.write("ignored")
        
    # Write a py file with class private method, attribute annotation, and complex default
    with open(os.path.join(mock_python_package, "edge.py"), "w") as f:
        f.write('''
import typing
def func(a: typing.Any, b=object()):
    pass

class MyClass:
    def _private(self):
        pass
        
class _PrivateClass:
    pass

def complex_func(a, /, b, *args, c=1, d, **kwargs):
    pass
''')
    
    idx = PythonPackageIndex("lseg.data")
    # Hit lazy load in get_exports_tree (line 141)
    tree = idx.get_exports_tree()
    assert "edge.py" in tree["files"]
    
    sig = idx.get_signature("func")
    assert sig["args"][0]["annotation"] == "typing.Any"
    assert sig["defaults"][0] == "object()"

def test_find_spec_fallback(mocker):
    # Hit lines 42-46
    mocker.patch("importlib.util.find_spec", return_value=None)
    idx = PythonPackageIndex("nonexistent")
    assert idx._locate_package() is None
    
def test_file_fingerprint_oserror(mocker, mock_python_package):
    # Hit lines 27-28
    mocker.patch("os.path.getmtime", side_effect=OSError("Access denied"))
    # Should swallow the OSError and return a hash anyway
    from lseg_mcp.package_indexer import _file_fingerprint
    res = _file_fingerprint(mock_python_package)
    assert isinstance(res, str)
    
def test_r_indexer_not_found_signature(mock_r_package):
    # Hit line 313 (not found fallback)
    idx = RPackageIndex(mock_r_package)
    assert idx.get_signature("this_does_not_exist") is None
