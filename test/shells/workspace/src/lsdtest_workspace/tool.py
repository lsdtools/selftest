"""The workspace's execution role: the product's project tree behaviour, mounted under this package's id."""
from __future__ import annotations

from lsdtools import Tool

from lsd_desktop_ui.project_tree import project_explorer_tree_extension, project_tree_extension

PACKAGE = "lsdtest/workspace"
tool = Tool(PACKAGE, label="Test Workspace")
tool.tree_extension(project_tree_extension(PACKAGE))
tool.tree_extension(project_explorer_tree_extension(PACKAGE))


__all__ = ["tool"]
