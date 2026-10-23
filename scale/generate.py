"""Generate a test-package workspace for one performance sweep: N packages x M contributions of chosen kinds.

Each package is ``lsdtest/scale-<kind>-<i>`` (category ``test/scale``) and contributes ``--per-package``
contributions of its one kind, so a measured cost belongs to that kind alone. ``--import-kb`` adds a
module of that many kilobytes the package's code imports (an import cost on purpose, never by
accident); ``--warmup`` declares it as the package's warm-up instead of importing it at load. The
workspace also gets ``scale.lsd``, a project that enables every generated package, and ``scale.json``,
the sweep's parameters. ``--depends F`` makes package ``i`` of a kind depend on the ``F`` packages
before it (``1``: a chain as deep as ``--packages``; more: a denser graph), so a sweep can charge
dependency resolution and ordering to graph depth and fan-in.

    python scale/generate.py --out C:/tmp/sweep --kinds step,main-view --packages 20 --per-package 10

Standard library only; deterministic for the same arguments.
"""
from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

#: kind -> (tool.py body for contribution j, frontend.py body or None). ``{i}`` is the package index.
KINDS = {
    "step": ('''
@tool.shape
def step_{j}(input: Table, factor: int = {j}) -> Table:
    """Contribution {j}: the identity shape step."""
    return input
''', None),
    "entity": ('''
class Scale{i}Entity{j}(Entity):
    """Contribution {j}: an entity type."""


tool.entity(Scale{i}Entity{j}, label="Scale {i} entity {j}")
''', None),
    "command": ('''
@tool.command("scale-{i}-{j}", help="contribution {j}")
def command_{j}() -> int:
    return {j}
''', None),
    "action": ('''
@tool.action("scale/{i}/{j}")
def action_{j}(ctx=None, **values):
    return {{"contribution": {j}}}
''', None),
    "menu-item": ('''
@tool.menu_item("scale_{i}_{j}", label="Scale {i} item {j}", menu="tools")
def menu_item_{j}():
    return {j}
''', None),
    "main-view": ('''
@tool.main_view("scale_{i}_{j}", title="Scale {i} view {j}", instance_policy="single")
def main_view_{j}(host, *, entity=None, view_id):
    from lsdtools import views

    return views.run_log()
''', '''
def main_view_{j}(context, *, entity=None, view_id):
    return context.create_run_log(entity=None, view_id=view_id)


VIEWS.append(MainViewType("scale_{i}_{j}", "Scale {i} view {j}", main_view_{j}, instance_policy="single"))
'''),
}


def _module_name(kind: str, index: int) -> str:
    return f"lsdtest_scale_{kind.replace('-', '_')}_{index}"


def _tool(kind: str, index: int, per_package: int, weight: bool, warmup: bool) -> str:
    imports = ["from __future__ import annotations", "", "from lsdtools import Entity, Table, Tool"]
    if weight and not warmup:
        imports.append("from . import _weight  # noqa: F401 - the sweep's import cost, on purpose")
    body = [f'"""lsdtest/scale-{kind}-{index}: {per_package} contributions of kind {kind}."""',
            *imports, "", f'tool = Tool("test.scale_{kind.replace("-", "_")}_{index}")', ""]
    template = KINDS[kind][0]
    body += [template.format(i=index, j=j).rstrip() + "\n" for j in range(per_package)]
    return "\n".join(body).rstrip() + "\n"


def _frontend(kind: str, index: int, per_package: int) -> str | None:
    template = KINDS[kind][1]
    if template is None:
        return None
    head = [f'"""lsdtest/scale-{kind}-{index}: its frontend declarations."""',
            "from lsdtools.extend import Frontend, MainViewType", "", "VIEWS = []", ""]
    parts = [template.format(i=index, j=j).strip() + "\n" for j in range(per_package)]
    tail = ["", f'frontend = Frontend("lsdtest/scale-{kind}-{index}", tuple(VIEWS))']
    return "\n".join(head + parts + tail) + "\n"


def _manifest(kind: str, index: int, *, frontend: bool, weight: bool, warmup: bool, depends: int = 0) -> dict:
    module = _module_name(kind, index)
    dependencies = {f"lsdtest/scale-{kind}-{before}": ">=1.0.0" for before in range(max(0, index - depends), index)}
    role = {"schema_version": 1, "api_version": "1.0", "entry": f"{module}.tool:tool",
            "dependencies": dict(dependencies), "runtime_dependencies": {}}
    manifest = {
        "_schema_version": 1, "name": f"lsdtest/scale-{kind}-{index}",
        "display_name": f"Scale {kind} {index}", "version": "1.0.0",
        "description": f"A generated sweep package: contributions of kind {kind}.",
        "author": "LSD", "publisher": "lsdtest", "keywords": ["test", "scale", kind], "min_lsd": "1.0.0",
        "tier": "domain", "paid": False, "category": "test/scale", "dependencies": dependencies,
        "tool": f"{module}.tool:tool", "execution": role, "warmup": {},
    }
    if frontend:
        modules = sorted(["__init__.py", "frontend.py"] + (["_weight.py"] if weight else []))
        manifest["frontend"] = {**role, "entry": f"{module}.frontend:frontend", "modules": modules}
    if weight and warmup:
        manifest["warmup"] = {"execution": {"modules": [f"{module}._weight"]}}
    return manifest


def generate(out: Path, kinds: list[str], packages: int, per_package: int, import_kb: int,
             warmup: bool, depends: int = 0) -> dict:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    names = []
    for kind in kinds:
        if kind not in KINDS:
            raise SystemExit(f"unknown kind {kind!r}; known: {', '.join(sorted(KINDS))}")
        for index in range(packages):
            folder = out / "test" / "scale" / f"scale-{kind}-{index}"
            code = folder / "src" / _module_name(kind, index)
            code.mkdir(parents=True)
            frontend = _frontend(kind, index, per_package)
            weight = import_kb > 0
            (code / "__init__.py").write_text(f'"""lsdtest/scale-{kind}-{index}."""\n', encoding="utf-8")
            (code / "tool.py").write_text(_tool(kind, index, per_package, weight, warmup), encoding="utf-8")
            if frontend is not None:
                (code / "frontend.py").write_text(frontend, encoding="utf-8")
            if weight:
                # Distinct bytes per package, so no two packages share a compiled constant.
                blob = (f"{kind}-{index}-" * (import_kb * 1024 // (len(kind) + 4) + 1))[:import_kb * 1024]
                (code / "_weight.py").write_text(f'BLOB = {blob!r}\n', encoding="utf-8")
            (folder / "lsd_package.json").write_text(json.dumps(
                _manifest(kind, index, frontend=frontend is not None, weight=weight, warmup=warmup,
                          depends=depends),
                indent=2) + "\n", encoding="utf-8")
            names.append(f"lsdtest/scale-{kind}-{index}")
    project = {
        "_schema_version": 1, "_type": "Engine",
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "lsdtest-scale:" + ",".join(names))),
        "metadata": {}, "name": "scale sweep", "artifact_workspace": ".", "max_parallel": 1,
        "entities": [], "packages": [f"{name}@1.0.0" for name in names],
        "package_state": {"enabled": {name: True for name in names}},
    }
    (out / "scale.lsd").write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    sweep = {"schema_version": 1, "kinds": kinds, "packages": packages, "per_package": per_package,
             "import_kb": import_kb, "warmup": warmup, "depends": depends, "names": names}
    (out / "scale.json").write_text(json.dumps(sweep, indent=2) + "\n", encoding="utf-8")
    return sweep


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path, help="the workspace to (re)create")
    parser.add_argument("--kinds", default="step", help=f"comma-separated: {', '.join(KINDS)}")
    parser.add_argument("--packages", type=int, default=1, help="packages per kind")
    parser.add_argument("--per-package", type=int, default=1, help="contributions per package")
    parser.add_argument("--import-kb", type=int, default=0, help="a module of this size each package imports")
    parser.add_argument("--warmup", action="store_true", help="declare the weight module as a warm-up")
    parser.add_argument("--depends", type=int, default=0,
                        help="each package depends on this many packages before it (1: a chain)")
    args = parser.parse_args(argv)
    sweep = generate(args.out, [k.strip() for k in args.kinds.split(",") if k.strip()], args.packages,
                     args.per_package, args.import_kb, args.warmup, args.depends)
    print(json.dumps({"out": str(args.out), "packages": len(sweep["names"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
