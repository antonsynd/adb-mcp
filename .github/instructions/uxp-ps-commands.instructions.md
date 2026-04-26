---
description: "Use when writing or editing Photoshop UXP plugin command handlers in uxp/ps/commands/. Covers the execute() wrapper requirement, layer lookup, enum conversion, and handler registration."
applyTo: "uxp/ps/commands/*.js"
---

# UXP Photoshop Command Handler Rules

## Mandatory: `execute()` wrapper

**Every** Photoshop DOM API call must be wrapped in `execute()`:

```js
await execute(async () => {
    layer.opacity = 80;           // ✓ inside execute
});
layer.opacity = 80;               // ✗ will silently fail or throw permission error
```

`execute()` wraps `core.executeAsModal` — it is not optional.

## Layer lookup

Always use `findLayer(id)` from `utils.js` — never iterate `app.activeDocument.layers` manually:

```js
let layer = findLayer(options.layerId);
if (!layer) throw new Error(`commandName : Could not find layerId : ${options.layerId}`);
```

## Enum conversion

Never pass raw strings to Photoshop constant parameters — use the helpers from `utils.js`:

```js
getBlendMode(options.blendMode)       // string → PS BlendMode constant
getAnchorPosition(options.anchor)     // string → PS AnchorPosition constant
```

## Registering handlers

The key in `commandHandlers` must **exactly match** the `action` string used in `createCommand()` on the Python side:

```js
const commandHandlers = {
    myNewCommand,     // must match createCommand("myNewCommand", ...) in Python
    ...existingHandlers,
};
```

## Active document guard

All commands require an active open document **except** `createDocument` and `openFile`. If adding a new document-creation command, add it to `requiresActiveDocument()` in `index.js`.

## Response structure

Every successful command automatically includes `document`, `layers`, and `hasActiveSelection` in the response — do not call `getLayers` manually. Only return data from the handler that is specific to this command.
