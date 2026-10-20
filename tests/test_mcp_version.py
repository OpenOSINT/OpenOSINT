"""The MCP serverInfo version must come from the installed package metadata."""

from importlib.metadata import version

from openosint import mcp_server


def test_initialization_options_report_installed_package_version():
    options = mcp_server._initialization_options()

    assert options.server_version == version("openosint")
