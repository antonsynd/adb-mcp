# adb-mcp Agent Guidelines

See [CLAUDE.md](CLAUDE.md) for architecture overview and [PLAN.md](PLAN.md) for fork-specific roadmap.

## Architecture

Three-tier chain: **Python MCP server** → **Node proxy** (`:3001`) → **UXP plugin** (inside Adobe app).

- MCP servers: `mcp/ps-mcp.py` etc. — FastMCP, one per Adobe app
- Proxy: `adb-proxy-socket/proxy.js` — Socket.IO relay, no command logic
- UXP plugin: `uxp/ps/` — runs inside Photoshop, handles commands via `commandHandlers` dispatch

## Adding a Command (Full Checklist)

### 1. Python MCP tool (`mcp/ps-mcp.py`)

```python
@mcp.tool()
def my_new_tool(param1: int, param2: str):
    """Docstring shown to the AI as the tool description."""
    command = createCommand("myActionName", {
        "param1": param1,
        "param2": param2,
    })
    return sendCommand(command)
```

### 2. UXP handler (`uxp/ps/commands/<module>.js`)

```js
const myNewCommand = async (command) => {
    let options = command.options;
    await execute(async () => {        // ALL Photoshop API calls must be inside execute()
        app.activeDocument.something = options.param1;
    });
};
```

Register in the same module's `commandHandlers` export:
```js
const commandHandlers = { myNewCommand, ...existingHandlers };
```

The key **must exactly match** the `action` string passed to `createCommand()`.

## Critical Gotchas

| # | Rule |
|---|------|
| 1 | `action` string in Python **must exactly match** the `commandHandlers` key in JS — typos give an unhelpful "Unknown Command" error |
| 2 | **Every** Photoshop DOM API call must be inside `execute()` (wraps `core.executeAsModal`) — omitting it causes silent failures or permission errors |
| 3 | Python uses `snake_case` params; they map to `camelCase` inside `options` in JS (e.g. `layer_id` → `options.layerId`) |
| 4 | Always use `findLayer(id)` from `utils.js` — never iterate the layer tree manually |
| 5 | `createDocument` and `openFile` are the only commands exempt from the active-document check; adding new doc-creation commands requires updating `requiresActiveDocument()` in `uxp/ps/commands/index.js` |
| 6 | Use `getBlendMode()`, `getAnchorPosition()`, etc. from `utils.js` to convert string enum names to PS constants — passing raw strings crashes |
| 7 | Every successful response already includes the full layer tree and document info — no need to call `getLayers` separately |
| 8 | Image-returning tools (e.g. `getDocumentImage`) must decode `response.response.dataUrl` and return an MCP `Image` object, not the raw dict |

## Commands

```bash
# Install a PS MCP server for development
cd mcp && uv run mcp install --with fonttools --with python-socketio --with mcp --with requests --with websocket-client --with numpy ps-mcp.py

# Run proxy
cd adb-proxy-socket && node proxy.js

# Format Python
black mcp/ && isort mcp/

# Type check Python
mypy mcp/
```

## Key Files

| File | Purpose |
|------|---------|
| `mcp/core.py` | `createCommand()` / `sendCommand()` |
| `mcp/socket_client.py` | Per-command Socket.IO connect/send/disconnect |
| `uxp/ps/commands/index.js` | Command dispatch, active-document guard |
| `uxp/ps/commands/utils.js` | `findLayer()`, enum converters |
| `uxp/ps/main.js` | Plugin entry point; assembles `SUCCESS`/`FAILURE` response |
| `adb-proxy-socket/proxy.js` | Socket.IO relay — no command logic here |
