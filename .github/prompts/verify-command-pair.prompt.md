---
description: "Verify that every createCommand() action string in the Python MCP server has a matching commandHandlers key in the UXP JS plugin. Use after adding or renaming a command to catch mismatches before testing."
agent: agent
tools: [search, file_search, grep_search]
---

Search the codebase for mismatched command pairs between the Python MCP server and the UXP plugin.

## Step 1 — Collect Python action strings

Search [mcp/ps-mcp.py](../../../mcp/ps-mcp.py) for all `createCommand(` calls and extract the first argument (the action string) from each. Also check [mcp/ps-batch-play.py](../../../mcp/ps-batch-play.py) if it contains `createCommand` calls.

## Step 2 — Collect JS handler keys

Search all files under [uxp/ps/commands/](../../../uxp/ps/commands/) for `commandHandlers` object definitions. Extract every key that is registered. Include keys spread from sub-modules into [uxp/ps/commands/index.js](../../../uxp/ps/commands/index.js).

## Step 3 — Find mismatches

Compare the two sets:
- **Python action strings with no matching JS key** → would cause "Unknown Command" at runtime
- **JS handler keys with no matching Python action string** → dead code (not necessarily a bug, but flag it)

## Step 4 — Report

Print a clear table:

| Action string | Python side | JS side | Status |
|---|---|---|---|
| `createDocument` | ✓ | ✓ | OK |
| `missingAction` | ✓ | ✗ | **MISMATCH — will fail** |
| `orphanHandler` | ✗ | ✓ | Dead code |

Summarize the total count of OK pairs, mismatches, and dead code entries.
