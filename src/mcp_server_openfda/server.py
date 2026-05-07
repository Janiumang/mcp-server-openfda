"""SignalBridge for openFDA - MCP server entry point.

This is the v0.1 scaffolding. It exposes one trivial tool (`ping`) to verify
MCP wiring end-to-end. The four real openFDA tools - search_drug_adverse_events,
count_adverse_events, get_drug_label, search_drug_recalls - are added next.
"""

from mcp.server.fastmcp import FastMCP

# The server's MCP name. This is what Claude Desktop displays in its
# MCP servers list and what tool calls are routed against.
mcp = FastMCP("signalbridge-openfda")


@mcp.tool()
def ping() -> str:
    """Verify the SignalBridge openFDA MCP server is reachable.

    Use this to confirm end-to-end MCP wiring before calling data tools.
    Returns a fixed identification string. Takes no arguments.
    """
    return "SignalBridge openFDA MCP server v0.1.0 - alive."


def main() -> None:
    """Run the MCP server over stdio transport.

    stdio is the transport Claude Desktop uses to talk to local MCP servers:
    Claude Desktop spawns this process, writes JSON-RPC requests to its stdin,
    and reads responses from its stdout.
    """
    mcp.run()


if __name__ == "__main__":
    main()
