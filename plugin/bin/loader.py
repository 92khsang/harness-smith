"""Load the prepared environment's copy of the tool, or report that it cannot be loaded.

The launcher runs this instead of ``-m harness_smith`` so that one interpreter start can tell
a damaged environment apart from a failing operation. An environment that cannot import the
tool exits with ``LOAD_FAILURE`` before anything reaches stdout, which lets the launcher
discard its readiness claim and prepare again; every other status is the tool's own.

It is run under ``-I``, so the caller's working directory, ``PYTHONPATH``, ``PYTHONHOME`` and
the user site directory are all off ``sys.path``: this tool runs from inside the repository it
audits, and nothing there may supply the package the tool is.
"""

from __future__ import annotations

import sys

LOAD_FAILURE = 97


def main() -> int:
    try:
        from harness_smith.cli import main as run_command_line
    except Exception as error:
        sys.stderr.write(
            f"harness-smith: the prepared environment cannot load the tool: {error!r}\n"
        )
        return LOAD_FAILURE
    return run_command_line(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
