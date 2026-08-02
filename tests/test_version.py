"""The version strings a release has to bump in lockstep.

Cutting a release edits five of them by hand -- pyproject.toml, the three
packages' __init__.py, and the PKGBUILD's pkgver -- and nothing has ever
checked that they agree afterwards. A miss is quiet in the worst way:
`--version` would report one number while pacman and the wheel's metadata
report another, on exactly the bug report where the version is the point.

Skipped rather than failed when the repo files aren't present, so an
installed copy of the test suite (or one run from a wheel) doesn't fail on
paths that only exist in a checkout or source tarball.
"""
import re
import unittest
from pathlib import Path

import g7ctl
import g7ctlc
import pyg7

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"
_PKGBUILD = _ROOT / "packaging" / "PKGBUILD"


class VersionLockstepTest(unittest.TestCase):
    def test_the_three_packages_agree(self):
        self.assertEqual(pyg7.__version__, g7ctl.__version__)
        self.assertEqual(pyg7.__version__, g7ctlc.__version__)

    @unittest.skipUnless(_PYPROJECT.is_file(), "pyproject.toml only exists in a checkout/sdist")
    def test_pyproject_agrees(self):
        # Read by regex rather than tomllib: tomllib is 3.11+, and this project
        # supports 3.9. The anchor matters -- an unanchored `version` would also
        # match [tool.ruff]'s target-version.
        match = re.search(r'^version\s*=\s*"([^"]+)"$', _PYPROJECT.read_text(),
                          re.MULTILINE)
        self.assertIsNotNone(match, "no version= line found in pyproject.toml")
        self.assertEqual(match.group(1), pyg7.__version__,
                         "pyproject.toml and pyg7.__version__ disagree -- the wheel's "
                         "metadata would report a different version than --version does")

    @unittest.skipUnless(_PKGBUILD.is_file(), "PKGBUILD only exists in a checkout/sdist")
    def test_pkgbuild_pkgver_agrees(self):
        # Only the release PKGBUILD: packaging/git/ derives its pkgver from
        # `git describe` at build time and is meant to differ.
        match = re.search(r"^pkgver=(\S+)$", _PKGBUILD.read_text(), re.MULTILINE)
        self.assertIsNotNone(match, "no pkgver= line found in packaging/PKGBUILD")
        self.assertEqual(match.group(1), pyg7.__version__,
                         "PKGBUILD pkgver and the packages disagree -- the release "
                         "tarball URL it builds from would point at the wrong tag")
