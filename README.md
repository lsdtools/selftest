# lsd-test-packages — the packages the LSD kernel is tested and measured with

The product (`lsd-product`) is the kernel: only what an empty project needs. Its tests, Grounds,
examples and benchmarks never use a real package from `lsd-packages`. They use the packages here:
purpose-built, minimal and deterministic, so one test exercises one kernel path and one benchmark
measures one cost. A real package's behaviour is tested in that package. The product enforces this
(`engine/lsd/tests/test_product_separation.py`).

## The rules

1. **Owner `lsdtest`.** Every package here is `lsdtest/<name>` (import root `lsdtest_<name>`), in a
   `test/...` category. Nothing here is published.
2. **One concern per package.** A package contributes one kind of thing, so its activation, first
   use, memory and idle cost belong to that alone.
3. **Deterministic and cheap by default.** No network, no randomness without a seed, no work at import.
   Cost is added on purpose, by the scale generator, never by accident.
4. **The kernel's public surface only.** A package imports `lsdtools` (plus `lsd_project` records and
   `lsd_desktop_ui.project_tree` for the workspace shell), like any package author would.
5. **Found by the testkit.** `LSD_TEST_PACKAGES_ROOT` names this workspace (default: the product's
   sibling `lsd-test-packages`); Grounds stage packages from here by id.

## Layout

```
test/
  shells/workspace   lsdtest/workspace   the entity tree, the inspector and the tables, with the
                                         product's project tree behaviour
  shells/pipeline    lsdtest/pipeline    the pipeline graph and the run log
  shells/viewer      lsdtest/viewer      the 3D viewer view (declares the render warm-up)
  data/points        lsdtest/points      a point set from a CSV file: a load with a point budget and a
                                         points-layer delivery
  data/rows          lsdtest/rows        a deterministic table and a cheap shape: the engine's per-entity
                                         and per-step pipeline cost (project_scale_v1)
  contrib/dependent  lsdtest/dependent   a step over lsdtest/points: dependency resolution and order
scale/
  generate.py        N packages x M contributions of one kind each (step, entity, command, action,
                     menu-item, main-view), with an optional import weight or warm-up and an optional
                     dependency graph (--depends F: each package on the F before it), into a scratch
                     workspace with a project enabling them all: the sweeps behind the product's
                     engine/lsd/benchmarks/activation_v1.py
```

The kernel's Grounds keep their projects beside them in the product; they name packages from here.
