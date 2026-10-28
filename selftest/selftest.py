"""LSD selftest: prove LSD works on this machine with the test packages of this repository.

Run it in a checkout (development, or after a ``git pull``)::

    python selftest/selftest.py [--lsdtools PATH | --lsdtools-python PYTHON] [--release URL] [--keep] [--json]

``lsdtools selftest`` downloads this repository's release and runs this same file with its own lsdtools, so
a developer and anyone else run exactly the same checks.

Everything happens in scratch homes that share the installed runtime store (nothing is downloaded again;
with no runtime installed, the scratch home sets one up), in two lanes:

- **release** (the GitHub release lane): the test packages install from this repository's release
  (``lsdtools install <release> --unreviewed --project P``: the person who runs the selftest decides),
  sealed for this machine and locked into a new project; their pipelines run in the runtime's Python
  (``pipelines.py``); the project opens in a hidden window, where every package must be effective; one
  package is disabled and enabled again through the window's action door, each change settled on its
  commit receipt; the window is photographed through its own render path and closed, the saved project
  must record the packages enabled, and it runs headless;
- **local** (an author's linked folders): the same packages linked as local packages (their copies have
  a blank publisher; their code is untouched); a project pinning them opens, and the window must list
  them but run none: linked code is project code, and only a person enables it.

Each step is timed: the report is also a small benchmark. Standard library only. The shells
(``test/shells``) stand in for the runtime's own in a source run, so an installed runtime never takes them.

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
VERSION = "1.1.0"
HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
RELEASE = f"https://github.com/lsdtools/selftest@v{VERSION}"
#: The packages a selftest takes, in dependency order (a dependent after what it needs).
PACKAGES = ("data/rows", "data/points", "contrib/dependent")
#: The package disabled and enabled again in the open window: nothing depends on it.
TOGGLED = "lsdtest/rows"
_SETTLED = {"committed", "rejected", "withdrawn", "conflict", "failed"}


class StepFailed(Exception):
    pass


class Selftest:
    def __init__(self, lsdtools: list[str], work: Path, target: str | None, release: str, *, echo=None) -> None:
        self.lsdtools, self.work, self.target, self.release, self.echo = lsdtools, work, target, release, echo
        self.home = work / "home-release"
        self.store: Path | None = None
        self.names: list[str] = []
        self.staged: list[tuple[str, str, Path]] = []
        self.steps: list[dict] = []
        self.session: str | None = None
        self.project: Path | None = None

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
            raise StepFailed(f"lsdtools {' '.join(argv[:3])} exited {done.returncode}: {error.get('message', '')}")
        return document

    def python(self, *argv: str, timeout: float = 600.0) -> subprocess.CompletedProcess:
        """The runtime's own Python (``lsdtools python``)."""
        return subprocess.run(self._argv("python", *argv), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)

    def action(self, kind: str, *params: str, timeout: float = 300.0) -> dict:
        argv = [item for param in params for item in ("-p", param)]
        return self.lsd("action", self.session, kind, *argv, timeout=timeout)["data"]["result"]

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

    # -- the shared checks -----------------------------------------------------------------------------

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

    def new_project(self, name: str) -> str:
        created = self.lsd("new", "project", str(self.work / "projects" / name))
        self.project = Path(created["data"]["project"])
        return str(self.project)

    def open_window(self) -> str:
        opened = self.lsd("open", str(self.project), "--window", "hidden", timeout=300)
        self.session = str(opened["data"]["session"])
        return f"session {self.session}"

    def packages(self) -> dict:
        return {row["name"]: row for row in self.action("describe_project_packages").get("packages", [])}

    def close(self) -> str:
        self.lsd("close", self.session, timeout=300)
        self.session = None
        return "closed"

    # -- the release lane ------------------------------------------------------------------------------

    def install_release(self) -> str:
        """Install the release's packages and lock them into the new project (a person runs the selftest)."""
        installed = self.lsd("install", self.release, "--unreviewed", "--project", str(self.project),
                             timeout=900)["data"]
        self.names = [row["name"] for row in installed["installed"]]
        wanted = [json.loads((REPOSITORY / "test" / relative / "lsd_package.json").read_text("utf-8"))["name"]
                  for relative in PACKAGES]
        if sorted(self.names) != sorted(wanted) or sorted(installed.get("pinned", [])) != sorted(wanted):
            raise StepFailed(f"installed {self.names} and locked {installed.get('pinned')}, not {wanted}")
        lanes = {row["lane"] for row in installed["installed"]}
        if lanes != {"url"}:
            raise StepFailed(f"the release installed through {sorted(lanes)}, not the url lane")
        return f"{len(self.names)} installed from {self.release} and locked into the project"

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

    def effective(self) -> str:
        rows = self.packages()
        inert = [name for name in self.names if rows.get(name, {}).get("effective") is not True]
        if inert:
            raise StepFailed(f"not effective in the window: {', '.join(inert)}")
        return f"{len(self.names)} effective"

    def commit(self, kind: str, *params: str, deadline: float = 120.0) -> dict:
        """Send one project command and wait for its receipt to settle (the host's own signal)."""
        receipt = self.action(kind, *params).get("receipt") or {}
        request = receipt.get("request_id")
        if not request:
            raise StepFailed(f"{kind} returned no receipt")
        limit = time.monotonic() + deadline
        while receipt.get("status") not in _SETTLED:
            if time.monotonic() > limit:
                raise StepFailed(f"{kind} never settled: {receipt.get('status')}")
            receipt = self.action("get_project_command_receipt", f"request_id={request}").get("receipt") or {}
        if receipt["status"] != "committed":
            raise StepFailed(f"{kind} was {receipt['status']}: {receipt.get('message') or ''}")
        return receipt

    def toggle(self) -> str:
        self.commit("set_project_package_enabled", f"package={TOGGLED}", "enabled=false")
        if self.packages().get(TOGGLED, {}).get("effective") is not False:
            raise StepFailed(f"{TOGGLED} is still effective after it was disabled")
        self.commit("set_project_package_enabled", f"package={TOGGLED}", "enabled=true")
        if self.packages().get(TOGGLED, {}).get("effective") is not True:
            raise StepFailed(f"{TOGGLED} is not effective after it was enabled again")
        return f"{TOGGLED} disabled and enabled again, each committed"

    def snapshot(self) -> str:
        picture = self.work / "window.png"
        self.lsd("snapshot", self.session, "--out", str(picture), timeout=300)
        width, height, spread = _png_spread(picture.read_bytes())
        if spread <= 1.0:
            raise StepFailed(f"the window rendered {width}x{height} with a spread of {spread:.2f}: blank")
        return f"{width}x{height}, spread {spread:.1f}"

    def saved(self) -> str:
        document = json.loads(self.project.read_text("utf-8"))
        enabled = document.get("package_state", {}).get("enabled", {})
        lock = document.get("package_lock", {})
        wrong = [name for name in self.names if enabled.get(name) is not True or name not in lock]
        if wrong:
            raise StepFailed(f"the saved project does not lock and enable {', '.join(wrong)}")
        return "the saved project locks and enables every package"

    def run_project(self) -> str:
        self.lsd("run", str(self.project), timeout=900)
        return "ran headless"

    # -- the local lane --------------------------------------------------------------------------------

    def local_home(self) -> str:
        self.home = self.work / "home-local"
        return str(self.home)

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

    def pin_linked(self) -> str:
        """Pin every linked package in the project document, enabled, as a saved project records them."""
        self.new_project("local")
        document = json.loads(self.project.read_text("utf-8"))
        names = [name for name, _version, _folder in self.staged]
        document["packages"] = [f"{name}@{version}" for name, version, _folder in self.staged]
        document["package_overrides"] = {"pinned": names}
        document["package_state"] = {"enabled": {name: True for name in names}}
        self.project.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        self.lsd("project", "check", str(self.project))
        return f"{len(names)} pinned"

    def held_for_review(self) -> str:
        """Linked code is project code: the window lists each package but runs none until a person reviews it."""
        rows = self.packages()
        names = [name for name, _version, _folder in self.staged]
        unlisted = [name for name in names if name not in rows]
        if unlisted:
            raise StepFailed(f"the window does not list {', '.join(unlisted)}")
        running = [name for name in names if rows[name].get("effective") is not False]
        if running:
            raise StepFailed(f"linked code runs without a person's review: {', '.join(running)}")
        return f"{len(names)} listed, none run before review"

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
    return f"{'ok  ' if row['ok'] else 'FAIL'} {row['step']:<18} {row['ms']:>9.0f} ms  {row['detail']}"


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
    parser.add_argument("--release", default=RELEASE, help=f"the GitHub release to install (default: {RELEASE})")
    parser.add_argument("--keep", action="store_true", help="keep the scratch folder")
    parser.add_argument("--json", action="store_true", help="print one lsd.selftest.v1 document")
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="lsd-selftest-"))
    # Each step is reported as it ends: on stdout, or on stderr while stdout carries the JSON document.
    echo = (lambda line: print(line, file=sys.stderr, flush=True)) if args.json else (lambda line: print(line, flush=True))
    test = Selftest(_lsdtools_command(args.lsdtools, args.lsdtools_python), work, args.target, args.release,
                    echo=echo)
    started = time.perf_counter()
    plan = [("runtime", test.find_runtime), ("doctor", test.doctor),
            ("new-project", lambda: test.new_project("release")), ("install-release", test.install_release),
            ("pipelines", test.pipelines), ("open-hidden", test.open_window), ("packages-effective", test.effective),
            ("toggle-package", test.toggle), ("snapshot", test.snapshot), ("close", test.close),
            ("saved-project", test.saved), ("run-headless", test.run_project),
            ("local-home", test.local_home), ("stage-packages", test.stage), ("link-packages", test.link),
            ("pin-linked", test.pin_linked), ("open-linked", test.open_window),
            ("held-for-review", test.held_for_review), ("close-linked", test.close),
            ("runtime-python", test.runtime_python)]
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
    report = {"schema": SCHEMA, "version": VERSION, "ok": ok, "repository": str(REPOSITORY),
              "release": args.release, "work": str(work) if args.keep else None,
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
