# LSEG-MCP Server

`lseg-mcp` is an asynchronous, introspective Model Context Protocol (MCP) server that acts as a definitive bridge between LLMs and the London Stock Exchange Group (LSEG) data APIs.

It enables AI agents to confidently draft perfectly formatted financial data retrieval pipelines in both Python (`lseg-data`) and R (`RefinitivR`).

## Features

- **Semantic Mapping Engine**: Translates legacy Refinitiv COA codes to industry-specific modern LSEG FCC formulas automatically. Handles additive arrays, ASR bracket notation, and industry routing.
- **Polyglot Code Generation**: Merges mapping-aware field resolution with live AST-verified function signatures to generate syntactically correct boilerplate in Python and R.
- **AST-Driven Introspection**: Performs static analysis to read function signatures directly from the Python and R source code without executing unsafe scripts.
- **Continuous Synchronization**: Automatically performs `git pull` and `pip install --upgrade` to ensure the MCP server is always synchronized with the underlying SDKs.
- **Headless Observability**: Features a hardened `os.fsync()` log streaming pipeline ensuring reliable cross-platform telemetry capture.

## Prerequisites

- Python 3.11+
- Git
- Access to LSEG Workspace (running in the background for live data retrieval)

## Installation

Clone the repository and install it in editable mode:

```bash
git clone https://github.com/<org>/lseg-mcp.git
cd lseg-mcp
pip install -e ".[dev]"
```

## Configuration

The server operates over standard input/output (stdio) using the JSON-RPC 2.0 protocol.

### MCP Client Configuration

Point your MCP client (like Claude Desktop or Antigravity) to the executable:

```json
{
  "mcpServers": {
    "lseg-mcp": {
      "command": "C:\\path\\to\\lseg_mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "lseg_mcp.server"
      ]
    }
  }
}
```

### Environment Variables

All paths are relative to the project root by default, but you can override them:
- `LSEG_MAPPING_PATH`: Absolute path to the Excel mapping matrix.
- `REFINITIVR_PATH`: Absolute path to the RefinitivR repository (cloned automatically if missing).

## Running the Server Locally

If you need to debug the server independently of an MCP client, you can use the cross-platform launch scripts which automatically tail the internal logs:

**Windows:**
```cmd
run_server.cmd
```

**macOS / Linux:**
```bash
./run_server.sh
```

## Monitoring & Observability

Because the server runs headlessly within the MCP client, all console outputs (like `git clone` or `pip install` progress) and JSON-RPC traffic are hidden.

You can monitor the server's real-time internal status by tailing its log file. Open a separate terminal and run:

**Windows (PowerShell):**
```powershell
Get-Content -Path .lseg_cache\startup.log -Wait
```

**macOS / Linux:**
```bash
tail -f .lseg_cache/startup.log
```

## Testing

The project maintains **98% absolute line coverage**. To run the test suite:

```bash
pytest --cov=src --cov-report=term-missing tests/
```

## Architecture

For a comprehensive dive into the internal semantic mapping engine, the AST parser bracket-balancing algorithms, and the polyglot generator templates, please see [ARCHITECTURE.md](ARCHITECTURE.md).
