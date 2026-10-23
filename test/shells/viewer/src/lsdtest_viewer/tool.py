"""The viewer has no execution-role contribution: the view is a frontend declaration."""
from lsdtools import Tool

tool = Tool("lsdtest/viewer", label="Test Viewer")

__all__ = ["tool"]
