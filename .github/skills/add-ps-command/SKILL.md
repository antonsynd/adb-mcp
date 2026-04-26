---
name: add-ps-command
description: 'Scaffold a new Photoshop command end-to-end: Python @mcp.tool() in mcp/ps-mcp.py AND the matching JS handler in uxp/ps/commands/. Use when adding, implementing, or wiring up a new Photoshop MCP tool, command, or action.'
argument-hint: 'Describe the new command (e.g. "rotate layer by degrees")'
---

# Add a Photoshop Command

Scaffolds both ends of a new command: the Python MCP tool and the UXP JS handler. Both must be created together — the action string must match exactly or the command fails silently with "Unknown Command".

## When to Use
- Adding a new Photoshop capability to the MCP server
- Wiring up a new `@mcp.tool()` function
- Implementing the JS handler for an existing Python stub

## Procedure

### Step 1 — Choose where the JS handler lives

Open [uxp/ps/commands/index.js](../../../uxp/ps/commands/index.js) to see which modules handle similar commands:
- `core.js` — document and app-level operations
- `layers.js` — layer CRUD, properties, transforms
- `selection.js` — selections and masks
- `filters.js` — filter effects
- `adjustment_layers.js` — adjustment layer creation
- `layer_styles.js` — layer style properties

### Step 2 — Pick an `action` name

Use `camelCase` matching the verb+noun pattern of existing commands (e.g. `rotateLayer`, `setLayerOpacity`). This string must be identical in both Python and JS.

### Step 3 — Add the Python tool

In [mcp/ps-mcp.py](../../../mcp/ps-mcp.py), add a new tool following the template in [templates/python-tool.py](./templates/python-tool.py).

Key rules:
- Function name uses `snake_case`; the `action` string inside `createCommand()` uses the `camelCase` name chosen in Step 2
- Python param names map to `camelCase` in JS `options` (e.g. `layer_id` → `options.layerId`)
- No try/except needed — errors bubble up automatically

### Step 4 — Add the JS handler

In the chosen module, add the handler following the template in [templates/js-handler.js](./templates/js-handler.js).

Key rules:
- **All** Photoshop DOM API calls must be inside `execute(async () => { ... })` — this wraps `core.executeAsModal`
- Use `findLayer(id)` from `utils.js` — never iterate the layer tree manually
- Use `getBlendMode()`, `getAnchorPosition()`, etc. from `utils.js` for enum conversion — raw strings crash

### Step 5 — Register the handler

In the same module's `commandHandlers` export object, add the new function:

```js
const commandHandlers = {
    myNewCommand,   // <-- add here
    ...existingHandlers,
};
```

The key name **must exactly match** the `action` string from Step 2.

### Step 6 — Verify the pair

Run `/verify-command-pair` to confirm the Python `createCommand` action string has a matching JS `commandHandlers` key.

### Step 7 — Special cases

- If the new command **creates a document** (no active document required), add it to the exclusion list in `requiresActiveDocument()` in [uxp/ps/commands/index.js](../../../uxp/ps/commands/index.js)
- If the new command **returns an image** (base64 dataUrl), the MCP tool must decode `response.response.dataUrl` and return an MCP `Image` object — see `get_document_image` in `ps-mcp.py` for the pattern
