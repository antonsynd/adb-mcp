// Import helpers at the top of the module (if not already imported):
// const { execute, findLayer, getBlendMode } = require("./utils");

const myNewCommand = async (command) => {
    let options = command.options;
    let layerId = options.layerId;          // matches the key sent from Python

    // Always use findLayer() — never iterate the layer tree manually
    let layer = findLayer(layerId);
    if (!layer) {
        throw new Error(`myNewCommand : Could not find layerId : ${layerId}`);
    }

    // ALL Photoshop DOM API calls must be inside execute()
    await execute(async () => {
        layer.someProperty = options.value;
    });

    // Return value becomes response.response in the MCP response.
    // If nothing meaningful to return, omit the return statement.
};

// Register — key must exactly match the action string used in createCommand() on the Python side
const commandHandlers = {
    myNewCommand,
    // ...spread existing handlers from this module
};

module.exports = { commandHandlers };
