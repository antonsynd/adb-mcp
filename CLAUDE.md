# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

adb-mcp enables AI control of Adobe Photoshop via the MCP protocol. It is a fork of [mikechambers/adb-mcp](https://github.com/mikechambers/adb-mcp), stripped down to Photoshop-only. The upstream repo supported 5 Adobe apps; this fork focuses exclusively on Photoshop and adds a JavaScript REPL (`execute_script`) for arbitrary code execution.

## Architecture

Three-tier communication chain:

```
AI Client <-> MCP Server (Python, stdio) <-> WebSocket Proxy (Node, :3001) <-> UXP Plugin <-> Photoshop
```

- **MCP Server** (`mcp/ps-mcp.py`): Python process using `FastMCP` from the `mcp` SDK. Defines `@mcp.tool()` functions (curated tools + `execute_script` REPL + `call_batch_play_command`) that build command dicts via `core.createCommand()` and send them via `socket_client.send_message_blocking()`.
- **WebSocket Proxy** (`adb-proxy-socket/proxy.js`): Socket.IO relay on port 3001. Routes `command_packet` events by application name. No command parsing — purely a message router.
- **UXP Plugin** (`uxp/ps/`): Runs inside Photoshop. Connects to the proxy as a Socket.IO client. Receives commands, dispatches to handler functions, returns results. Handlers are split across `commands/core.js` (including `executeScript`), `commands/layers.js`, `commands/selection.js`, `commands/filters.js`, `commands/adjustment_layers.js`, `commands/layer_styles.js`, and `commands/utils.js`. Aggregated via `commands/index.js`.
- **Shared modules** (`mcp/core.py`, `mcp/socket_client.py`, `mcp/logger.py`, `mcp/fonts.py`, `mcp/validators.py`, `mcp/path_validator.py`): `core.py` creates command dicts. `socket_client.py` handles per-command Socket.IO connect/send/disconnect cycles. `fonts.py` enumerates system PostScript font names via fontTools. `validators.py` validates input parameters at the MCP tool boundary. `path_validator.py` restricts file paths to the user's home directory (configurable via `ADB_MCP_ALLOWED_PATH_PREFIX` env var).
- **DXT packaging** (`dxt/`): Contains manifest and build output for packaging the UXP plugin as a `.dxt` distributable.

The proxy is needed because UXP plugins can only connect to sockets as clients, not listen as servers.

## Adding New Functionality

To add a new curated command:

1. **MCP server**: Add a `@mcp.tool()` function in `mcp/ps-mcp.py`. Use `createCommand("actionName", {options})` and `sendCommand(command)`.
2. **Plugin**: Add a handler function in the appropriate commands module under `uxp/ps/commands/`. Export it in that module's `commandHandlers` object. The `action` string in the command dict must match the key in `commandHandlers`. Handlers are aggregated in `commands/index.js`.

For exploratory or novel operations, use `execute_script` (JS REPL) or `call_batch_play_command` (raw batchPlay) instead of adding new curated tools.

## Commands

### MCP Server (from `mcp/` directory)

```bash
# Install the MCP server for development (registers with Claude Desktop)
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
```

### Proxy Dependencies

```bash
cd adb-proxy-socket && npm install
```

## Key Conventions

- The MCP server connects to the proxy at `http://localhost:3001` with a 20-second default timeout.
- Command flow: Python MCP tool -> `core.createCommand(action, options)` -> `socket_client.send_message_blocking(command)` -> proxy -> plugin handler -> response back through the chain.
- The socket client reconnects per command (stateless). Each `send_message_blocking()` creates a new Socket.IO connection.
- Plugin responses include `status` ("SUCCESS" or "FAILURE"), current `document` info, `layers` tree, and `hasActiveSelection`.
- `execute_script` sends arbitrary JS code to Photoshop's UXP runtime via the `executeScript` handler. `call_batch_play_command` sends raw batchPlay descriptors. Both are in `ps-mcp.py`.
- Input validation (`validators.py`, `path_validator.py`) applies to curated tools only — REPL tools are intentionally exempt.

## Related Docs

- `PLAN.md` — fork roadmap: JS REPL, persistent sockets, Photoshop-only strip-down.
- `SECURITY_REMEDIATION.md` — security hardening plan for the multi-app ecosystem.
- `AGENTS.md` — agent-specific guidelines (points back here for architecture).
