from mcp.core import createCommand, sendCommand

@mcp.tool()
def my_new_tool(layer_id: int, value: str) -> dict:
    """
    One-sentence description shown to the AI as the tool description.

    Args:
        layer_id: The ID of the target layer.
        value: Description of this parameter.
    """
    command = createCommand("myNewCommand", {   # camelCase action name — must match JS commandHandlers key
        "layerId": layer_id,                    # snake_case params become camelCase in options
        "value": value,
    })
    return sendCommand(command)
