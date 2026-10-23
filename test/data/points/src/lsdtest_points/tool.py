"""Two steps over one CSV point set: a load with a point budget and a points-layer delivery.

The entity owns the pipeline; the load step holds the source. Nothing here validates a domain:
the steps exist so the kernel's Grounds can edit parameters, run, fail on a wrong path and recover.
"""
from __future__ import annotations

import math

from lsdtools import Entity, InputArtifact, LayerPayload, Source, Table, Tool

tool = Tool("test.points", label="Test Points")


class PointsEntity(Entity):
    """One load-to-layer pipeline over a CSV point set."""


@tool.load(source_kinds=("file",))
def load_points(src: Source, point_budget: int = 50_000) -> Table:
    """Read the CSV and keep its first *point_budget* rows."""
    paths = src.paths()
    if len(paths) != 1:
        raise ValueError(f"load_points reads exactly one file; got {len(paths)}")
    if isinstance(point_budget, bool) or int(point_budget) <= 0:
        raise ValueError("point_budget must be a positive integer")
    table = Table.read_csv(paths[0])
    return Table(table.arrow.slice(0, int(point_budget)))


@tool.deliver
def show_points(points: InputArtifact, point_size: float = 2.0) -> LayerPayload:
    """Deliver the loaded table as a points layer."""
    size = float(point_size)
    if not math.isfinite(size) or size <= 0.0:
        raise ValueError("point_size must be a finite positive number")
    return LayerPayload(kind="points", tables={"path": points}, style={"point_size": size})


__all__ = ["tool", "PointsEntity", "load_points", "show_points"]
