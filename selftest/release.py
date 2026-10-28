"""Build this repository's GitHub release: the test packages as a package-release-v1 collection.

    python selftest/release.py --tag v1.1.0 --out DIR

``DIR`` receives what the release ``vX.Y.Z`` of github.com/lsdtools/selftest carries, beside the suite's own
archive: one ``lsdtest.<name>-<version>-any.zip`` per released package (its folder, as the package directory
an install holds), ``lsd-release.json`` (the collection's release document, naming the tag's commit) and
``SHA256SUMS``. The bytes depend only on the files, so a rebuild of a tag is the same release. Standard
library only. Each file is its blob at the tag; the source tree digest is runtime-store-v1's ``tree_digest`` (natives excluded), as
``lsd_packaging.release`` checks it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
URL = "https://github.com/lsdtools/selftest"
#: The packages the release carries: the extension packages (the shells are the runtime's own).
RELEASED = ("data/rows", "data/points", "contrib/dependent")
NATIVE_SUFFIXES = (".dll", ".so", ".dylib", ".pyd")
_TREE_DOMAIN = b"LSD-RUNTIME-TREE-v1\0"
_STAMP = (1980, 1, 1, 0, 0, 0)


def _files(tag: str, folder: str) -> dict[str, bytes]:
    """The package's files at ``tag``, path -> the blob's bytes (never the working tree's line ends)."""
    listed = subprocess.run(["git", "ls-tree", "-r", "-z", "--format=%(objectname) %(path)", tag, "--", folder],
                            cwd=REPOSITORY, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    files = {}
    for row in filter(None, listed):
        blob, _, name = row.partition(" ")
        data = subprocess.run(["git", "cat-file", "blob", blob], cwd=REPOSITORY, capture_output=True,
                              check=True).stdout
        files[name[len(folder) + 1:]] = data
    return files


def source_tree_sha256(files: dict[str, bytes]) -> str:
    kept = {path: data for path, data in files.items() if not path.lower().endswith(NATIVE_SUFFIXES)}
    folders = {"/".join(path.split("/")[:depth]) for path in kept for depth in range(1, path.count("/") + 1)}
    records = [(path, None) for path in folders] + [(path, data) for path, data in kept.items()]
    digest = hashlib.sha256(_TREE_DOMAIN)
    for path, data in sorted(records, key=lambda record: record[0].encode("ascii")):
        encoded = path.encode("ascii")
        if data is None:
            digest.update(b"D\0" + encoded + b"\0")
        else:
            digest.update(b"F\0" + encoded + b"\0" + str(len(data)).encode("ascii") + b"\0"
                          + hashlib.sha256(data).digest())
    return digest.hexdigest()


def _zip(path: Path, files: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, _STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, files[name])
    return path.read_bytes()


def build(tag: str, out: Path, commit: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for relative in RELEASED:
        files = _files(tag, f"test/{relative}")
        manifest = json.loads(files["lsd_package.json"])
        owner, _, short = manifest["name"].partition("/")
        filename = f"{owner}.{short}-{manifest['version']}-any.zip"
        archive = _zip(out / filename, files)
        rows.append({"package": manifest["name"], "version": manifest["version"],
                     "source_tree_sha256": source_tree_sha256(files),
                     "python_tag": "cp312", "min_lsd": manifest.get("min_lsd", "1.0.0"),
                     "dependencies": manifest.get("dependencies", {}),
                     "runtime_dependencies": manifest.get("runtime_dependencies", {}),
                     "artifacts": [{"kind": "source-package", "platform": "any", "filename": filename,
                                    "size": len(archive), "sha256": hashlib.sha256(archive).hexdigest()}],
                     "examples": [], "catalog": None})
    document = {"schema": "lsd.package-release.v1", "repository": URL, "tag": tag, "commit": commit,
                "packages": rows}
    (out / "lsd-release.json").write_bytes(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())
    assets = sorted(path for path in out.iterdir() if path.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_bytes("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                                             for path in assets).encode("ascii"))
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="release", description="Build the selftest release's package assets.")
    parser.add_argument("--tag", required=True, help="the release tag, vX.Y.Z (it must name HEAD)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    commit = subprocess.run(["git", "rev-list", "-n", "1", args.tag], cwd=REPOSITORY, capture_output=True,
                            text=True, check=True).stdout.strip()
    document = build(args.tag, args.out, commit)
    print(json.dumps({"tag": args.tag, "commit": commit, "packages": [row["package"] for row in document["packages"]],
                      "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
