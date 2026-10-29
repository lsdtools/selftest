"""A shape step whose work is a native job the product's JIT compiles for this machine: ``x += y * dt``."""
from __future__ import annotations

from lsdtools import Table, Tool

tool = Tool("test.jobs", label="Test Jobs")


@tool.shape
def integrate_rows(input: Table, dt: float = 0.5, steps: int = 1) -> Table:
    """The input with ``x`` moved by ``y * dt``, ``steps`` times, by the JIT-compiled job."""
    from .integrate import integrate

    if isinstance(steps, bool) or int(steps) < 1:
        raise ValueError("steps must be a positive integer")
    import pyarrow as pa

    table = input.arrow
    moved, _cpu = integrate(table.column("x").to_numpy(), table.column("y").to_numpy(), dt=float(dt),
                            steps=int(steps))
    return Table(table.set_column(table.schema.get_field_index("x"), "x", pa.array(moved)))


__all__ = ["tool", "integrate_rows"]
