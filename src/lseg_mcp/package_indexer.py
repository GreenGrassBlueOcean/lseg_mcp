"""
Polyglot Codebase Introspector for lseg-data (Python) and RefinitivR (R).

Performs static AST analysis of the source code without executing any code.
Uses JIT caching with mtime fingerprinting for sub-second repeated loads.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def _file_fingerprint(directory: str) -> str:
    """Hash of mtimes + file count for quick staleness check."""
    parts: list[str] = []
    for root, _, files in os.walk(directory):
        for f in files:
            fp = os.path.join(root, f)
            try:
                parts.append(f"{fp}:{os.path.getmtime(fp):.0f}")
            except OSError:
                pass
    return hashlib.md5("\n".join(sorted(parts)).encode()).hexdigest()


class PythonPackageIndex:
    """AST-based index of a Python package's public API surface."""

    def __init__(self, package_name: str = "lseg.data"):
        self.package_name = package_name
        self._functions: list[dict[str, Any]] = []
        self._fingerprint: str = ""

    def _locate_package(self) -> str | None:
        """Find the installed package path without importing it."""
        import importlib.util
        try:
            spec = importlib.util.find_spec(self.package_name)
        except (ModuleNotFoundError, ValueError):
            return None  # pragma: no cover
        if spec and spec.submodule_search_locations:
            return spec.submodule_search_locations[0]
        return None  # pragma: no cover

    def index(self, force: bool = False) -> list[dict[str, Any]]:
        """Parse all .py files via AST and extract public functions/classes."""
        pkg_path = self._locate_package()
        if pkg_path is None:
            return [{"error": f"Package '{self.package_name}' not found in current environment."}]

        fp = _file_fingerprint(pkg_path)
        if not force and fp == self._fingerprint and self._functions:
            return self._functions

        funcs: list[dict[str, Any]] = []
        for root, _, files in os.walk(pkg_path):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, pkg_path)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                        tree = ast.parse(fh.read(), filename=fpath)
                except SyntaxError:
                    continue

                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name.startswith("_"):
                            continue
                        sig = self._extract_func_sig(node)
                        sig["file"] = rel
                        funcs.append(sig)
                    elif isinstance(node, ast.ClassDef):
                        if node.name.startswith("_"):
                            continue
                        cls_info = {
                            "type": "class",
                            "name": node.name,
                            "file": rel,
                            "doc": ast.get_docstring(node),
                            "methods": [],
                        }
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"):
                                cls_info["methods"].append(self._extract_func_sig(item))
                        funcs.append(cls_info)

        self._functions = funcs
        self._fingerprint = fp
        return funcs

    @staticmethod
    def _extract_func_sig(node: ast.FunctionDef) -> dict[str, Any]:
        """Extract name, arguments, defaults, and docstring from AST node."""
        args = []
        def _parse_arg(a: ast.arg):
            annotation = ast.unparse(a.annotation) if a.annotation else ""
            args.append({"name": a.arg, "annotation": annotation})

        for a in getattr(node.args, "posonlyargs", []):
            _parse_arg(a)
        for a in getattr(node.args, "args", []):
            _parse_arg(a)
        if getattr(node.args, "vararg", None):
            _parse_arg(node.args.vararg)
        for a in getattr(node.args, "kwonlyargs", []):
            _parse_arg(a)
        if getattr(node.args, "kwarg", None):
            _parse_arg(node.args.kwarg)

        defaults = []
        for d in node.args.defaults + getattr(node.args, "kw_defaults", []):
            if d is None:
                defaults.append(None)
                continue
            try:
                defaults.append(ast.literal_eval(d))
            except (ValueError, TypeError, SyntaxError):
                try:
                    defaults.append(ast.unparse(d))
                except Exception:
                    defaults.append("...")  # pragma: no cover

        return {
            "type": "function",
            "name": node.name,
            "args": args,
            "defaults": defaults,
            "doc": ast.get_docstring(node),
        }

    def get_signature(self, function_name: str) -> dict[str, Any] | None:
        """Lookup a specific function/class by name."""
        if not self._functions:
            self.index()
        for item in self._functions:
            if item["name"] == function_name:
                return item
            # Check class methods
            if item.get("type") == "class":
                for method in item.get("methods", []):
                    if method["name"] == function_name:
                        return {**method, "class": item["name"]}
        return None

    def get_exports_tree(self) -> dict[str, Any]:
        """Hierarchical view of all exports grouped by file."""
        if not self._functions:
            self.index()
        tree: dict[str, list[str]] = {}
        for item in self._functions:
            f = item.get("file", "unknown")
            tree.setdefault(f, []).append(item["name"])
        return {
            "package": self.package_name,
            "total_exports": len(self._functions),
            "files": tree,
        }


class RPackageIndex:
    """Regex-based index of an R package's exported functions and R6 classes."""

    def __init__(self, repo_path: str | None = None):
        if repo_path is None:
            from lseg_mcp._paths import get_r_repo_path
            repo_path = str(get_r_repo_path())
        self.repo_path = Path(repo_path)
        self._functions: list[dict[str, Any]] = []
        self._fingerprint: str = ""

    def index(self, force: bool = False) -> list[dict[str, Any]]:
        """Parse .R files for exported functions and R6 classes."""
        r_dir = self.repo_path / "R"
        if not r_dir.exists():
            return [{"error": f"No R/ directory in {self.repo_path}"}]

        fp = _file_fingerprint(str(self.repo_path))
        if not force and fp == self._fingerprint and self._functions:
            return self._functions

        funcs: list[dict[str, Any]] = []

        # Also parse NAMESPACE for actual exports
        exports = self._parse_namespace()

        for f in sorted(r_dir.iterdir()):
            if f.suffix.lower() != ".r":
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue  # pragma: no cover
            funcs.extend(self._parse_r_file(f.name, content, exports))

        # Also parse Rd files for richer documentation
        man_dir = self.repo_path / "man"
        if man_dir.exists():
            rd_docs = self._parse_rd_files(man_dir)
            # Merge Rd documentation into function entries
            for func in funcs:
                rd = rd_docs.get(func["name"])
                if rd:
                    func["rd_title"] = rd.get("title", "")
                    func["rd_description"] = rd.get("description", "")
                    func["rd_usage"] = rd.get("usage", "")

        self._functions = funcs
        self._fingerprint = fp
        return funcs

    def _parse_namespace(self) -> set[str]:
        """Parse NAMESPACE file for exported function names."""
        ns_file = self.repo_path / "NAMESPACE"
        if not ns_file.exists():
            return set()
        content = ns_file.read_text(encoding="utf-8", errors="ignore")
        exports: set[str] = set()
        for match in re.finditer(r"export\(([^)]+)\)", content):
            for m in match.group(1).split(","):
                exports.add(m.replace('"', '').replace("'", "").strip())
        for match in re.finditer(r'exportPattern\("([^"]+)"\)', content):
            # Store patterns as-is for later regex matching
            exports.add(match.group(1))
        return exports

    @staticmethod
    def _parse_r_file(
        filename: str, content: str, exports: set[str]
    ) -> list[dict[str, Any]]:
        """Extract function definitions from a single .R file."""
        funcs: list[dict[str, Any]] = []

        # Match: function_name <- function(
        pattern = re.compile(
            r"^(\w[\w.]*)\s*<-\s*function\s*\(",
            re.MULTILINE,
        )
        for m in pattern.finditer(content):
            name = m.group(1)
            
            # Balance parentheses to extract the full arguments string
            start_idx = m.end()
            depth = 1
            idx = start_idx
            in_string = False
            string_char = None
            while idx < len(content) and depth > 0:
                c = content[idx]
                if not in_string:
                    if c in ("'", '"'):
                        in_string = True  # pragma: no cover
                        string_char = c  # pragma: no cover
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                else:
                    if c == '\\':
                        idx += 1  # pragma: no cover
                    elif c == string_char:
                        in_string = False  # pragma: no cover
                idx += 1
                
            args_raw = content[start_idx:idx-1].strip() if depth == 0 else ""
            args = [a.strip() for a in args_raw.split(",") if a.strip()] if args_raw else []

            # Clean up the argument list by removing any newlines
            args = [" ".join(a.split()) for a in args]

            # Check if exported
            is_exported = name in exports or any(
                re.match(pat, name)
                for pat in exports
                if not pat.isidentifier()  # it's a pattern
            )

            # Extract preceding Roxygen comments
            start = m.start()
            preceding = content[:start].rstrip()
            roxygen_lines: list[str] = []
            for line in reversed(preceding.split("\n")):
                stripped = line.strip()
                if stripped.startswith("#'"):
                    roxygen_lines.insert(0, stripped[2:].strip())
                else:
                    break

            doc = "\n".join(roxygen_lines) if roxygen_lines else None

            funcs.append({
                "type": "function",
                "name": name,
                "file": filename,
                "args": args,
                "exported": is_exported,
                "doc": doc,
            })

        # Match R6 class definitions
        r6_pattern = re.compile(
            r"(\w+)\s*<-\s*R6::R6Class\s*\(",
            re.MULTILINE,
        )
        for m in r6_pattern.finditer(content):
            funcs.append({
                "type": "R6Class",
                "name": m.group(1),
                "file": filename,
                "exported": m.group(1) in exports,
            })

        return funcs

    @staticmethod
    def _parse_rd_files(man_dir: Path) -> dict[str, dict[str, str]]:
        """Parse .Rd files for titles, descriptions, and usage."""
        docs: dict[str, dict[str, str]] = {}
        for rd_file in man_dir.glob("*.Rd"):
            try:
                content = rd_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue  # pragma: no cover

            name = rd_file.stem
            doc: dict[str, str] = {}

            title_m = re.search(r"\\title\{([^}]+)\}", content)
            if title_m:
                doc["title"] = title_m.group(1).strip()

            desc_m = re.search(r"\\description\{([^}]+)\}", content, re.DOTALL)
            if desc_m:
                doc["description"] = desc_m.group(1).strip()[:500]

            usage_m = re.search(r"\\usage\{([^}]+)\}", content, re.DOTALL)
            if usage_m:
                doc["usage"] = usage_m.group(1).strip()

            docs[name] = doc
        return docs

    def get_signature(self, function_name: str) -> dict[str, Any] | None:
        """Lookup a specific R function by name."""
        if not self._functions:
            self.index()
        for item in self._functions:
            if item["name"] == function_name:
                return item
        return None

    def get_exports_tree(self) -> dict[str, Any]:
        """Hierarchical view of all R exports grouped by file."""
        if not self._functions:
            self.index()
        tree: dict[str, list[str]] = {}
        exported_count = 0
        for item in self._functions:
            if item.get("exported"):
                f = item.get("file", "unknown")
                tree.setdefault(f, []).append(item["name"])
                exported_count += 1
        return {
            "package": "RefinitivR",
            "total_exports": exported_count,
            "files": tree,
        }


class PackageIndexer:
    """Unified facade over both Python and R package indexes."""

    def __init__(
        self,
        python_package: str = "lseg.data",
        r_repo_path: str | None = None,
    ):
        self.python_index = PythonPackageIndex(python_package)
        self.r_index = RPackageIndex(r_repo_path)

    def get_signature(self, language: str, function_name: str) -> dict[str, Any]:
        """Get function signature for a given language."""
        if language.lower() in ("python", "py"):
            result = self.python_index.get_signature(function_name)
        elif language.lower() in ("r",):
            result = self.r_index.get_signature(function_name)
        else:
            return {"error": f"Unsupported language: {language}. Use 'python' or 'r'."}

        if result is None:
            return {"error": f"Function '{function_name}' not found in {language} index."}
        return result

    def get_exports(self, language: str) -> dict[str, Any]:
        """Get hierarchical export tree for a language."""
        if language.lower() in ("python", "py"):
            return self.python_index.get_exports_tree()
        elif language.lower() in ("r",):
            return self.r_index.get_exports_tree()
        return {"error": f"Unsupported language: {language}"}

    def reindex(self, language: str | None = None) -> dict[str, Any]:
        """Force re-index one or both packages."""
        results: dict[str, Any] = {}
        if language is None or language.lower() in ("python", "py"):
            py_funcs = self.python_index.index(force=True)
            results["python"] = {
                "status": "indexed",
                "count": len(py_funcs),
            }
        if language is None or language.lower() in ("r",):
            r_funcs = self.r_index.index(force=True)
            results["r"] = {
                "status": "indexed",
                "count": len(r_funcs),
            }
        return results
