# Security Remediation Plan

Based on the comprehensive audit of the adb-mcp codebase completed 2026-04-26.

## Design Principles

This project's purpose is to give AI agents full programmatic control of Adobe creative apps. Arbitrary code execution is the feature, not a vulnerability. The security model is therefore **perimeter-based**: secure the transport and authenticate clients, but do not restrict what authenticated clients can do inside Adobe apps.

The full app ecosystem is maintained: Photoshop, Premiere Pro, After Effects, Illustrator, and InDesign.

---

## Phase 1: Perimeter Security

The proxy is the single chokepoint between MCP servers and Adobe plugins. Securing it is the highest-leverage change. All items in this phase are independent and can be worked in parallel.

### 1.1 Add Proxy Authentication

**Files:** `adb-proxy-socket/proxy.js:31-100`, `mcp/socket_client.py:35-97`, all `uxp/*/main.js`, all `cep/*/main.js`

**Problem:** Any local process can connect to the proxy, register as any app, and send/intercept commands. No authentication, no CORS, no origin checking.

**Fix:**
- Generate a random token at proxy startup and write it to a known file (e.g., `~/.adb-mcp/token`)
- Require clients to pass this token in the Socket.IO `auth` handshake option
- Reject connections in the proxy's `connection` handler if `socket.handshake.auth.token` doesn't match
- Update `socket_client.py` to read the token file and pass it during connect
- Update all UXP and CEP `main.js` files to read/receive the token and pass it during connect
- Add explicit CORS config to Socket.IO: `cors: { origin: "http://localhost:*" }`

**Validation:** Connect via `wscat` or a bare script without the token — connection must be refused.

---

### 1.2 Reduce Proxy Buffer and Add Rate Limiting

**File:** `adb-proxy-socket/proxy.js:31-34`

**Problem:** 50MB message buffer (50x the Socket.IO default), no rate limiting, no connection limits.

**Fix:**
- Reduce `maxHttpBufferSize` to `5 * 1024 * 1024` (5MB)
- Add connection limit per IP (e.g., max 10 concurrent connections)
- Add message rate limiting (e.g., max 30 messages/second per client) using a simple token bucket in the `command_packet` handler
- Add `pingTimeout` and `pingInterval` options to disconnect idle clients

---

### 1.3 Restrict UXP Plugin Network Permissions

**Files:** `uxp/ps/manifest.json:72-77`, `uxp/pr/manifest.json:72-77`, `uxp/id/manifest.json:73-77`

**Problem:** All plugins request `"domains": "all"` network access.

**Fix:**
- Change network domains to `["http://localhost:3001"]`
- Keep `"localFileSystem": "fullAccess"` — required for save/export operations, and the REPL needs filesystem access by design

---

### 1.4 Remove Remote Debugging Port

**File:** `cep/com.mikechambers.ai/CSXS/manifest.xml:34-35`

**Problem:** `--remote-debugging-port=8088` allows any local process to attach a debugger and inject code into the Illustrator extension.

**Fix:**
- Remove `<Parameter>--remote-debugging-port=8088</Parameter>`
- Remove `<Parameter>--allow-file-access-from-files</Parameter>` unless specifically needed

---

## Phase 2: Migrate CEP to UXP (After Effects & Illustrator)

CEP is deprecated by Adobe. The current CEP extensions use ExtendScript, which has `system.callSystem()` — the ability to execute arbitrary OS shell commands. UXP does not expose this. Migrating eliminates the only capability that exceeds the intended "control Adobe apps" scope.

### 2.1 Create After Effects UXP Plugin

**Replace:** `cep/com.mikechambers.ae/` (CEP extension)
**Create:** `uxp/ae/` (UXP plugin)

**Architecture:** Match the existing Photoshop UXP plugin pattern:
- `manifest.json` — declare permissions, require `allowCodeGenerationFromStrings: true`
- `main.js` — Socket.IO client connecting to proxy, command dispatch loop
- `commands/` — handler modules

**REPL handler:** Same pattern as planned for Photoshop:
```javascript
const executeScript = async (command) => {
    const code = command.options.code;
    const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
    const fn = new AsyncFunction('app', code);
    return await fn(app);
};
```

The injected globals will differ from Photoshop — AE's UXP DOM exposes `app.project`, composition items, layers via its own object model (no `batchPlay`).

**Curated tools:** Port the existing `getProjectInfo`, `getCompositions`, `getLayers` handlers. They currently build ExtendScript strings and call `evalScript()` — rewrite them to use AE's UXP DOM directly.

**MCP server:** Update `mcp/ae-mcp.py` to replace `execute_extend_script` with `execute_script` (same interface as the PS REPL tool).

---

### 2.2 Create Illustrator UXP Plugin

**Replace:** `cep/com.mikechambers.ai/` (CEP extension)
**Create:** `uxp/ai/` (UXP plugin)

**Architecture:** Same as 2.1, matching the Photoshop UXP pattern.

**REPL handler:** Same `executeScript` pattern. Illustrator's UXP DOM exposes `app.activeDocument`, path items, artboards, etc.

**Curated tools:** Port `getDocuments`, `getActiveDocumentInfo`, `exportPNG`, `openFile`. The current implementations build ExtendScript via string interpolation (which has injection vulnerabilities — `commands.js:65-157`). Rewriting against UXP DOM eliminates the injection vector entirely.

**MCP server:** Update `mcp/ai-mcp.py` to replace `execute_extend_script` with `execute_script`.

---

### 2.3 Delete CEP Extensions

Once UXP plugins are validated:
- Delete `cep/com.mikechambers.ae/`
- Delete `cep/com.mikechambers.ai/`

This eliminates:
- ExtendScript's `system.callSystem()` (OS shell access)
- ExtendScript parameter injection vulnerabilities (`ai/commands.js:65-157`)
- Remote debugging port exposure (`ai/CSXS/manifest.xml:34`)
- The `--allow-file-access-from-files` flag

---

## Phase 3: Input Hygiene & Defensive Hardening

These don't restrict what the REPL can do, but protect against accidental misuse, oversized payloads, and bugs in the curated tools.

### 3.1 Input Validation for Curated Tools

**New file:** `mcp/validators.py`
**Modified files:** All MCP server files

**Problem:** No validation of string lengths, numeric ranges, list sizes, or object structure in any curated tool.

**Fix:**
- Create `validators.py` with helpers:
  - `validate_string(value, max_length=10_000, name="value") -> str`
  - `validate_number(value, min_val, max_val, name="value") -> float`
  - `validate_list(value, max_length=1000, name="value") -> list`
- Apply in each curated `@mcp.tool()` function (not the REPL tools — those accept arbitrary input by design):
  - String params (prompts, text, names): max 10KB
  - Numeric params (opacity 0-100, angle 0-360, radius 0-3000, etc.): range per parameter
  - List params (layer IDs, item names): max 1000 items
- For the JS plugin side: add bounds checking in curated command handlers before calling Adobe APIs

**Note:** The `execute_script` / REPL tools are exempt from input validation beyond a size cap on the code string (e.g., 100KB) and timeout enforcement.

---

### 3.2 Path Validation for Curated Tools

**New file:** `mcp/path_validator.py`
**Modified files:** `mcp/ps-mcp.py`, `mcp/pr-mcp.py`, `mcp/ai-mcp.py`, UXP command handlers with file ops

**Problem:** Curated tools that accept file paths pass them through without validation.

**Fix:**
- Create `validate_path(path: str, must_exist: bool = False) -> str`:
  - Resolve via `pathlib.Path(path).resolve()` to eliminate `..` and symlinks
  - Check resolved path is under user's home directory (configurable)
  - Reject null bytes
- Call in every curated tool that accepts a file path
- JS side: validate before `fs.getEntryWithUrl()` in `uxp/ps/commands/core.js` and `utils.js`

**Note:** The REPL tools are exempt — they have full filesystem access by design.

---

### 3.3 Protect Destructive Operations with History States

**Files:** `uxp/ps/commands/layers.js` (lines 203, 231, 378), `uxp/ps/commands/core.js` (lines 452-462)

**Problem:** `deleteLayer`, `flattenAllLayers`, `deleteSelection` execute immediately with no undo point.

**Fix:**
- Wrap destructive curated commands in Photoshop history states:
  ```javascript
  await app.activeDocument.suspendHistory(async () => {
      layer.delete();
  }, "Delete Layer (MCP)");
  ```
- For `flattenAllLayers`: create a snapshot before flattening
- Apply the same pattern in other app plugins where applicable

---

### 3.4 Add Structured Logging and Audit Trail

**Files:** `mcp/logger.py:25-27`, `adb-proxy-socket/proxy.js`

**Problem:** No timestamps, log levels, request correlation, or persistent audit trail.

**Fix:**
- Python: Use `logging` stdlib with a formatter including ISO timestamp, level, and request ID
- Node: Prefix `console.log` calls with ISO timestamp and level (or use a minimal structured logger)
- Log every command received (action, app, timestamp) and its result (success/failure)
- Log all connection/disconnection events with client identity
- This is especially important given the REPL — you want to be able to see what the AI executed

---

## Phase 4: Code Quality & Bug Fixes

No urgency. Address as part of normal development.

### 4.1 Fix Thread Safety in Socket Client

**Files:** `mcp/socket_client.py:30-33, 99-150`, `mcp/core.py:1-9`

**Problem:** Global variables accessed without locks. Race conditions under concurrent MCP requests.

**Fix:**
- Replace module-level globals in `core.py` with a config dataclass or `threading.local()`
- Protect `sio` connection lifecycle in `socket_client.py` with `threading.Lock()`

---

### 4.2 Fix Bare Except Clause

**File:** `mcp/socket_client.py:129`

**Fix:** Change `except:` to `except Exception:`.

---

### 4.3 Make Configuration Environment-Based

**Files:** All MCP servers (lines ~44-46 each), `adb-proxy-socket/proxy.js:36`

**Fix:**
- Python: `PROXY_URL = os.environ.get("ADB_MCP_PROXY_URL", "http://localhost:3001")`
- Python: `PROXY_TIMEOUT = int(os.environ.get("ADB_MCP_PROXY_TIMEOUT", "20"))`
- Node: `const PORT = parseInt(process.env.ADB_MCP_PROXY_PORT || "3001", 10);`

---

### 4.4 Fix Hardcoded IDs in Harmonize

**File:** `uxp/ps/commands/layers.js:843-844`

**Fix:**
```javascript
"documentID": app.activeDocument.id,
"layerID": layerId,
```

---

### 4.5 Fix Wrong Function Call in InDesign

**File:** `uxp/id/commands/index.js:115`

**Fix:** Change `requiresActiveProject(command)` to `requiresActiveDocument(command)`.

---

### 4.6 Fix Incomplete Error Message

**File:** `mcp/pr-mcp.py:599`

**Fix:** `f"Invalid blur_dimensions '{blur_dimensions}'. Must be one of: {list(dimensions.keys())}"`

---

### 4.7 Fix Resource Leak in Socket Client

**File:** `mcp/socket_client.py:149`

**Fix:** Increase `client_thread.join` timeout to 5 seconds. Log a warning if the thread is still alive after join.

---

### 4.8 Remove Dead Code

**Files:**
- `uxp/pr/commands/index.js:44-65` — commented-out `getProjectContentInfo2`
- `cep/com.mikechambers.ae/commands.js:154-173` — commented-out handlers
- `cep/com.mikechambers.ai/commands.js:320-333` — commented-out execute command

**Fix:** Delete commented-out code. It lives in git history.

---

### 4.9 Complete Type Hints

**Files:** All MCP `.py` files.

**Fix:** Add return types, use `dict[str, Any]` instead of bare `dict`, run `mypy mcp/`.

---

## Implementation Notes

- **Phase 1** is the priority. Proxy auth is the single most important security control — it gates everything else.
- **Phase 2** is the largest effort (~1-2 weeks) but has the best payoff: eliminates ExtendScript's OS-level access, removes injection vulnerabilities, unifies the plugin architecture, and future-proofs against CEP deprecation. Requires testing against each Adobe app with its UXP API.
- **Phase 3** hardens the curated tools without restricting the REPL. Good defense-in-depth.
- **Phase 4** is housekeeping. Do opportunistically.
- **Testing:** No automated test suite exists. Each phase requires manual testing against running Adobe apps — verify both that legitimate commands still work and that the security controls function (e.g., unauthenticated connections rejected, oversized payloads rejected).
- **Deploy Phase 1.1 atomically:** Proxy auth requires updating proxy + all plugins + all MCP servers together.
- **Phase 2 can be incremental:** Migrate one app at a time (e.g., Illustrator first since it has the most curated tools to port, then AE).

## Estimated Scope

| Phase | Effort | Depends On |
|-------|--------|------------|
| Phase 1: Perimeter Security | ~2 days | Nothing |
| Phase 2: CEP → UXP Migration | ~1-2 weeks | Nothing (but deploy after Phase 1) |
| Phase 3: Input Hygiene | ~2-3 days | Nothing |
| Phase 4: Code Quality | ~1 day | Nothing |
