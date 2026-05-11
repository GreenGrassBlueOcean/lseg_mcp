"""
Rescan & Update Manager for LSEG-MCP.

Orchestrates asynchronous package updates:
 - ``git pull`` for the RefinitivR R repository
 - ``pip install --upgrade lseg-data`` for the Python package
 - Flushes AST caches and triggers re-indexing
 - Returns a diff summary of modified/added functions
"""

from __future__ import annotations

import asyncio
import logging
import sys
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def _run_cmd(cmd: list[str], cwd: str | None = None, stream_name: str | None = None) -> dict[str, Any]:
    """Run a shell command asynchronously and optionally stream its output."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["GCM_INTERACTIVE"] = "never"
    env["PIP_PROGRESS_BAR"] = "off"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=cwd,
            env=env,
        )

        stdout_chunks = []
        stderr_chunks = []

        async def read_stream(stream: asyncio.StreamReader, chunks_list: list[str]):
            buffer = ""
            while True:
                chunk = await stream.read(1024)
                if not chunk:
                    if buffer.strip() and stream_name:
                        logger.info("  [%s] %s", stream_name, buffer.strip())
                    break
                
                decoded = chunk.decode("utf-8", errors="replace")
                chunks_list.append(decoded)
                buffer += decoded
                
                while "\n" in buffer or "\r" in buffer:
                    n_idx = buffer.find("\n")
                    r_idx = buffer.find("\r")
                    
                    if n_idx != -1 and r_idx != -1:
                        split_idx = min(n_idx, r_idx)
                    else:
                        split_idx = max(n_idx, r_idx)
                        
                    line = buffer[:split_idx].strip()
                    if line and stream_name:
                        logger.info("  [%s] %s", stream_name, line)
                    buffer = buffer[split_idx+1:]

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(proc.stdout, stdout_chunks),  # type: ignore
                    read_stream(proc.stderr, stderr_chunks),  # type: ignore
                ),
                timeout=300
            )
            await proc.wait()
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()  # pragma: no cover
            except OSError:
                pass  # pragma: no cover
            return {"returncode": -1, "stdout": "", "stderr": "Command timed out after 300s."}

        return {
            "returncode": proc.returncode,
            "stdout": "".join(stdout_chunks).strip(),
            "stderr": "".join(stderr_chunks).strip(),
        }
    except FileNotFoundError as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


class RescanManager:
    """Manages package updates and cache invalidation."""

    def __init__(
        self,
        r_repo_path: str | None = None,
        python_pip: str | None = None,
    ):
        if r_repo_path is None:
            r_repo_path = str(Path(__file__).resolve().parents[2] / ".lseg_cache" / "RefinitivR")
        self.r_repo_path = Path(r_repo_path)
        if python_pip is None:
            self.python_pip = [sys.executable, "-m", "pip"]
        else:
            self.python_pip = [python_pip] if isinstance(python_pip, str) else python_pip

    async def update_r_package(self) -> dict[str, Any]:
        """Pull or clone the latest RefinitivR from Git."""
        if not self.r_repo_path.exists():
            # Clone it if it doesn't exist (open source fallback)
            repo_url = "https://github.com/GreenGrassBlueOcean/RefinitivR.git"
            self.r_repo_path.parent.mkdir(parents=True, exist_ok=True)
            result = await _run_cmd(
                ["git", "clone", "--depth", "1", "--progress", repo_url, self.r_repo_path.name],
                cwd=str(self.r_repo_path.parent),
                stream_name="CLONE",
            )
            if result["returncode"] == 0:
                return {
                    "status": "cloned",
                    "message": f"Successfully cloned {repo_url} into {self.r_repo_path}",
                }
            return {
                "status": "error",
                "message": result["stderr"] or result["stdout"],
            }

        result = await _run_cmd(
            ["git", "pull", "--rebase", "--progress"],
            cwd=str(self.r_repo_path),
            stream_name="CLONE",
        )
        if result["returncode"] == 0:
            return {
                "status": "updated",
                "message": result["stdout"] or "Already up to date.",
            }
        return {
            "status": "error",
            "message": result["stderr"] or result["stdout"],
        }

    async def update_python_package(self) -> dict[str, Any]:
        """Upgrade lseg-data via pip."""
        cmd = self.python_pip + ["install", "--upgrade", "lseg-data", "--progress-bar", "raw"]
        result = await _run_cmd(cmd, cwd=str(self.r_repo_path.parent), stream_name="PIP")
        if result["returncode"] == 0:
            return {
                "status": "updated",
                "message": result["stdout"],
            }
        return {
            "status": "error",
            "message": result["stderr"] or result["stdout"],
        }

    async def rescan(
        self,
        indexer: Any,
        update_packages: bool = True,
    ) -> dict[str, Any]:
        """
        Full rescan cycle:
        1. (Optional) Pull latest R code and upgrade Python package.
        2. Snapshot current function counts.
        3. Force re-index both packages.
        4. Return a diff summary.
        """
        report: dict[str, Any] = {}

        # Snapshot before
        before_py = len(indexer.python_index._functions)
        before_r = len(indexer.r_index._functions)

        # Update packages if requested
        if update_packages:
            r_result, py_result = await asyncio.gather(
                self.update_r_package(),
                self.update_python_package(),
                return_exceptions=True,
            )
            report["r_update"] = r_result if not isinstance(r_result, Exception) else {"status": "error", "message": str(r_result)}
            report["python_update"] = py_result if not isinstance(py_result, Exception) else {"status": "error", "message": str(py_result)}

        # Re-index
        reindex_result = indexer.reindex()
        report["reindex"] = reindex_result

        # Diff
        after_py = len(indexer.python_index._functions)
        after_r = len(indexer.r_index._functions)

        report["diff"] = {
            "python": {"before": before_py, "after": after_py, "delta": after_py - before_py},
            "r": {"before": before_r, "after": after_r, "delta": after_r - before_r},
        }

        return report
