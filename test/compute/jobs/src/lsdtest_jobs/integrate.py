"""One job, ``x += y * dt``, as LLVM IR the product's JIT compiles for this machine's CPU (``lsdtools.jit``), run over
two float64 columns by the runtime engine (``lsdtools.ecs.JobInstance``, the ``lsd_job_v1.h`` contract).

The IR names no target: it compiles on any 64-bit CPU the JIT targets (x86-64, arm64). It reads the job context by
the contract's LP64 offsets (row sets at 8, the step's dt at 72; a row set's rows at 8 and columns at 16; a column is
32 bytes, its data first). The JIT adds no fast-math or contraction, so a multiply and an add stay two roundings:
:func:`reference` is the same arithmetic in NumPy, and the two agree bit for bit.
"""
from __future__ import annotations

import numpy as np

__all__ = ["IR", "SYMBOL", "integrate", "reference"]

SYMBOL = "lsdtest_jobs_integrate"

IR = r"""
%Descriptor = type { i32, i32, i32, i32, ptr, ptr, ptr, ptr, ptr, ptr, ptr, ptr, ptr, ptr, ptr, ptr }

; lsd_job_descriptor_v1: struct_size 112, version 1, determinism 1, no exports; only run.
@lsdtest_jobs_integrate = constant %Descriptor { i32 112, i32 1, i32 1, i32 0, ptr null, ptr null, ptr null,
    ptr @lsdtest_jobs_run, ptr null, ptr null, ptr null, ptr null, ptr null, ptr null, ptr null, ptr null }

define i32 @lsdtest_jobs_run(ptr %context) {
entry:
  %row_sets.at = getelementptr inbounds i8, ptr %context, i64 8
  %row_sets = load ptr, ptr %row_sets.at
  %dt.at = getelementptr inbounds i8, ptr %context, i64 72
  %dt = load double, ptr %dt.at
  %rows.at = getelementptr inbounds i8, ptr %row_sets, i64 8
  %rows = load i64, ptr %rows.at
  %columns.at = getelementptr inbounds i8, ptr %row_sets, i64 16
  %columns = load ptr, ptr %columns.at
  %x = load ptr, ptr %columns
  %y.at = getelementptr inbounds i8, ptr %columns, i64 32
  %y = load ptr, ptr %y.at
  br label %loop
loop:
  %index = phi i64 [ 0, %entry ], [ %next, %body ]
  %done = icmp eq i64 %index, %rows
  br i1 %done, label %exit, label %body
body:
  %x.i = getelementptr inbounds double, ptr %x, i64 %index
  %y.i = getelementptr inbounds double, ptr %y, i64 %index
  %xv = load double, ptr %x.i
  %yv = load double, ptr %y.i
  %step = fmul double %yv, %dt
  %moved = fadd double %xv, %step
  store double %moved, ptr %x.i
  %next = add i64 %index, 1
  br label %loop
exit:
  ret i32 0
}
"""


def integrate(x, y, *, dt: float, steps: int = 1) -> tuple[np.ndarray, str]:
    """``x`` after ``steps`` runs of the compiled job (a new array), and the CPU the JIT compiled it for."""
    from lsdtools.ecs import JobInstance, aligned
    from lsdtools.jit import Jit

    values = np.asarray(x, dtype="float64")
    moving = aligned((len(values),), "float64")
    moving[:] = values
    rate = aligned((len(values),), "float64", readonly=True, fill=np.asarray(y, dtype="float64"))
    with Jit() as jit:
        jit.add(IR)
        cpu = str(jit.target[0])
        with JobInstance(jit.address(SYMBOL), [[(moving, "write"), (rate, "read")]]) as job:
            for _ in range(int(steps)):
                job.run(dt=float(dt))
        return np.array(moving), cpu


def reference(x, y, *, dt: float, steps: int = 1) -> np.ndarray:
    """The same arithmetic in NumPy: one multiply and one add a step, each rounded."""
    values = np.asarray(x, dtype="float64").copy()
    rate = np.asarray(y, dtype="float64")
    for _ in range(int(steps)):
        values = values + rate * float(dt)
    return values
