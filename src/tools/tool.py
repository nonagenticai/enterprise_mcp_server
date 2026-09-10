from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

# Create a separate FastMCP instance for tools
tool_mcp = FastMCP(name="Tool Server")


@tool_mcp.tool()  # Use tool_mcp not mcp
def add(a: int, b: int) -> int:
    """Add two integers together."""
    return a + b


@tool_mcp.tool()  # Use tool_mcp not mcp
def subtract(a: int, b: int) -> int:
    """Subtract one integer from another."""
    return a - b
