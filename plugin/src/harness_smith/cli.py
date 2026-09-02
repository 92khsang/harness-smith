"""The command-line boundary: the one public seam of the product.

Every run emits exactly one OperationResult, including a run that fails before an operation
was identified. There is no path on which automation receives a non-document outcome.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from harness_smith.diagnostics import Diagnostic
from harness_smith.operations import REGISTRY, Operation, OperationRequest
from harness_smith.render import FORMATS, JSON, TEXT, render_json, render_text
from harness_smith.repository import resolve_repository_root
from harness_smith.result import OperationResult
from harness_smith.vocabulary import ENVIRONMENT_SUBJECT, ExitCode, Mode

PROGRAM = "harness-smith"


class UsageError(Exception):
    """An invocation the command-line contract refuses."""


class HelpRequested(Exception):  # noqa: N818 - a control signal, not a failure
    """``--help`` was asked for; argparse has already written it."""


class _Parser(argparse.ArgumentParser):
    """An argument parser that reports failures as diagnostics instead of exiting itself."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if status == 0:
            raise HelpRequested(message or "")
        raise UsageError(message or "invalid invocation")


def _add_shared_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool) -> None:
    """Shared options are accepted before and after the operation name.

    The copies on a subparser suppress their defaults so that omitting one there does not
    overwrite the value given ahead of the operation name.
    """
    parser.add_argument(
        "--format",
        choices=list(FORMATS),
        default=argparse.SUPPRESS if suppress_defaults else TEXT,
        help="output format (default: text)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=argparse.SUPPRESS if suppress_defaults else None,
        metavar="PATH",
        help="repository root (default: discovered from the working directory)",
    )


def build_parser() -> _Parser:
    # Abbreviated spellings are refused: argparse would accept --forma=json while the
    # pre-scan that decides the format of a pre-dispatch failure would not recognise it, so
    # the same invocation would answer in two different formats depending on where it failed.
    parser = _Parser(
        prog=PROGRAM,
        description="Author and govern the repository-owned agent harness.",
        allow_abbrev=False,
    )
    _add_shared_options(parser, suppress_defaults=False)
    subparsers = parser.add_subparsers(dest="operation", required=True, metavar="OPERATION")
    for name in sorted(REGISTRY):
        subparser = subparsers.add_parser(
            name,
            prog=f"{PROGRAM} {name}",
            help=REGISTRY[name].spec.summary,
            allow_abbrev=False,
        )
        _add_shared_options(subparser, suppress_defaults=True)
    return parser


def preferred_format(arguments: Sequence[str]) -> str:
    """Pre-scan the arguments so a run that fails before parsing still honours ``--format``.

    The last occurrence wins, which is what the parser itself would have decided.
    """
    chosen = TEXT
    for index, argument in enumerate(arguments):
        if argument == "--format" and index + 1 < len(arguments):
            candidate = arguments[index + 1]
        elif argument.startswith("--format="):
            candidate = argument.split("=", 1)[1]
        else:
            continue
        if candidate in FORMATS:
            chosen = candidate
    return chosen


def help_requested(arguments: Sequence[str]) -> bool:
    return any(argument in {"-h", "--help"} for argument in arguments)


def _failure(operation: str | None, mode: Mode, code: str, message: str) -> OperationResult:
    return OperationResult(
        operation=operation,
        mode=mode,
        diagnostics=(Diagnostic.of(code, ENVIRONMENT_SUBJECT, message=message),),
        data=None,
    )


def _emit(result: OperationResult, output_format: str, operation: Operation | None = None) -> int:
    if output_format == JSON:
        sys.stdout.write(render_json(result))
    else:
        sys.stdout.write(render_text(result, operation))
    return int(result.exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    output_format = preferred_format(arguments)

    # Help is prose on stdout, which is the one thing --format json promises stdout will not
    # carry. The contract forbids the combination rather than breaking the promise.
    if output_format == JSON and help_requested(arguments):
        return _emit(
            _failure(
                None,
                Mode.READ,
                "HS-CLI-USAGE",
                "--help is not available with --format json; ask for help in the text format",
            ),
            JSON,
        )

    try:
        parsed = build_parser().parse_args(arguments)
    except HelpRequested:
        return int(ExitCode.SUCCESS)
    except UsageError as error:
        return _emit(_failure(None, Mode.READ, "HS-CLI-USAGE", str(error)), output_format)

    operation = REGISTRY[parsed.operation]
    output_format = parsed.format
    mode = operation.spec.default_mode

    root = resolve_repository_root(parsed.root, Path.cwd())
    if root is None:
        return _emit(
            _failure(
                operation.spec.name,
                mode,
                "HS-REPOSITORY-ROOT-NOT-FOUND",
                "the given --root is not a repository"
                if parsed.root is not None
                else "no repository root could be identified from the working directory",
            ),
            output_format,
        )

    try:
        outcome = operation.run(OperationRequest(repository_root=root))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return _emit(
            _failure(
                operation.spec.name, mode, "HS-INTERNAL-ERROR", "the operation failed unexpectedly"
            ),
            output_format,
        )

    result = OperationResult(
        operation=operation.spec.name,
        mode=mode,
        diagnostics=outcome.diagnostics,
        changes=outcome.changes,
        data=outcome.data,
    )
    return _emit(result, output_format, operation)
