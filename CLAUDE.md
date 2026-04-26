# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

adb-mcp enables AI control of Adobe creative tools (Photoshop, Premiere Pro, InDesign, After Effects, Illustrator) via the MCP protocol. It is a fork of [mikechambers/adb-mcp](https://github.com/mikechambers/adb-mcp).

## Architecture

Three-tier communication chain:

```
AI Client <-> MCP Server (Python, stdio) <-> WebSocket Proxy (Node, :3001) <-> Adobe Plugin <-> Adobe App
```

- **MCP Servers** (`mcp/`): Python processes using `FastMCP` from the `mcp` SDK. One per Adobe app (`ps-mcp.py`, `pr-mcp.py`, `ae-mcp.py`, `ai-mcp.py`, `id-mcp.py`). Each defines `@mcp.tool()` functions that build command dicts via `core.createCommand()` and send them via `socket_client.send_message_blocking()`.
- **WebSocket Proxy** (`adb-proxy-socket/proxy.js`): Socket.IO relay on port 3001. Routes `command_packet` events by application name. No command parsing — purely a message router between MCP servers and plugins.
- **UXP Plugins** (`uxp/ps/`, `uxp/pr/`, `uxp/id/`): Run inside Adobe apps (Photoshop, Premiere, InDesign). Connect to the proxy as Socket.IO clients. Receive commands, dispatch to handler functions, return results. Photoshop handlers are split across `commands/core.js`, `commands/layers.js`, `commands/selection.js`, `commands/filters.js`, `commands/adjustment_layers.js`, `commands/layer_styles.js`.
- **CEP Extensions** (`cep/com.mikechambers.ae/`, `cep/com.mikechambers.ai/`): For After Effects and Illustrator. Use ExtendScript via `CSInterface.evalScript()` instead of UXP.
- **Shared modules** (`mcp/core.py`, `mcp/socket_client.py`, `mcp/logger.py`, `mcp/fonts.py`): `core.py` creates command dicts. `socket_client.py` handles per-command Socket.IO connect/send/disconnect cycles. `fonts.py` enumerates system PostScript font names via fontTools.

The proxy is needed because UXP plugins can only connect to sockets as clients, not listen as servers.

## Adding New Functionality

To add a new command for an Adobe app:

1. **MCP server**: Add a `@mcp.tool()` function in the app's MCP file (e.g., `mcp/ps-mcp.py`). Use `createCommand("actionName", {options})` and `sendCommand(command)`.
2. **Plugin**: Add a handler function in the app's commands module (e.g., `uxp/ps/commands/core.js`). Register it in the `commandHandlers` object exported from that module. The `action` string in the command dict must match the key in `commandHandlers`.

## Commands

### MCP Servers (from `mcp/` directory)

```bash
# Install an MCP server for development (registers with Claude Desktop)
uv run mcp install --with fonttools --with python-socketio --with mcp --with requests --with websocket-client --with numpy ps-mcp.py

# Run directly for testing
uv run ps-mcp.py
```

### Proxy Server

```bash
cd adb-proxy-socket && node proxy.js
# Or use prebuilt executables from GitHub releases
```

### Python Dependencies

Managed via `mcp/pyproject.toml`. Key dependencies: `mcp[cli]`, `python-socketio`, `fonttools`, `pillow`, `numpy`, `websocket-client`. Dev tools: `pytest`, `black`, `isort`, `mypy`.

```bash
# Format
black mcp/
isort mcp/

# Type check
mypy mcp/

# Tests (if any exist)
pytest mcp/
```

### Proxy Dependencies

```bash
cd adb-proxy-socket && npm install
```

## Key Conventions

- All MCP servers connect to the proxy at `http://localhost:3001` with a 20-second default timeout.
- Command flow: Python MCP tool -> `core.createCommand(action, options)` -> `socket_client.send_message_blocking(command)` -> proxy -> plugin handler -> response back through the chain.
- The socket client reconnects per command (stateless). Each `send_message_blocking()` creates a new Socket.IO connection.
- Plugin responses include `status` ("SUCCESS" or "FAILURE"), and for Photoshop: current `document` info, `layers` tree, and `hasActiveSelection`.
- `ps-batch-play.py` is a separate MCP server exposing raw batchPlay command execution.
- After Effects and Illustrator use `execute_extend_script` for arbitrary ExtendScript execution (no curated tool wrappers).

## Fork-Specific Context

This fork's `PLAN.md` describes adding a JavaScript REPL (`executeScript`) for Photoshop, persistent socket connections, and stripping down to Photoshop-only. See `PLAN.md` for implementation details.
