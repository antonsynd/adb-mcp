<!-- Verified by /verify-plan on 2026-04-26 -->
<!-- Verification result: PASS WITH CORRECTIONS -->

# Plan: Photoshop REPL via MCP

Fork of [mikechambers/adb-mcp](https://github.com/mikechambers/adb-mcp). Goal: expose a JavaScript REPL for Photoshop through MCP so an AI agent can send arbitrary JS code (UXP DOM API, batchPlay, etc.) and get results back.

**Note:** This plan strips the project to Photoshop-only (Phase 3). `SECURITY_REMEDIATION.md` covers the full multi-app ecosystem. If both plans are active, Phase 3 here should be deferred or reconciled — the security remediation's CEP-to-UXP migration (Phase 2) assumes all apps are retained.

## Current State of the Fork

The upstream repo has three tiers:

```
MCP Server (Python, stdio)  -->  Node.js WebSocket Proxy (:3001)  <--  UXP Plugin (inside Photoshop)
```

**What already works:**
- ~60 curated Photoshop tools in `mcp/ps-mcp.py` (create doc, layers, filters, selections, text, adjustments, etc.)
- `mcp/ps-batch-play.py` — a single `call_batch_play_command(commands: list)` tool that sends raw batchPlay JSON descriptors to Photoshop
- `uxp/ps/commands/core.js` has `executeBatchPlayCommand` which receives batchPlay arrays and runs them via `action.batchPlay()`
- The proxy (`adb-proxy-socket/proxy.js`) is a thin Socket.IO relay — no command parsing, just routes packets by application name
- UXP plugin connects as a WebSocket client to the proxy, receives `command_packet` events, dispatches to handler functions, returns results

**What's missing for a REPL:**
- No arbitrary JS execution — the plugin maps action names to hardcoded handler functions. There's no `eval()` or `new Function()` path.
- The UXP manifest (`uxp/ps/manifest.json`) does not declare `allowCodeGenerationFromStrings: true`, which is required for `eval()`/`new Function()` in UXP.
- Socket client (`mcp/socket_client.py`) reconnects per command (stateless). Fine for individual tool calls but adds latency for rapid REPL sequences.
- No screenshot-return in tool responses (there's `getDocumentImage` but it's a separate tool, not automatic).
- Supports 5 Adobe apps (PS, Premiere, AE, Illustrator, InDesign) — we only need Photoshop.

## Changes

### Phase 1: Enable Arbitrary JS Execution (core REPL)

**1.1 — UXP Manifest: allow eval**

File: `uxp/ps/manifest.json`

Add to `requiredPermissions`:
```json
"allowCodeGenerationFromStrings": true
```

This unlocks `eval()` and `new Function()` inside the UXP plugin. Without it, any attempt to execute dynamic code will throw a security error.

**1.2 — UXP Plugin: add `executeScript` command handler**

File: `uxp/ps/commands/core.js`

Add a new handler:
```js
const executeScript = async (command) => {
    let options = command.options;
    let code = options.code;

    // Catch syntax errors from AsyncFunction construction separately from
    // runtime errors during execution — both should return structured errors
    // so the AI agent can iterate, not unhandled exceptions.
    let fn;
    try {
        const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
        fn = new AsyncFunction('app', 'action', 'imaging', 'constants', 'fs', code);
    } catch (e) {
        throw new Error(`SyntaxError in provided code: ${e.message}`);
    }

    let out = await execute(async () => {
        return await fn(app, action, imaging, constants, fs);
    });

    return out;
};
```

Using `new AsyncFunction` instead of `eval()` because:
- Supports `await` (most Photoshop API calls are async)
- Injects `app`, `action`, `imaging`, `constants`, `fs` as parameters — the agent doesn't need to `require()` anything
- Returns the expression value (useful for queries like `return app.activeDocument.layers.length`)

Register it in `commandHandlers` at the bottom of `core.js`:
```js
const commandHandlers = {
    executeScript,        // <-- new
    executeBatchPlayCommand,
    // ... rest unchanged
};
```

**1.3 — MCP Server: add `execute_script` tool**

File: new `mcp/ps-repl.py` (or add to existing `ps-mcp.py`)

A minimal MCP server with the REPL tool:
```python
@mcp.tool()
def execute_script(code: str, timeout: int = 30) -> str:
    """
    Execute arbitrary JavaScript code inside Photoshop's UXP runtime.

    The code runs inside an async function with these variables available:
    - app: Photoshop application object (require('photoshop').app)
    - action: action module (for batchPlay)
    - imaging: imaging module (for pixel access)
    - constants: Photoshop constants
    - fs: UXP filesystem module

    Use 'return' to send values back. Example:
        return app.activeDocument.layers.map(l => ({id: l.id, name: l.name}))

    Args:
        code: JavaScript code to execute
        timeout: Max seconds to wait (default 30, increase for slow operations)
    """
    command = createCommand("executeScript", {"code": code})
    return sendCommand(command)
```

Also keep `call_batch_play_command` as a separate tool — batchPlay with raw JSON descriptors is useful on its own and doesn't require `allowCodeGenerationFromStrings` for cases where we want a more locked-down mode.

**1.4 — MCP Server: add `get_canvas_snapshot` tool**

Essential for the agent to "see" what it's doing:
```python
@mcp.tool()
def get_canvas_snapshot() -> Image:
    """Returns a JPEG screenshot of the current Photoshop canvas."""
    command = createCommand("getDocumentImage", {})
    result = sendCommand(command)
    # [CORRECTED: The response from sendCommand() is the direct packet object:
    # {status, response, document, layers, hasActiveSelection}. There is no
    # intermediate "command" key. The handler return value is at result["response"].
    # Using dataUrl (with prefix stripping) matches the existing get_document_image
    # pattern in ps-mcp.py.]
    if result.get("status") == "SUCCESS" and "response" in result:
        image_data = result["response"]
        data_url = image_data.get("dataUrl")
        if data_url and data_url.startswith("data:image/jpeg;base64,"):
            base64_data = data_url.split(",", 1)[1]
            return Image(data=base64.b64decode(base64_data), format="jpeg")
    return result
```

**[CORRECTED: `get_document_image()` already exists in `mcp/ps-mcp.py` (line 286) and does exactly this — it calls `getDocumentImage`, decodes the dataUrl, and returns an `Image` object. Phase 1.4 is therefore already implemented. Consider simply keeping/renaming the existing tool rather than adding a duplicate.]**

This already works via the existing `getDocumentImage` handler. The correct response key path (verified from proxy.js and ps-mcp.py) is `result["response"]["dataUrl"]`.

### Phase 2: Improve the Socket Layer

**2.1 — Persistent socket connection**

File: `mcp/socket_client.py`

Current behavior: each `send_message_blocking()` call creates a new Socket.IO client, connects, sends, waits, disconnects. For a REPL where you might send 10 commands in quick succession, this is wasteful.

Change to: maintain a single persistent connection. Connect on first use, reuse for subsequent calls. Add reconnect logic if the connection drops. Keep the blocking request-response pattern (emit command, wait for response via queue) but skip the connect/disconnect overhead.

**Failure strategy for in-flight commands:** If the connection drops while a command is awaiting a response, fail that command immediately with a clear error (e.g., "Connection lost while awaiting response — command may or may not have executed"). Do not silently requeue, since the command may have been partially executed on the plugin side. The caller (MCP tool) can decide whether to retry. Track pending commands by ID so the reconnect handler can fail all of them.

**2.2 — Configurable timeout**

The 20-second timeout is too short for operations like generative fill or large batch scripts. Pass timeout from the MCP tool to the socket client. The `execute_script` tool already accepts a `timeout` parameter — thread it through.

### Phase 3: Strip Down to Photoshop-Only

Since this fork is personal and only targets Photoshop:

**3.1 — Remove non-PS apps**

Delete or ignore:
- `mcp/pr-mcp.py` (Premiere)
- `mcp/ae-mcp.py` (After Effects)
- `mcp/ai-mcp.py` (Illustrator)
- `mcp/id-mcp.py` (InDesign)
- `uxp/pr/`, `uxp/id/` (Premiere/InDesign UXP plugins)
- `cep/` (CEP extensions for AE/Illustrator)
- `dxt/pr/` (Premiere DXT manifest)

**3.2 — Consolidate MCP servers**

Upstream has separate entry points: `ps-mcp.py` (curated tools), `ps-batch-play.py` (raw batchPlay). Merge into a single `ps-mcp.py` that includes:
- The curated tools (keep them — they're convenient and well-tested)
- `call_batch_play_command` (from `ps-batch-play.py`)
- `execute_script` (new REPL tool)
- `get_canvas_snapshot` (new)

One MCP server, one stdio process, one config entry in Claude Code.

### Phase 4: Claude Code Integration

**4.1 — MCP server config**

Add to Claude Code's MCP settings (`.claude/settings.json` or global):
```json
{
  "mcpServers": {
    "photoshop": {
      "command": "uv",
      "args": ["run", "--script", "/Users/anton/github/adb-mcp/mcp/ps-mcp.py"],
      "env": {}
    }
  }
}
```

**4.2 — Startup workflow**

Daily usage:
1. Open Photoshop
2. Open the "Photoshop MCP Agent" plugin panel (Plugins menu) and click Connect (or enable "Connect on Launch")
3. Start the proxy: `cd adb-proxy-socket && node proxy.js`
4. Use Claude Code — the MCP server starts automatically when Claude Code invokes a tool

Consider a single launcher script (`start.sh`) that starts the proxy in the background and waits.

**4.3 — REPL system prompt / instructions resource**

The existing `config://get_instructions` resource gives the agent context about Photoshop conventions (color format, bounds format, blend modes, font list). Extend it with REPL-specific guidance:

- When to use `execute_script` (exploratory, multi-step, or novel operations) vs curated tools (well-known operations like create document, apply filter)
- The async function signature and available variables
- Common patterns: `return app.activeDocument.layers.map(...)`, wrapping batchPlay calls, reading pixel data
- Error handling: if `execute_script` throws, the error message comes back in the response — iterate

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `uxp/ps/manifest.json` | Edit | Add `allowCodeGenerationFromStrings: true` |
| `uxp/ps/commands/core.js` | Edit | Add `executeScript` handler + register it |
| `mcp/ps-mcp.py` | Edit | Add `execute_script` and `get_canvas_snapshot` tools, merge in batchPlay tool |
| `mcp/socket_client.py` | Edit | Persistent connection, configurable timeout |
| `mcp/ps-batch-play.py` | Delete | Merged into `ps-mcp.py` |
| `mcp/pr-mcp.py` | Delete | Not needed |
| `mcp/ae-mcp.py` | Delete | Not needed |
| `mcp/ai-mcp.py` | Delete | Not needed |
| `mcp/id-mcp.py` | Delete | Not needed |
| `uxp/pr/` | Delete | Not needed |
| `uxp/id/` | Delete | Not needed |
| `cep/` | Delete | Not needed |
| `dxt/pr/` | Delete | Not needed |

## Testing

1. **Smoke test**: Load UXP plugin, connect to proxy, call `execute_script` with `return app.activeDocument.name` from Claude Code
2. **batchPlay via REPL**: Send a Gaussian blur via `execute_script` using `await action.batchPlay(...)` — verify it applies
3. **Error handling**: Send invalid JS, verify error message propagates back through the chain
4. **Timeout**: Send a long-running operation, verify timeout works and doesn't leave the proxy in a bad state
5. **Canvas snapshot**: Call `get_canvas_snapshot`, verify the agent receives a viewable JPEG
6. **Curated tools still work**: Run a few existing tools (create document, add layer) to ensure nothing broke

## Open Questions

- **Security**: `allowCodeGenerationFromStrings` + `execute_script` means the agent can run anything inside Photoshop. For personal use this is fine. If sharing the repo, document the risk clearly.
- **UXP eval limitations**: Need to verify that `new AsyncFunction()` works in UXP's V8. If not, fall back to `eval('(async () => { ' + code + ' })()')`. The UXP runtime is not a full browser — some JS features may be missing.
- **State between calls**: Each `executeScript` invocation is independent — no shared variables between calls. If the agent needs to build up state across calls, it would need to use a global object on `window` or write to the document. This may be fine in practice since the agent can always re-query state.
- **Proxy auto-start**: Could bundle the proxy into the UXP plugin's lifecycle (start on connect, stop on disconnect) but this adds complexity. A manual `node proxy.js` or a launcher script is simpler for personal use.

## Verification Summary

**Result:** PASS WITH CORRECTIONS
**Verified on:** 2026-04-26
**Plan file:** PLAN.md

### Corrections Made

1. **Section 1.4 — `get_canvas_snapshot` response key path** (critical error): The original code used `result["command"]["response"]["base64Image"]`. The actual response structure from `sendCommand()` places the handler's return value directly at `result["response"]` — there is no `"command"` intermediate key. The proxy emits `packet_response` with the raw `out` object (`{status, response, document, layers, hasActiveSelection}`), not wrapped under a `"command"` key. Corrected to match the pattern in the existing `get_document_image()` in `mcp/ps-mcp.py` (line 286): use `result["response"]["dataUrl"]` with prefix stripping.

2. **Section 1.4 — `get_document_image` already exists** (redundancy): `get_document_image()` in `mcp/ps-mcp.py` (line 286) already does exactly what `get_canvas_snapshot` would do — calls `getDocumentImage`, decodes the `dataUrl`, and returns an `Image` object. Phase 1.4 is effectively already implemented. Added a corrective note so the author can decide whether to rename or consolidate rather than add a duplicate.

### Warnings

- **`allowCodeGenerationFromStrings` manifest field name**: The exact UXP manifest v5 field name for enabling `eval()`/`new AsyncFunction()` cannot be verified without running UXP or consulting Adobe's documentation. The plan correctly acknowledges this in "Open Questions." Ensure this field name is confirmed against official UXP docs before implementation.

- **`executeBatchPlayCommand` returns `o[0]`**: The existing handler returns only the first element of the batchPlay result array (`return o[0]`, core.js line ~529). The plan doesn't mention this when describing the merge in Phase 3.2. When consolidating `ps-batch-play.py` into `ps-mcp.py`, confirm that callers expecting the full array won't be broken.

- **Phase 3.2 `get_canvas_snapshot` in File Change Summary**: The summary table lists adding `get_canvas_snapshot` as new, but it already exists as `get_document_image`. Update the table to reflect keeping/renaming the existing tool.

### Missing Steps Added

- Phase 1.3 / 3.2: When merging `ps-batch-play.py` into `ps-mcp.py`, the `config://get_instructions` resource currently lives in **both** `ps-mcp.py` (line 1532) and `ps-batch-play.py` — the merged file should deduplicate this resource and extend it per Section 4.3.

### Unchecked Claims

- **`allowCodeGenerationFromStrings: true` as the correct UXP manifest field**: UXP plugin documentation is needed to confirm this exact key name and placement within `requiredPermissions`. Cannot verify statically.
- **`new AsyncFunction()` availability in UXP's V8**: Noted in the plan's Open Questions; cannot verify without running the UXP runtime.
