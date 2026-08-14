# Working on g7ctl

Reverse-engineered userspace control for the GameSir G7 Pro. Three packages
in one repo: `pyg7/` (protocol library, no GUI deps), `g7ctl/` (CLI), and
`g7ctlc/` (PyQt6 GUI).

**[`PROTOCOL.md`](PROTOCOL.md) is the reference for everything on the wire.**
Read the relevant section before changing anything that builds or parses a
packet. It documents confirmed behaviour only, and says so explicitly where a
value is predicted rather than observed.

## The rules that matter here

**Nothing about the hardware is confirmed until it has been confirmed on the
hardware.** Unit tests here run against a fake session that records calls; it
cannot model timing, firmware quirks, or the device's actual behaviour. Every
protocol change needs a write -> read -> compare round trip against a real
controller. This has repeatedly caught bugs that a green test suite did not:
a dropped third write, a decoder that disagreed with its own writer, and a
flag whose meaning was backwards.

**A test written from a wrong model will confirm the wrong model.** When a
test passes and the feature is broken, suspect the fake first. Prefer tests
that go through the path the application actually takes over ones that call a
helper directly.

**Distinguish "measured" from "inferred", in commits and in comments.** If
something was reasoned rather than observed, say so and say what would
falsify it. Several confident, internally-consistent conclusions in this
project's history were wrong because every sample shared a property nobody
noticed.

**Switching the controller in and out of vendor mode too quickly can wedge
it.** Reads stop answering while everything else keeps working, and the only
recovery erases the active profile's remaps. `pyg7/device.py` paces the
handshake for this reason. Do not remove that pacing, and prefer
`g7ctl batch` (one session, many commands) over loops of single commands.

**Config writes are addressed writes into a register file.** `03 [PROFILE]
[PAGE] [OFFSET] [LEN]` writes `LEN` bytes at `(PAGE << 8) + OFFSET`. A wrong
length or address does not error -- it silently corrupts a neighbouring
setting. See PROTOCOL.md.

## Checks

```bash
pytest -q          # full suite
ruff check .       # lint
```

Both run in CI on every push. Releases bump **five** version strings in
lockstep (`pyproject.toml`, the three `__init__.py` files, and
`packaging/PKGBUILD`); `tests/test_version.py` fails if they drift.

## Packaging

- `packaging/PKGBUILD` builds a **tagged release** from its GitHub tarball.
  It cannot contain unreleased commits -- bumping `pkgrel` will not pick them
  up.
- `packaging/git/PKGBUILD` builds **current `main`** as `*-git` packages,
  which conflict/replace the release ones. Use this to install unreleased
  work.
