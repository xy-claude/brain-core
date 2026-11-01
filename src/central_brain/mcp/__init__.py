"""MCP (Model Context Protocol) server — optional extra.

Install with ``pip install brain-core[mcp]``. Without the extra, this
subpackage can still be imported at the package level but anything that
reaches into :mod:`mcp` will raise ImportError at call time.

Public entry point: :func:`central_brain.mcp.server.run_server`.
"""
