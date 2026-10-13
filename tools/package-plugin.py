#!/usr/bin/env python3
"""Build or verify the deterministic HamDraw ComfyUI plugin archive.

The archive unpacks straight into ComfyUI's `custom_nodes/` directory, so the
`hamdraw_chp/` folder is the top-level entry rather than a nested one. Like
the happ archive this is byte-for-byte reproducible: fixed timestamps, sorted
entries, no compression surprises.

The version number is never written here: it is read from
``hamdraw_chp/version.py`` so the zip name and the number the plugin reports
over HTTP can never drift apart.

Usage:
  python3 tools/package-plugin.py           # build release/hamdraw-comfyui-plugin-v<version>.zip
  python3 tools/package-plugin.py --check   # rebuild in memory and compare digests
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
# The plugin package *is* this repository's root since the CHP split: there is no
# `comfyui-plugin/` level any more (`hamdraw_chp/` and `README.md` sit next to this
# script's parent). Keeping SOURCE = ROOT also keeps VERSION_FILE / ARCHIVE /
# plugin_directories() derived, so nothing else needs touching.
SOURCE = ROOT
VERSION_FILE = SOURCE / "hamdraw_chp" / "version.py"
FIXED_TIMESTAMP = (2026, 9, 17, 0, 0, 0)
ENTRIES = ("hamdraw_chp", "README.md")

# Runtime files that live inside the package directory and hold credentials. The
# zip is published on the website, so these must never travel in it -- they are
# listed by name on purpose (a name list is easier to audit than a glob), and a
# build that finds one says so instead of skipping it silently.
PRIVATE_FILES = frozenset({"hamdraw_settings.json", "chp_admin.json", "chp_keys.json"})


def plugin_version() -> str:
    """Read ``__version__`` out of version.py without importing the package.

    Importing ``hamdraw_chp`` would pull in ``folder_paths`` and ``aiohttp``,
    neither of which exists on the machine that builds the zip.
    """
    namespace: dict[str, object] = {}
    exec(compile(VERSION_FILE.read_text(encoding="utf-8"), str(VERSION_FILE), "exec"), namespace)
    value = namespace.get("__version__")
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"no usable __version__ in {VERSION_FILE.relative_to(ROOT)}")
    return value.strip()


VERSION = plugin_version()
ARCHIVE = ROOT / "release" / f"hamdraw-comfyui-plugin-v{VERSION}.zip"


_FILE_CACHE: list[pathlib.Path] | None = None


def plugin_files() -> list[pathlib.Path]:
    """The archive members, in publish order. Scanned once (the warning below must
    not repeat for every caller)."""
    global _FILE_CACHE
    if _FILE_CACHE is not None:
        return _FILE_CACHE
    files: list[pathlib.Path] = []
    for relative in ENTRIES:
        target = SOURCE / relative
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            # Bytecode caches are build leftovers from whatever machine last imported
            # the plugin; they must never travel in the published archive. Neither must
            # the runtime credential files handled below.
            skipped: list[str] = []
            for path in target.rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.name in PRIVATE_FILES:
                    skipped.append(path.relative_to(SOURCE).as_posix())
                    continue
                files.append(path)
            for name in sorted(skipped):
                print(f"warning: skipping private file {name}", file=sys.stderr)
        else:
            raise SystemExit(f"missing plugin path: {relative}")
    _FILE_CACHE = sorted(files, key=lambda path: path.relative_to(SOURCE).as_posix())
    return _FILE_CACHE


def plugin_directories() -> list[str]:
    """Explicit folder entries keep the archive friendly to simple unzip tools."""
    names = {
        path.relative_to(SOURCE).parent.as_posix() + "/"
        for path in plugin_files()
        if path.relative_to(SOURCE).parent.parts
    }
    return sorted(names)


def write_archive(archive: pathlib.Path) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in plugin_directories():
            info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (0o40755 << 16) | 0x10
            bundle.writestr(info, b"")
        for path in plugin_files():
            info = zipfile.ZipInfo(path.relative_to(SOURCE).as_posix(), FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes())


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the committed archive")
    args = parser.parse_args()

    if args.check:
        if not ARCHIVE.exists():
            raise SystemExit(f"missing archive: {ARCHIVE.relative_to(ROOT)}")
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            rebuilt = pathlib.Path(temporary) / ARCHIVE.name
            write_archive(rebuilt)
            if sha256(rebuilt) != sha256(ARCHIVE):
                raise SystemExit("the committed plugin archive does not match its sources")
        print(f"plugin archive ok {ARCHIVE.relative_to(ROOT)} sha256={sha256(ARCHIVE)}")
        return

    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    write_archive(ARCHIVE)
    print(f"created {ARCHIVE.relative_to(ROOT)} ({ARCHIVE.stat().st_size} bytes) sha256={sha256(ARCHIVE)}")


if __name__ == "__main__":
    main()
