<!-- Verified by /verify-plan on 2026-04-26 -->
<!-- Verification result: PASS WITH CORRECTIONS -->

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
- Update all CEP `main.js` files to read the token file and pass it during connect
- UXP plugins cannot read arbitrary filesystem paths (`~/.adb-mcp/token`) due to UXP's sandboxed filesystem — even with `localFileSystem: fullAccess`. Instead, the proxy should serve the token over a one-time HTTP endpoint at startup (e.g., `GET http://localhost:3001/__token`), or the token should be entered manually in the plugin panel UI. Alternatively, the proxy can issue a challenge-response during the Socket.IO handshake that only local plugins can answer (e.g., the proxy writes a nonce to a known plugin data folder path).
- Add explicit CORS config to Socket.IO using a regex (Socket.IO passes this to the `cors` npm package, which does not support wildcards within origin strings):
  ```js
  cors: { origin: /^http:\/\/localhost(:\d+)?$/ }
  ```

**Validation:** Connect via `wscat` or a bare script without the token — connection must be refused.

---

### 1.2 Reduce Proxy Buffer and Add Rate Limiting

**File:** `adb-proxy-socket/proxy.js:31-34`

**Problem:** 50MB message buffer (50x the Socket.IO default), no rate limiting, no connection limits.

**Fix:**
- Reduce `maxHttpBufferSize` to `5 * 1024 * 1024` (5MB)
- Add connection limit per IP (e.g., max 10 concurrent connections)
- Add message rate limiting (e.g., max 30 messages/second per client) using a simple token bucket in the `command_packet` handler
- Also rate-limit connection attempts and `register` events — the proxy broadcasts commands to all clients registered for an application (`sendToApplication` in `proxy.js:117-133`), so a rogue client that passes auth could silently eavesdrop on all commands for an app without sending any
- Add `pingTimeout` and `pingInterval` options to disconnect idle clients

---

### 1.3 Restrict UXP Plugin Network Permissions

**Files:** `uxp/ps/manifest.json:72-77`, `uxp/pr/manifest.json:72-77`, `uxp/id/manifest.json:72-79`

**Problem:** All plugins request broad network access. PS and PR use `"domains": "all"` (a string). [CORRECTED: InDesign already uses an array format `["all", "http://localhost:3001"]` at lines 72-79, not a simple `"all"` string — the fix for ID only needs to remove `"all"` from the existing array.]

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

**Risk:** After Effects UXP scripting support has historically lagged behind Photoshop's. Before starting this migration, spike on whether AE's UXP runtime supports: Socket.IO client libraries, `AsyncFunction` / `new Function()` with `allowCodeGenerationFromStrings`, and sufficient DOM coverage for the existing curated tools (`getProjectInfo`, `getCompositions`, `getLayers`). If AE UXP is not mature enough, this migration should be deferred and the CEP extension retained with the Phase 1.1 auth token applied via its Node.js context.

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

**Curated tools:** Port the existing `getLayers` handler (the only registered command handler in the CEP plugin's `commandHandlers`). [CORRECTED: `getProjectInfo` and `getCompositions` exist in `cep/com.mikechambers.ae/commands.js` but are NOT registered in `commandHandlers` (lines 170-172 only register `getLayers` and `executeExtendScript`). `getProjectInfo` is called from `main.js:54` to attach context to every response, not as a standalone command. `getCompositions` is not called anywhere. Consider whether to expose these as MCP tools or keep them as internal context helpers.] They currently build ExtendScript strings and call `evalScript()` — rewrite them to use AE's UXP DOM directly.

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
  - Resolve via `pathlib.Path(path).resolve()` to collapse `..` segments and follow symlinks to their real targets (e.g., `~/link -> /etc/passwd` resolves to `/etc/passwd`)
  - Check the **resolved** path is under user's home directory (configurable) — this catches both `..` traversal and symlinks that escape the boundary
  - Reject null bytes
- Call in every curated tool that accepts a file path
- JS side: validate before `fs.getEntryWithUrl()` in `uxp/ps/commands/core.js` and `utils.js`

**Note:** The REPL tools are exempt — they have full filesystem access by design.

---

### 3.3 Protect Destructive Operations with History States

**Files:** `uxp/ps/commands/layers.js` (lines 203, 378), `uxp/ps/commands/selection.js` (line 231), `uxp/ps/commands/utils.js` (line 215)

**Problem:** `deleteLayer`, `flattenAllLayers`, `deleteSelection` execute via the `execute()` wrapper which calls `core.executeAsModal()` but without `historyStateInfo` — so they create a modal scope but not a named, undoable history state.

**Fix:**
- The existing `execute()` helper in `utils.js:215` already calls `core.executeAsModal()`. Extend it to accept and forward `historyStateInfo`:
  ```javascript
  const execute = async (callback, commandName = "Executing command...", historyStateInfo = undefined) => {
      const options = { commandName };
      if (historyStateInfo) {
          options.historyStateInfo = historyStateInfo;
      }
      return await core.executeAsModal(callback, options);
  };
  ```
- Update destructive commands to pass `historyStateInfo`:
  ```javascript
  await execute(async () => {
      layer.delete();
  }, "Delete Layer", { name: "Delete Layer (MCP)", target: app.activeDocument });
  ```
- Note: `suspendHistory()` is the ExtendScript/CEP API and does not exist in UXP. The UXP equivalent is `executeAsModal()` with `historyStateInfo`.
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

**Files:** All MCP server files (`ps-mcp.py:44-46`, `pr-mcp.py:44-46`, `ae-mcp.py:33-35`, `ai-mcp.py:33-35`, `id-mcp.py:39-41`, `ps-batch-play.py:38-40`), `adb-proxy-socket/proxy.js:36` [CORRECTED: line numbers vary per file, not ~44-46 for all; added `ps-batch-play.py` which was missing but also has hardcoded config]

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

**Fix:** Change `requiresActiveProject(command)` to `requiresActiveDocument(command)`. [CORRECTED: `requiresActiveProject` is not just the wrong function — it is completely undefined in this file. `requiresActiveDocument` is defined at line 127. This causes a ReferenceError at runtime for any command that is not `createDocument`.]

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
- `cep/com.mikechambers.ae/commands.js:154-168` — commented-out handlers [CORRECTED: was 154-173, but lines 170-173 are the live `commandHandlers` export — deleting those would break the extension]
- `cep/com.mikechambers.ai/commands.js:323-337` — commented-out execute command [CORRECTED: was 320-333, but the comment block starts at line 323 (`/*`) and ends at line 337 (`}*/`); lines 319-320 are the end of the live `parseAndRouteCommand` function]

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

---

## Verification Summary

**Result:** PASS WITH CORRECTIONS
**Verified on:** 2026-04-26
**Plan file:** SECURITY_REMEDIATION.md

### Corrections Made

1. **Phase 1.3 (InDesign manifest):** Changed line reference from `73-77` to `72-79`. Corrected problem description — InDesign's manifest already uses an array format `["all", "http://localhost:3001"]`, not the simple `"all"` string like PS and PR. Fix for ID only needs to remove `"all"` from the existing array.

2. **Phase 2.1 (AE curated tools):** Corrected claim that `getProjectInfo`, `getCompositions`, `getLayers` are all command handlers. Only `getLayers` and `executeExtendScript` are registered in `commandHandlers` (lines 170-172). `getProjectInfo` is an internal function called from `main.js:54` to attach context to responses. `getCompositions` is defined but not called anywhere.

3. **Phase 4.3 (Config line numbers):** Replaced `"lines ~44-46 each"` with per-file line numbers: `ps-mcp.py:44-46`, `pr-mcp.py:44-46`, `ae-mcp.py:33-35`, `ai-mcp.py:33-35`, `id-mcp.py:39-41`. Added missing `ps-batch-play.py:38-40`.

4. **Phase 4.5 (InDesign bug):** Added clarification that `requiresActiveProject` is not just the wrong function — it is completely undefined in the file. This causes a ReferenceError at runtime, not just incorrect behavior.

5. **Phase 4.8 (Dead code ranges):** Fixed `cep/com.mikechambers.ae/commands.js` from `154-173` to `154-168` — lines 170-173 are the live `commandHandlers` export. Fixed `cep/com.mikechambers.ai/commands.js` from `320-333` to `323-337` — lines 319-320 are the end of the live `parseAndRouteCommand` function.

### Warnings

1. **Phase 2.1:** Before starting the AE UXP migration, verify whether AE's UXP runtime supports Socket.IO client libraries and `AsyncFunction` constructor — the plan already notes this as a spike, which is the right approach.

2. **Phase 2.1:** Consider whether `getProjectInfo` and `getCompositions` should be exposed as MCP tools in the new UXP plugin, or remain as internal context helpers as they are today in the CEP plugin.

3. **Phase 1.1 (UXP token delivery):** The plan proposes three alternatives for delivering auth tokens to UXP plugins (HTTP endpoint, manual entry, challenge-response). A decision should be made before implementation to avoid rework.

### Missing Steps Added

1. **Phase 4.3:** `ps-batch-play.py` was not listed but has identical hardcoded config at lines 38-40 that needs the same environment variable treatment.

### Unchecked Claims

1. **Phase 2.1/2.2:** Claims about AE and Illustrator UXP DOM API availability (`app.project`, composition items, `app.activeDocument`, path items, artboards) cannot be verified from the codebase — these depend on Adobe's UXP runtime for each app, which requires live testing.

2. **Phase 3.1:** Specific numeric ranges for validation (opacity 0-100, angle 0-360, radius 0-3000) were not verified against Adobe API documentation — these are reasonable defaults but should be confirmed against actual API constraints.
