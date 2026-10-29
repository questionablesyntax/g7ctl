"""Every data file the GUI reads at run time must be listed in
pyproject.toml's package-data, or it works from a checkout and is missing
from the installed package. g7ctlc/controller_diagram.py reads
assets/drawing/front.svg at import time, so a wheel without it fails to start.

The globs are read from the file's text rather than with tomllib, which
Python 3.9 (still in the CI matrix) does not have.
"""
import fnmatch
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "g7ctlc" / "assets"


def _package_data_globs() -> list:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[tool.setuptools.package-data]", 1)[1]
    section = re.split(r"(?m)^\[", section, maxsplit=1)[0]
    body = section.split("=", 1)[1]
    return re.findall(r'"([^"]+)"', body)


def _matches(relative: str, pattern: str) -> bool:
    """setuptools' glob: `*` stays within one path segment."""
    rel, pat = relative.split("/"), pattern.split("/")
    return len(rel) == len(pat) and all(fnmatch.fnmatch(r, p) for r, p in zip(rel, pat))


class PackageDataTest(unittest.TestCase):
    def test_every_asset_file_is_covered_by_package_data(self):
        globs = _package_data_globs()
        self.assertTrue(globs, "no package-data globs found in pyproject.toml")
        missing = []
        for path in sorted(ASSETS.rglob("*")):
            if not path.is_file() or path.suffix in (".py", ".pyc") or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(ASSETS).as_posix()
            if not any(_matches(relative, g) for g in globs):
                missing.append(relative)
        self.assertEqual(missing, [], f"assets not shipped in the wheel: {missing}")

    def test_the_controller_drawing_is_shipped(self):
        self.assertTrue(
            any(_matches("drawing/front.svg", g) for g in _package_data_globs()),
            "drawing/front.svg is read at import time and must be in package-data")


if __name__ == "__main__":
    unittest.main()
