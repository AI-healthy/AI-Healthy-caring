"""Stdio MCP entrypoint; launched locally by MCP2Xiaozhi."""
from mcp.server.fastmcp import FastMCP

from .mcp_tools import get_shiyi_season_card, recommend_shiyi_activity

mcp = FastMCP("ShiYi local demo")
mcp.tool()(get_shiyi_season_card)
mcp.tool()(recommend_shiyi_activity)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
