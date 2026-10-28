"""LSD selftest: prove LSD works on this machine with the test packages of this repository.

Run it in a checkout (development, or after a ``git pull``)::

    python selftest/selftest.py [--lsdtools PATH | --lsdtools-python PYTHON] [--keep] [--json]

``lsdtools selftest`` downloads this repository and runs this same file with its own lsdtools, so a
developer and anyone else run exactly the same checks.

Everything happens in a scratch home that shares the installed runtime store (nothing is downloaded
again; with no runtime installed, the scratch home sets one up). The extension packages are copied
there as an author's local packages (the copies have a blank publisher; their code is untouched) and
linked, and their pipelines run headless in the runtime's Python (``pipelines.py``). A project that
pins them opens in a hidden window, which must hold their code for a person's review (linked code is
project code, and only a person enables it) while the window renders through its own path; the
window closes, the project runs headless and the runtime's Python runs. Each step is timed: the report
is also a small benchmark. Standard library only.

The shells (``test/shells``) stand in for the runtime's own shells in a source run, so an installed
runtime, which ships its own, never links them.

Exit status 0 when every step passed, 1 otherwise; ``--json`` prints one ``lsd.selftest.v1`` document.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

SCHEMA = "lsd.selftest.v1"
HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
#: The packages a selftest links, in dependency order (a dependent after what it needs).
PACKAGES = ("data/rows", "data/points", "contrib/dependent")


class StepFailed(Exception):
    pass


class Selftest:
    def __init__(self, lsdtools: list[str], work: Path, target: str | None, *, echo=None) -> None:
        self.lsdtools, self.work, self.target, self.echo = lsdtools, work, target, echo
        self.home = work / "home"
        self.store: Path | None = None
        self.staged: list[tuple[str, str, Path]] = []
        self.steps: list[dict] = []
        self.session: str | None = None

    # -- running lsdtools ------------------------------------------------------------------------------

    def _argv(self, *argv: str, home: bool = True) -> list[str]:
        options = []
        if home:
            options += ["--home", str(self.home)]
            if self.store is not None:
                options += ["--store", str(self.store)]
        if self.target:
            options += ["--target", self.target]
        return [*self.lsdtools, *options, *argv]

    def lsd(self, *argv: str, home: bool = True, timeout: float = 600.0) -> dict:
        """One lsdtools command with --json: its result document."""
        done = subprocess.run(self._argv("--json", *argv, home=home), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise StepFailed(f"lsdtools {' '.join(argv)} printed no result (exit {done.returncode}): "
                             f"{done.stderr.strip()[-400:]}")
        document = json.loads(lines[-1])
        if done.returncode != 0 or document.get("ok") is not True:
            error = document.get("error") or {}
            raise StepFailed(f"lsdtools {' '.join(argv)} exited {done.returncode}: {error.get('message', '')}")
        return document

    def python(self, *argv: str, timeout: float = 600.0) -> subprocess.CompletedProcess:
        """The runtime's own Python (``lsdtools python``)."""
        return subprocess.run(self._argv("python", *argv), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)

    def step(self, name: str, function) -> None:
        started = time.perf_counter()
        row = {"step": name, "ok": False, "ms": 0.0, "detail": ""}
        self.steps.append(row)
        try:
            row["detail"] = function()
            row["ok"] = True
        except (StepFailed, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
            row["detail"] = " ".join(str(exc).split())[:500]
            raise
        finally:
            row["ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            if self.echo is not None:
                self.echo(_line(row))

    # -- the checks ------------------------------------------------------------------------------------

    def find_runtime(self) -> str:
        """Share the installed runtime's store; set one up in the scratch home when there is none."""
        try:
            installed = self.lsd("runtime", "path", home=False)
        except StepFailed:
            self.lsd("setup", timeout=3600)
            return "no runtime was installed: set one up in the scratch home"
        # <store>/versions/<version>/<artifact sha256>
        self.store = Path(installed["data"]["path"]).parents[2]
        return f"shares {self.store}"

    def doctor(self) -> str:
        checks = self.lsd("doctor")["data"]["checks"]
        failed = [f"{row['check']}: {row['detail']}" for row in checks if not row["ok"]]
        if failed:
            raise StepFailed("; ".join(failed))
        return ", ".join(row["check"] for row in checks)

    def stage(self) -> str:
        """Copy each package as an author's local package (blank publisher; code untouched)."""
        for relative in PACKAGES:
            target = self.work / "packages" / relative
            shutil.copytree(REPOSITORY / "test" / relative, target,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            manifest_path = target / "lsd_package.json"
            manifest = json.loads(manifest_path.read_text("utf-8"))
            manifest["publisher"] = ""
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            self.staged.append((manifest["name"], manifest["version"], target))
        return ", ".join(name for name, _version, _folder in self.staged)

    def link(self) -> str:
        for _name, _version, folder in self.staged:
            self.lsd("install", "-e", str(folder))
        listed = {row["name"]: row for row in self.lsd("list")["data"]["packages"]}
        missing = [name for name, _version, _folder in self.staged if listed.get(name, {}).get("source") != "local"]
        if missing:
            raise StepFailed(f"not linked: {', '.join(missing)}")
        return f"{len(self.staged)} linked"

    def pipelines(self) -> str:
        done = self.python(str(HERE / "pipelines.py"))
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise StepFailed(f"pipelines.py exited {done.returncode}: {done.stderr.strip()[-400:]}")
        report = json.loads(lines[-1])
        failed = [f"{row['check']}: {row['detail']}" for row in report["checks"] if not row["ok"]]
        if failed or done.returncode != 0:
            raise StepFailed("; ".join(failed) or f"pipelines.py exited {done.returncode}")
        return ", ".join(f"{row['check']} {row['ms']:.0f} ms" for row in report["checks"])

    def new_project(self) -> str:
        created = self.lsd("new", "project", str(self.work / "projects" / "selftest"))
        self.project = Path(created["data"]["project"])
        return str(self.project)

    def pin_packages(self) -> str:
        """Pin every linked package in the project document, enabled, as a saved project records them."""
        document = json.loads(self.project.read_text("utf-8"))
        names = [name for name, _version, _folder in self.staged]
        document["packages"] = [f"{name}@{version}" for name, version, _folder in self.staged]
        document["package_overrides"] = {"pinned": names}
        document["package_state"] = {"enabled": {name: True for name in names}}
        self.project.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        self.lsd("project", "check", str(self.project))
        listed = json.dumps(self.lsd("project", "packages", str(self.project))["data"])
        missing = [name for name in names if name not in listed]
        if missing:
            raise StepFailed(f"the project does not list {', '.join(missing)}")
        return f"{len(names)} pinned"

    def open_window(self) -> str:
        opened = self.lsd("open", str(self.project), "--window", "hidden", timeout=300)
        self.session = str(opened["data"]["session"])
        return f"session {self.session}"

    def held_for_review(self) -> str:
        """Linked code is project code: the window lists each package but runs none until a person reviews it."""
        described = self.lsd("action", self.session, "describe_project_packages")["data"]["result"]
        rows = {row["name"]: row for row in described.get("packages", [])}
        names = [name for name, _version, _folder in self.staged]
        unlisted = [name for name in names if name not in rows]
        if unlisted:
            raise StepFailed(f"the window does not list {', '.join(unlisted)}")
        running = [name for name in names if rows[name].get("effective") is not False]
        if running:
            raise StepFailed(f"linked code runs without a person's review: {', '.join(running)}")
        return f"{len(names)} listed, none run before review"

    def snapshot(self) -> str:
        picture = self.work / "window.png"
        self.lsd("snapshot", self.session, "--out", str(picture), timeout=300)
        width, height, spread = _png_spread(picture.read_bytes())
        if spread <= 1.0:
            raise StepFailed(f"the window rendered {width}x{height} with a spread of {spread:.2f}: blank")
        return f"{width}x{height}, spread {spread:.1f}"

    def close(self) -> str:
        self.lsd("close", self.session, timeout=300)
        self.session = None
        return "closed"

    def run_project(self) -> str:
        self.lsd("run", str(self.project), timeout=900)
        return "ran headless"

    def runtime_python(self) -> str:
        done = self.python("-c", "import sys, lsdtools; print(sys.version.split()[0])", timeout=300)
        if done.returncode != 0:
            raise StepFailed(f"the runtime's python exited {done.returncode}: {done.stderr.strip()[-400:]}")
        return f"Python {done.stdout.strip()}"


def _png_spread(data: bytes) -> tuple[int, int, float]:
    """(width, height, standard deviation of the image bytes): a blank picture has almost none."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise StepFailed("the snapshot is not a PNG")
    offset, width, height, chunks = 8, 0, 0, []
    while offset < len(data):
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            chunks.append(body)
        offset += 12 + length
    sample = zlib.decompress(b"".join(chunks))[:1 << 22]
    counts = [0] * 256
    for value in sample:
        counts[value] += 1
    total = len(sample) or 1
    mean = sum(value * count for value, count in enumerate(counts)) / total
    variance = sum(count * (value - mean) ** 2 for value, count in enumerate(counts)) / total
    return width, height, variance ** 0.5


def _remove(path: Path) -> None:
    def clear(function, failed, _exc):
        os.chmod(failed, stat.S_IWRITE)
        function(failed)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear)
    else:
        shutil.rmtree(path, onerror=clear)


def _line(row: dict) -> str:
    return f"{'ok  ' if row['ok'] else 'FAIL'} {row['step']:<16} {row['ms']:>9.0f} ms  {row['detail']}"


def _lsdtools_command(executable: str | None, python: str | None) -> list[str]:
    """The lsdtools under test: an executable, a Python whose lsdtools runs (``-m lsdtools._manager``), or
    the one on PATH (else this Python's)."""
    if executable:
        return [executable]
    if python:
        return [python, "-m", "lsdtools._manager"]
    found = shutil.which("lsdtools")
    return [found] if found else [sys.executable, "-m", "lsdtools._manager"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="selftest", description="Prove LSD works on this machine.")
    command = parser.add_mutually_exclusive_group()
    command.add_argument("--lsdtools", help="the lsdtools executable to test (default: lsdtools on PATH)")
    command.add_argument("--lsdtools-python", help="a Python whose lsdtools to test (python -m lsdtools._manager)")
    parser.add_argument("--target", choices=("production", "development"), help="lsdtools' --target")
    parser.add_argument("--keep", action="store_true", help="keep the scratch folder")
    parser.add_argument("--json", action="store_true", help="print one lsd.selftest.v1 document")
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="lsd-selftest-"))
    # Each step is reported as it ends: on stdout, or on stderr while stdout carries the JSON document.
    echo = (lambda line: print(line, file=sys.stderr, flush=True)) if args.json else (lambda line: print(line, flush=True))
    test = Selftest(_lsdtools_command(args.lsdtools, args.lsdtools_python), work, args.target, echo=echo)
    started = time.perf_counter()
    plan = [("runtime", test.find_runtime), ("doctor", test.doctor), ("stage-packages", test.stage),
            ("link-packages", test.link), ("pipelines", test.pipelines), ("new-project", test.new_project),
            ("pin-packages", test.pin_packages), ("open-hidden", test.open_window),
            ("held-for-review", test.held_for_review), ("snapshot", test.snapshot), ("close", test.close),
            ("run-headless", test.run_project), ("runtime-python", test.runtime_python)]
    try:
        for name, function in plan:
            test.step(name, function)
    except Exception:  # noqa: BLE001 - the failed step is recorded; the report says which
        if test.session is not None:
            try:
                test.lsd("close", test.session, timeout=120)
            except Exception:  # noqa: BLE001 - reported below: a hidden window may be left open
                row = {"step": "close-after-failure", "ok": False, "ms": 0.0,
                       "detail": f"session {test.session} may still be open"}
                test.steps.append(row)
                echo(_line(row))
    ok = len(test.steps) == len(plan) and all(row["ok"] for row in test.steps)
    report = {"schema": SCHEMA, "ok": ok, "repository": str(REPOSITORY), "work": str(work) if args.keep else None,
              "total_ms": round((time.perf_counter() - started) * 1000.0, 1), "steps": test.steps}
    if not args.keep:
        _remove(work)
    if args.json:
        print(json.dumps(report))
    else:
        print(f"{'passed' if ok else 'FAILED'} in {report['total_ms'] / 1000.0:.1f} s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
