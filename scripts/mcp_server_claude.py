#!/usr/bin/env python3
"""
A.I.M. MCP Server — Claude Code Edition

Thin wrapper that imports the shared MCP server from the aim backend
and patches the project-context resource to read CLAUDE.md instead of GEMINI.md.
"""
import os
import sys

# Ensure the shared src is importable
aim_claude_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(aim_claude_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Import the shared MCP server (this registers all tools)
from mcp_server import mcp, AIM_ROOT

# Override the project-context resource to read CLAUDE.md
@mcp.resource("aim://project-context")
def get_project_context() -> str:
    """Provides the high-level project context from CLAUDE.md."""
    path = os.path.join(aim_claude_root, "CLAUDE.md")
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()
    return "CLAUDE.md not found."

if __name__ == "__main__":
    mcp.run(transport="stdio")
