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
_GIT_PKGBUILD = _ROOT / "packaging" / "git" / "PKGBUILD"


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

    @unittest.skipUnless(_GIT_PKGBUILD.is_file(), "packaging/git/PKGBUILD only exists in a checkout")
    def test_git_pkgbuild_declares_the_same_checkdepends_as_the_release_one(self):
        # REAL BUG, found 2026-09-17 (Astra and Sol's bug-sweeps,
        # independently): packaging/git/PKGBUILD ran the identical
        # check() suite but never declared checkdepends at all -- missing
        # python-pyusb can prevent the suite from even being collected in
        # a clean chroot; missing python-pyqt6 makes every g7ctlc test
        # skip itself instead of failing, so check() goes green having
        # covered none of them.
        #
        # This only proves the two files' checkdepends= lines agree, not
        # that a clean chroot build actually succeeds -- this machine has
        # no such environment available (see STATUS.md/HANDOFF.md's own
        # documented limitation: no PKGBUILD build-test has ever run here,
        # release or -git). A real clean-chroot build remains the honest
        # next step to fully close this, same as it already was for the
        # release PKGBUILD's own checkdepends before this fix existed.
        release_match = re.search(r"^checkdepends=\((.+)\)$", _PKGBUILD.read_text(), re.MULTILINE)
        git_match = re.search(r"^checkdepends=\((.+)\)$", _GIT_PKGBUILD.read_text(), re.MULTILINE)
        self.assertIsNotNone(release_match, "no checkdepends= line found in packaging/PKGBUILD")
        self.assertIsNotNone(git_match, "no checkdepends= line found in packaging/git/PKGBUILD")
        self.assertEqual(git_match.group(1), release_match.group(1))
