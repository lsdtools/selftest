"""A shape step over the point table that lsdtest/points loads, and an entity built from both packages."""
from __future__ import annotations

from lsdtools import Source, Table, Tool

from lsdtest_points.tool import PointsEntity, load_points

tool = Tool("test.dependent", label="Test Dependent")


@tool.shape
def every_nth_point(input: Table, stride: int = 2) -> Table:
    """Keep every *stride*-th row."""
    if isinstance(stride, bool) or int(stride) <= 0:
        raise ValueError("stride must be a positive integer")
    import pyarrow as pa

    return Table(input.arrow.take(pa.array(range(0, input.arrow.num_rows, int(stride)), type=pa.int64())))


def thinned_points(path: str, stride: int = 2) -> PointsEntity:
    """A points entity whose load (from lsdtest/points) is thinned by this package's step."""
    entity = PointsEntity("thinned points")
    load = load_points(src=Source.file(path))
    entity.add(load)
    entity.add(every_nth_point(input=load, stride=stride))
    return entity


__all__ = ["tool", "every_nth_point", "thinned_points"]
