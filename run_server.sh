#!/usr/bin/env bash
# Run the LSEG-MCP server via stdio transport on macOS/Linux

# Get the absolute directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Run the python module using the Unix virtual environment structure
exec "$DIR/.venv/bin/python" -m lseg_mcp.server "$@"
