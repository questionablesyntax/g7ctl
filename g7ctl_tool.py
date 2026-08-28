#!/usr/bin/env python3
"""CLI shim for running from a source checkout, with no install step.

The real implementation is g7ctl/main.py. If the project is
pip-installed, use the `g7ctl` console script instead; this file only
exists so the CLI is runnable straight from a fresh `git clone` via
`python3 g7ctl_tool.py ...`.
"""
from g7ctl.main import main

if __name__ == "__main__":
    main()
