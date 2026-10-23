"""A load that makes a deterministic table and a shape that scales one column.

No I/O and no domain: a project of N entities, each a load and M shapes, charges the engine's own
per-entity and per-step cost (planning, caching, publication, persistence) with real but tiny work.
"""
from __future__ import annotations

from lsdtools import Entity, Table, Tool

tool = Tool("test.rows", label="Test Rows")


class RowsEntity(Entity):
    """One load followed by shapes."""


@tool.load
def load_rows(rows: int = 1000, seed: int = 0) -> Table:
    """*rows* rows of three columns, the same for the same arguments."""
    if isinstance(rows, bool) or int(rows) < 1:
        raise ValueError("rows must be a positive integer")
    count, offset = int(rows), int(seed)
    return Table({"id": list(range(count)),
                  "x": [float((i * 7 + offset) % 101) for i in range(count)],
                  "y": [float((i * 13 + offset) % 97) for i in range(count)]})


@tool.shape
def scale_rows(input: Table, factor: float = 1.0) -> Table:
    """The input with ``x`` multiplied by *factor*."""
    return input.with_column("x", input["x"] * float(factor))


__all__ = ["tool", "RowsEntity", "load_rows", "scale_rows"]
