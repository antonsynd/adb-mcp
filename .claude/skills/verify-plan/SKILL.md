---
name: verify-plan
description: Verify a plan for accuracy and architectural soundness
argument-hint: "<path/to/plan.md>"
---

Verify a plan file for accuracy against the actual adb-mcp codebase. Reads the plan, extracts every verifiable claim, checks each against the codebase, and edits the plan directly to fix inaccuracies. Adds a verification stamp at the top.

## Argument Handling

If `$ARGUMENTS` is non-empty, use it as the path to the plan file.

If `$ARGUMENTS` is empty, find the most recently modified `.md` file in `~/.claude/plans/` using:
```bash
ls -t ~/.claude/plans/*.md | head -1
```

Read the plan file completely before proceeding.

## Verification Dimensions

Check each dimension in order. For each claim found, verify it against the actual codebase using Glob, Grep, and Read tools.

### 1. Structural Accuracy

Verify every concrete reference in the plan:
- **File paths**: Use Glob to confirm every referenced file/directory exists
- **Function/method/class names**: Use Grep to confirm they exist where claimed
- **Parameter signatures**: Read the actual code and compare signatures
- **Line number references**: Read the file and verify content at those lines
- **Module imports**: Verify import paths match actual module locations

Flag as error: any path, name, or code that doesn't exist. Fix inline if the correct reference can be determined.

### 2. Consistency with Project Conventions

Check the plan follows adb-mcp project rules:
- **Three-tier architecture**: Changes should respect the MCP Server <-> WebSocket Proxy <-> UXP Plugin chain
- **Command flow**: Python MCP tool -> `core.createCommand(action, options)` -> `socket_client.send_message_blocking(command)` -> proxy -> plugin handler -> response
- **Action name matching**: The `action` string in `createCommand()` must match a key in the plugin's `commandHandlers` object
- **Socket.IO protocol**: All communication goes through the proxy on port 3001 — no direct MCP-to-plugin connections
- **MCP tool pattern**: Tools must use `@mcp.tool()` decorator and use `createCommand()`/`sendCommand()` from core
- **Plugin handler pattern**: Handlers receive a command object, use `execute()` wrapper for Photoshop API calls, return results
- **Response structure**: Plugin responses include `status` ("SUCCESS"/"FAILURE"), `document` info, `layers` tree, and `hasActiveSelection`
- **No command parsing in proxy**: The proxy is a pure message relay — no business logic
- **Python deps**: Must be listed in `mcp/pyproject.toml`
- **Node deps**: Must be listed in `adb-proxy-socket/package.json`

Flag as warning: any convention violation. Add a note explaining the correct convention.

### 3. Architectural Soundness

Verify architectural claims and decisions:
- **UXP plugin constraints**: UXP plugins can only be socket clients (not servers) — verify plan doesn't assume the plugin can listen for connections
- **UXP manifest permissions**: Any new capabilities (eval, network, filesystem) must be declared in `uxp/ps/manifest.json`
- **Socket client behavior**: Verify plan is consistent with current socket client behavior (per-command connect/disconnect vs persistent)
- **Proxy routing**: Verify plan respects the proxy's routing by application name
- **Handler registration**: New command handlers must be registered in the appropriate `commandHandlers` export
- **Module boundaries**: MCP servers in `mcp/`, proxy in `adb-proxy-socket/`, plugin code in `uxp/ps/`

Flag as error: architectural violations that would break the communication chain. Flag as warning: suboptimal design.

### 4. Correctness

Check that proposed changes will actually work:
- **Python code**: Will the proposed Python code run? Check for obvious type errors, missing imports, wrong function signatures
- **JavaScript code**: Will the proposed JS code run in UXP's runtime? Check for Node.js-only APIs that don't exist in UXP
- **Socket.IO events**: Verify event names match between sender and receiver (`command_packet`, `command_packet_response`)
- **UXP API availability**: For Photoshop API calls, verify the APIs exist in the UXP DOM (`require('photoshop')`)
- **batchPlay descriptors**: If plan includes batchPlay JSON, verify descriptor structure is plausible
- **Error handling**: Does the plan address connection failures, timeouts, and malformed responses?

Flag as warning: unchecked edge cases. Flag as error: demonstrably incorrect claims.

### 5. Completeness

Check that nothing is missing:
- **All tiers covered**: If adding a new command, verify plan covers MCP tool + proxy (if routing changes) + plugin handler
- **Tests specified**: Every implementation change should have corresponding test additions or a testing strategy
- **Manifest updates**: New UXP permissions declared if needed
- **Dependency additions**: New Python/Node packages listed
- **Configuration**: Any new env vars, ports, or settings documented
- **Error paths**: Plan should describe what happens when things fail (timeout, disconnect, invalid input)

Flag as warning: missing steps. Add them as suggestions in the verification summary.

## Output

After verification, edit the plan file directly:

### 1. Add verification stamp at the very top of the file

```markdown
<!-- Verified by /verify-plan on YYYY-MM-DD -->
<!-- Verification result: [PASS / PASS WITH CORRECTIONS / NEEDS REVISION] -->
```

Use:
- **PASS** — No errors found, at most minor suggestions
- **PASS WITH CORRECTIONS** — Errors found and corrected inline; plan is now accurate
- **NEEDS REVISION** — Fundamental architectural or correctness issues that require the plan author's judgment

### 2. Add a Verification Summary section at the end of the plan

```markdown
## Verification Summary

**Result:** [PASS / PASS WITH CORRECTIONS / NEEDS REVISION]
**Verified on:** YYYY-MM-DD
**Plan file:** [path]

### Corrections Made
- (list each inline correction with before/after)

### Warnings
- (list each warning with explanation)

### Missing Steps Added
- (list suggestions for missing steps)

### Unchecked Claims
- (list any claims that couldn't be verified, with reason)
```

### 3. Fix errors inline

For each error found, edit the plan text directly to correct it. Mark corrections with `[CORRECTED: reason]` so the author can review changes.

Present a brief summary to the user after editing is complete.
