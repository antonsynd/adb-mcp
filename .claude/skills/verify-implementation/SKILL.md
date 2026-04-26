---
name: verify-implementation
description: Verify completed plan implementation, fix gaps/bugs/regressions, and commit fixes
argument-hint: "<path/to/plan.md>"
---

Verify that a plan has been fully and correctly implemented. Reads the plan, checks every step against the actual codebase, runs tests, spawns a team of agents to audit different dimensions, fixes any gaps/bugs/regressions found, and commits all fixes.

## Argument Handling

If `$ARGUMENTS` is non-empty, use it as the path to the plan file.

If `$ARGUMENTS` is empty, find the most recently modified `.md` file in `~/.claude/plans/`:
```bash
ls -t ~/.claude/plans/*.md 2>/dev/null | head -1
```

If no plan file is found (directory doesn't exist or contains no `.md` files), ask the user to provide the plan path explicitly.

Read the plan file completely before proceeding.

## Pre-Verification Checklist

Before spawning any agents, perform these checks yourself:

### 1. Validate plan file

- Confirm the file exists and is readable
- Check for the `/verify-plan` stamp — search for `<!-- Verified by /verify-plan` near the top of the file
  - If **absent**: warn the user that the plan was never verified but proceed anyway
  - If present and result says **NEEDS REVISION**: warn the user that the plan was flagged as needing revision — proceed but note this in the final report
  - If present and result says **PASS** or **PASS WITH CORRECTIONS**: proceed normally
- Check for the `/implement-plan` evidence — look for implementation commits by checking `git log --oneline` for commit messages referencing the plan

### 2. Establish baseline

- Run existing tests (check `mcp/pyproject.toml` for test configuration) — record pass/fail/skip counts as the **current baseline**. If no tests exist, note that.
- Run `black --check mcp/` and `isort --check mcp/` — record whether formatting is clean

### 3. Identify the plan's scope

Extract from the plan:
- Every **file path** mentioned (files that should have been created or modified)
- Every **step/task** described (numbered items, checkboxes, sections describing work)
- Every **MCP tool** added or modified (`@mcp.tool()` functions)
- Every **plugin handler** added or modified (entries in `commandHandlers`)
- Every **manifest permission** added
- Every **proxy change** described
- Every **socket client change** described
- Every **dependency** added (Python or Node)

Build a **completeness checklist** — a structured list of every deliverable the plan describes.

## Team Formation

Create a team using `TeamCreate` with name `verify-implementation`.

Spawn the following agents in parallel:

### Agent 1: Completeness Auditor

```
You are auditing whether a plan was fully implemented in the adb-mcp project (AI control of Adobe Photoshop via MCP protocol).

Architecture: MCP Server (Python) <-> WebSocket Proxy (Node, :3001) <-> UXP Plugin (inside Photoshop)

For EVERY item in the completeness checklist provided:
1. Use Glob to verify referenced files exist
2. Use Grep to verify referenced functions, handlers, tools, and command names exist
3. Use Read to verify the implementation matches what the plan describes (not just that a file exists, but that the content is correct)
4. For MCP tools: verify @mcp.tool() decorator, createCommand() call with correct action name, sendCommand() call
5. For plugin handlers: verify handler function exists and is registered in commandHandlers
6. For manifest changes: verify permissions are present in uxp/ps/manifest.json
7. For proxy changes: verify proxy.js was modified as described
8. For socket client changes: verify socket_client.py was modified as described

Report each item as:
- DONE — fully implemented as described
- PARTIAL — partially implemented (describe what's missing)
- MISSING — not implemented at all
- DIVERGED — implemented differently than planned (describe the divergence)

Output a structured checklist with status for every item.
```

Provide this agent with the full completeness checklist you extracted.

### Agent 2: Regression Detector

```
You are checking for regressions in the adb-mcp project after implementation work.

1. Run any existing tests (check mcp/pyproject.toml for test commands)
   - Report any failing tests
   - Compare against the baseline counts provided

2. Check Python code quality:
   - Run `black --check mcp/` — report any formatting issues
   - Run `isort --check mcp/` — report any import ordering issues

3. Check for consistency between MCP and plugin:
   - Extract all action names from createCommand() calls in mcp/*.py
   - Extract all handler names from commandHandlers in uxp/ps/commands/*.js
   - Report any MCP actions that have no matching plugin handler

4. Check manifest permissions:
   - If any new UXP features are used (eval, filesystem, network), verify they're declared in uxp/ps/manifest.json

5. Check for debug leftovers:
   - Search for console.log, print(), breakpoint(), debugger statements in changed files
   - Flag any that appear to be debug leftovers (not intentional logging)

Output a regression report with PASS/FAIL for each check.
```

Provide this agent with the baseline test counts.

### Agent 3: Architectural Reviewer

```
You are reviewing the architectural quality of recent changes in the adb-mcp project.

Architecture: MCP Server (Python) <-> WebSocket Proxy (Node, :3001) <-> UXP Plugin (inside Photoshop)

Check the git diff to identify changed files:
`git diff main...HEAD --name-only`

For each changed file, review for:

1. **adb-mcp Convention Compliance**
   - MCP tools use @mcp.tool() decorator and createCommand()/sendCommand() from core
   - Plugin handlers use execute() wrapper for Photoshop API calls
   - Action names match between createCommand() and commandHandlers
   - Proxy remains a pure message relay (no business logic added)
   - UXP plugin only acts as socket client
   - Response structure maintained: status, document, layers, hasActiveSelection
   - Socket.IO event names are correct (command_packet, command_packet_response)

2. **Code Quality**
   - No dead code, commented-out code, or debug leftovers
   - No TODO/FIXME comments without context or issue references
   - No magic numbers or strings that should be constants
   - No copy-paste duplication
   - Error handling covers timeouts, disconnects, malformed responses

3. **Security Considerations**
   - New eval/code execution features properly gated by manifest permissions
   - No credentials or secrets hardcoded
   - Input validation where the code crosses trust boundaries (user input -> MCP -> proxy -> plugin)

4. **Maintainability**
   - New code follows existing patterns in its file/module
   - No tight coupling between tiers (MCP server shouldn't depend on plugin internals)
   - Dependencies properly declared in pyproject.toml / package.json

Output findings as: CRITICAL (must fix before merge), WARNING (should fix), SUGGESTION (nice to have).
```

### Agent 4: Test Coverage Auditor

```
You are auditing test coverage for recent changes in the adb-mcp project.

1. Identify changed source files:
   `git diff main...HEAD --name-only`

2. For each changed source file, check if corresponding tests exist:
   - MCP server changes (mcp/*.py) -> test files in mcp/ or a tests/ directory
   - Plugin changes (uxp/ps/) -> manual test plan documented or automated tests
   - Proxy changes (adb-proxy-socket/) -> test files or manual test plan

3. Check test quality (if tests exist):
   - Positive tests (happy path) exist
   - Negative tests (error cases, timeouts, disconnects) exist
   - Edge cases covered (empty input, large payloads, concurrent requests)

4. Check for untested code paths:
   - New MCP tools without any test coverage
   - New plugin handlers without test coverage
   - New error handling paths without negative tests
   - Socket reconnection logic without tests

5. If no automated tests exist:
   - Verify the plan includes a manual testing strategy
   - Check if smoke test instructions are documented

Output a coverage report with: COVERED, PARTIALLY COVERED (missing cases listed), NOT COVERED.
```

## Collect Audit Results

Wait for all four agents to complete and return their reports. Do **not** begin remediation until every agent has reported back. Compile a unified list of issues from all reports.

## Remediation Phase

Address every issue from the unified list:

| Category | Action |
|----------|--------|
| MISSING implementation | Implement it yourself or delegate to an appropriate agent |
| PARTIAL implementation | Complete it yourself or delegate |
| Regression (test failure) | Fix the root cause |
| Architectural violation | Fix the code to follow conventions |
| Missing tests | Write the missing tests |
| Action name mismatch | Fix MCP tool or plugin handler to match |
| Manifest permission missing | Add the required permission |
| Formatting | Run `black mcp/` and `isort mcp/` |
| Dead code / debug leftovers | Remove them |

### Remediation Rules

1. **Fix in priority order**: test regressions > missing implementations > action mismatches > architectural violations > missing tests > formatting/cleanup
2. **Verify each fix**: after fixing an issue, run relevant tests to confirm the fix works
3. **Stage specific files**: never use `git add -A` or `git add .`
4. **Incremental commits**: group related fixes into logical commits, e.g.:
   - `fix: Complete missing implementation for [plan phase X]`
   - `fix: Resolve regression in [component]`
   - `fix: Add missing test coverage for [feature]`
   - `chore: Fix architectural violations from plan implementation`
5. **Include co-author**: all commits must include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
6. **Run tests after all fixes**: verify no new failures introduced

## Final Verification

After all fixes are committed:

1. Run all existing tests — no failures (compare against original baseline — pass count should be equal or higher)
2. `black --check mcp/` and `isort --check mcp/` — clean
3. Verify every `createCommand()` action has a matching `commandHandlers` entry
4. Verify `uxp/ps/manifest.json` has all required permissions
5. `git diff main...HEAD --stat` — summarize all changes

If any final verification step fails, loop back to remediation. Maximum 3 remediation loops — if issues persist after 3 attempts, report them as unresolved.

## Cleanup and Report

After final verification passes:

1. Shut down all teammates via `SendMessage` with `type: "shutdown_request"`
2. Delete the team via `TeamDelete`
3. Present the verification report to the user:

```markdown
## Implementation Verification Report

**Plan:** [plan file path]
**Branch:** [current branch]
**Verified on:** YYYY-MM-DD

### Completeness

| Status | Count |
|--------|-------|
| Fully implemented | N |
| Was partial (now fixed) | N |
| Was missing (now fixed) | N |
| Diverged from plan (acceptable) | N |
| Unresolved | N |

### Regressions

- **Baseline:** X passed, Y failed, Z skipped (or "no tests existed")
- **Post-implementation:** X passed, Y failed, Z skipped
- **Post-remediation:** X passed, Y failed, Z skipped
- **Regressions found:** N (N fixed)

### Architectural Review

- **Critical issues found:** N (N fixed)
- **Warnings found:** N (N fixed)
- **Suggestions:** N

### Test Coverage

- **New tests added (by plan):** N
- **Missing tests added (by remediation):** N
- **Coverage gaps remaining:** N

### Fixes Applied

| Commit | Description | Category |
|--------|-------------|----------|
| abc1234 | ... | missing-impl / regression / arch-violation / missing-test / cleanup |

### Issues Created

| Issue | Title | Reason |
|-------|-------|--------|
| #NNN | ... | deferred work / discovered tech debt |

### Unresolved Items

(List any items that could not be fixed, with explanation)

### Files Changed (total, including plan implementation + fixes)

(output of `git diff main...HEAD --stat`)
```
