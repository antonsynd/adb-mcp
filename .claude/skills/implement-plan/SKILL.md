---
name: implement-plan
description: Implement a plan with a coordinated agent team
argument-hint: "<path/to/plan.md> [--exclude \"section1,section2\"]"
---

Implement a verified plan using a coordinated team of agents. Reads the plan, decomposes it into ordered tasks, spawns appropriate agents, and implements with incremental commits and test-driven development.

## Argument Handling

Parse `$ARGUMENTS` for:
1. **Plan path** — the first argument (a file path ending in `.md`)
2. **--exclude flag** — optional, comma-separated list of section names to skip

If `$ARGUMENTS` is empty, find the most recently modified `.md` file in `~/.claude/plans/`:
```bash
ls -t ~/.claude/plans/*.md | head -1
```

## Pre-Implementation Checklist

Before spawning any agents, perform these checks yourself:

### 1. Read the plan file completely

### 2. Check for verification stamp
- Look for `<!-- Verified by /verify-plan` at the top
- If **absent**: warn the user "This plan has not been verified. Consider running `/verify-plan` first." Ask whether to proceed or stop.
- If stamp says **NEEDS REVISION**: stop and tell the user "This plan was flagged as needing revision. Please address the issues in the Verification Summary before implementing."
- If stamp says **PASS** or **PASS WITH CORRECTIONS**: proceed

### 3. Check git status
- Run `git status` — if there are uncommitted changes, warn the user and ask whether to proceed or stash first

### 4. Check for partially-completed work
- Run `git diff mainline...HEAD --stat` to see what's already been changed on this branch
- If there are existing changes, note them so agents don't duplicate work

### 5. Establish baseline
- Run any existing tests to record pass/fail counts (check `mcp/pyproject.toml` for test configuration)
- If no tests exist yet, note that as the baseline
- Run `black --check mcp/` and `isort --check mcp/` to verify formatting baseline

## Team Formation

Create a team using `TeamCreate` with name `implement-plan`.

Determine which agents to spawn based on what the plan touches:

| Role | Agent Type | Spawn When Plan References |
|------|-----------|---------------------------|
| MCP server work | `general-purpose` | `mcp/*.py`, Python tools, MCP server changes |
| Plugin work | `general-purpose` | `uxp/ps/`, JavaScript handlers, UXP plugin changes |
| Proxy work | `general-purpose` | `adb-proxy-socket/`, Socket.IO, proxy routing |
| Socket/networking | `general-purpose` | `socket_client.py`, connection handling, Socket.IO protocol |
| Final verification | `general-purpose` | Always spawned — final pass after implementation |

## Task Decomposition

Break the plan into commit-sized tasks using `TaskCreate`. Follow these rules:

1. **Ordering**: Tasks must follow the communication chain order: Plugin handler -> Proxy (if needed) -> MCP tool. Plugin-side changes first so the handler exists before the MCP tool tries to call it.
2. **Dependencies**: Use `addBlockedBy` to enforce ordering — MCP tool tasks block on plugin handler tasks, etc.
3. **Granularity**: Each task should be one logical commit (e.g., "Add executeScript handler to UXP plugin", "Add execute_script MCP tool", "Update manifest permissions")
4. **Test tasks**: Create test tasks alongside or immediately after each implementation task, not all at the end
5. **Excluded sections**: Skip any sections listed in the `--exclude` flag
6. **Final tasks**: Always create a "Run final verification" task and a "Run formatting" task, both blocked by all implementation tasks

## Implementation Workflow

Assign tasks to agents via `TaskUpdate` with the `owner` field. Monitor progress via `TaskList`.

### Agent Instructions

Each agent receives these instructions along with their specific task:

```
You are implementing part of a plan for the adb-mcp project (AI control of Adobe Photoshop via MCP protocol).

Architecture: MCP Server (Python) <-> WebSocket Proxy (Node, :3001) <-> UXP Plugin (inside Photoshop)

CRITICAL RULES:
- MCP tools must use @mcp.tool() decorator and createCommand()/sendCommand() from core
- Plugin handlers must use the execute() wrapper for Photoshop API calls
- Action names in createCommand() must match keys in the plugin's commandHandlers
- The proxy is a pure message relay — never add business logic to it
- UXP plugins can only be socket clients, not servers
- New UXP capabilities must be declared in uxp/ps/manifest.json
- New Python deps must be added to mcp/pyproject.toml
- Response structure: status ("SUCCESS"/"FAILURE"), document info, layers tree, hasActiveSelection

WORKFLOW:
1. Read the plan section for your task
2. Read existing code patterns in the area you're modifying
3. Write tests first or alongside implementation (not after)
4. Implement the changes
5. Run relevant tests if they exist
6. Run `black mcp/` and `isort mcp/` for Python files
7. Stage ONLY the specific files you changed (never `git add -A` or `git add .`)
8. Commit with a descriptive message referencing the plan section
9. Mark your task as completed via TaskUpdate
```

### Gap Discovery

During implementation, if agents discover:
- **Tech debt**: Create a GitHub issue with `gh issue create --title "..." --body "..."` (check for duplicates first with `gh issue list --search "..."`)
- **Bugs**: Create a GitHub issue and add a comment referencing it
- **Missing features**: Create a GitHub issue and add a TODO comment referencing it

### Incremental Commits

After each task is completed by an agent:
1. Verify the agent staged only relevant files
2. The commit message should be descriptive and reference the plan section, e.g.: `feat: Add executeScript handler to UXP plugin (plan phase 1.2)`
3. Include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>` in the commit

## Final Verification

After all implementation tasks are complete, the verification agent runs:

1. Run all existing tests — must pass
2. `black --check mcp/` and `isort --check mcp/` — verify formatting is clean
3. Check that every `createCommand()` action has a matching `commandHandlers` entry in the plugin
4. Verify `uxp/ps/manifest.json` has all required permissions for new features
5. `git diff --stat` — summarize all changes made
6. Verify the proxy still has no business logic (pure relay)

## Cleanup and Report

After final verification:

1. Shut down all teammates via `SendMessage` with `type: "shutdown_request"`
2. Delete the team via `TeamDelete`
3. Present a summary report to the user:

```markdown
## Implementation Summary

**Plan:** [plan file path]
**Branch:** [current branch]
**Commits:** [count]

### What Was Done
- (list each completed task with commit hash)

### What Was Deferred
- (list any items deferred with GitHub issue numbers)

### Test Results
- **Baseline:** X passed, Y failed, Z skipped (or "no tests existed")
- **Final:** X passed, Y failed, Z skipped

### Files Changed
(output of `git diff mainline...HEAD --stat`)
```
