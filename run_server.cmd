@echo off
REM Run the LSEG-MCP server via stdio transport
"%~dp0.venv\Scripts\python.exe" -m lseg_mcp.server %*
