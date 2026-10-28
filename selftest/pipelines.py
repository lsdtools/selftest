"""The test packages' pipelines, run headless inside the runtime: ``lsdtools python selftest/pipelines.py``.

selftest.py runs this after it links the packages. It loads every installed package as the runtime
does, then runs each extension package's pipeline through the SDK and checks the numbers: lsdtest/rows
(a deterministic table and a scale), lsdtest/points (a CSV load with a point budget) and
lsdtest/dependent (a step over lsdtest/points, so the dependency resolves). It prints one JSON line.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

#: The packages this file runs; the shells are the runtime's own (lsdtools/*) in an installed runtime.
PACKAGES = ("lsdtest/rows", "lsdtest/points", "lsdtest/dependent")


def main() -> int:
    from lsd import PackageManager
    from lsdtools import Engine, Source, Table

    checks = []

    def check(name, function):
        started = time.perf_counter()
        try:
            detail, ok = function(), True
        except Exception as exc:  # noqa: BLE001 - every failure is reported, the next check still runs
            detail, ok = f"{type(exc).__name__}: {exc}", False
        checks.append({"check": name, "ok": ok, "ms": round((time.perf_counter() - started) * 1000.0, 1),
                       "detail": detail})

    manager = PackageManager()

    def load():
        manager.load_all()
        loaded = set(manager.loaded_names())
        missing = [name for name in PACKAGES if name not in loaded]
        if missing:
            raise RuntimeError(f"not loaded: {', '.join(missing)}")
        return f"{len(PACKAGES)} loaded"

    def rows():
        from lsdtest_rows.tool import load_rows, scale_rows

        result = Engine().run(scale_rows(input=load_rows(rows=1000, seed=3), factor=2.0)).raise_on_error()
        x = result.output.arrow.column("x").to_pylist()
        if len(x) != 1000 or x[:3] != [6.0, 20.0, 34.0]:
            raise AssertionError(f"lsdtest/rows produced {len(x)} rows starting {x[:3]}")
        return "1000 rows, x scaled"

    folder = Path(tempfile.mkdtemp(prefix="lsd-selftest-points-"))
    csv = folder / "points.csv"
    Table({"x": [float(i) for i in range(100)], "y": [float(i * 2) for i in range(100)],
           "z": [0.0] * 100}).write_csv(str(csv))

    def points():
        from lsdtest_points.tool import load_points

        result = Engine().run(load_points(src=Source.file(str(csv)), point_budget=40)).raise_on_error()
        if result.output.arrow.num_rows != 40:
            raise AssertionError(f"lsdtest/points kept {result.output.arrow.num_rows} of 40")
        return "40 of 100 points"

    def dependent():
        from lsdtest_dependent.tool import every_nth_point
        from lsdtest_points.tool import load_points

        step = every_nth_point(input=load_points(src=Source.file(str(csv))), stride=4)
        result = Engine().run(step).raise_on_error()
        if result.output.arrow.column("x").to_pylist() != [float(i) for i in range(0, 100, 4)]:
            raise AssertionError("lsdtest/dependent did not keep every fourth point")
        return "every fourth of 100 points"

    check("load-packages", load)
    for name, function in (("pipeline-rows", rows), ("pipeline-points", points),
                           ("pipeline-dependent", dependent)):
        check(name, function)
    shutil.rmtree(folder, ignore_errors=True)
    print(json.dumps({"schema": "lsd.selftest.pipelines.v1", "ok": all(row["ok"] for row in checks),
                      "checks": checks}))
    return 0 if all(row["ok"] for row in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
