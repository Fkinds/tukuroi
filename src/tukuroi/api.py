# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import errno
import logging
import os
import sys
import time
import traceback
from collections.abc import Generator, Iterable, Sequence
from functools import partial
from pathlib import Path
from typing import assert_never

import click
import trailrunner
from moreorless import unified_diff

from . import pool
from .config import ConfigError, check_configs, generate_config, load_rules
from .core.edits import apply_fixes
from .core.engine import MAX_ROUNDS, fix, lint
from .core.rule import Report, Rule
from .core.source import ParseError, Source
from .core.text import Range
from .ftypes import (
    STDIN,
    Config,
    Error,
    FileContent,
    Metrics,
    MetricsHook,
    Options,
    OutputFormat,
    Result,
    Violation,
)
from .template import format_template

LOG = logging.getLogger(__name__)


def _shown(path: Path) -> Path:
    """``path`` relative to the current directory, if it is under it."""
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def _describe(error: Exception) -> str:
    if isinstance(error, ParseError):
        line, column = error.position.line, error.position.column
        return f"Syntax Error @ {line}:{column}: {error.message}"
    if isinstance(error, ConfigError):
        return error.describe()
    try:
        return str(error)
    except Exception:  # noqa: BLE001
        # The str() of a rule's exception can raise anything: as traceback.
        return "<exception str() failed>"


def _error(error: Exception, tb: str = "") -> Error:
    """
    ``error`` in strings alone, so that the process pool of ``lint`` can send
    it back: an exception that a rule raises may not pickle, or its class may
    not import in the parent process (#64). The name of its type is that of
    :mod:`traceback`.
    """
    name = traceback.TracebackException.from_exception(error).exc_type_str
    position = error.position if isinstance(error, ParseError) else None
    return Error(name, _describe(error), tb, position)


def print_result(
    result: Result,
    *,
    show_diff: bool = False,
    stderr: bool = False,
    output_format: OutputFormat = OutputFormat.fixit,
    output_template: str = "",
) -> int:
    """
    Print linting results in a simple format designed for human eyes.

    Setting ``show_diff=True`` will output autofixes or suggested changes in unified
    diff format, using ANSI colors when possible.

    Returns ``True`` if the result is "dirty" - either a lint error or exception.
    """
    path = _shown(result.path)

    if result.violation:
        rule_name = result.violation.rule_name
        start_line = result.violation.range.start.line
        start_col = result.violation.range.start.column
        message = result.violation.message
        if result.violation.autofixable:
            message += " (has autofix)"

        # The value as the enum, which a string of it is equal to: then `is`.
        output_format = OutputFormat(output_format)
        if output_format is OutputFormat.fixit:
            line = f"{path}@{start_line}:{start_col} {rule_name}: {message}"
        elif output_format is OutputFormat.vscode:
            line = f"{path}:{start_line}:{start_col} {rule_name}: {message}"
        elif output_format is OutputFormat.custom:
            # The names only, and strings and numbers (#14).
            end = result.violation.range.end
            values = {
                "end_col": end.column,
                "end_line": end.line,
                "message": message,
                "path": str(path),
                "rule_name": rule_name,
                "start_col": start_col,
                "start_line": start_line,
            }
            line = format_template(output_template, values)
        else:
            assert_never(output_format)
        click.secho(line, fg="yellow", err=stderr)

        if show_diff and result.violation.diff:
            _echo_diff(result.violation.diff, err=stderr)
        return True

    elif result.error:
        # An exception occurred while processing a file
        error = result.error
        click.secho(f"{path}: EXCEPTION: {error.message}", fg="red", err=stderr)
        if error.traceback:
            click.echo(error.traceback.strip(), err=stderr)
        return True

    elif result.applied:
        LOG.debug("%s: %d fixes applied", path, result.applied)
        return False

    else:
        LOG.debug("%s: clean", path)
        return False


# The color and boldness of the lines of a diff, as moreorless.click prints
# them; it prints to stdout only, which is the fixed source of `fix -` (#40).
_DIFF_STYLES = (
    ("---", None, True),
    ("+++", None, True),
    ("@@", "cyan", None),
    ("-", "red", None),
    ("+", "green", None),
)


def _echo_diff(diff: str, *, err: bool = False) -> None:
    """``diff`` in colors, on stderr if ``err``."""
    for line in diff.splitlines(True):
        styles = (s[1:] for s in _DIFF_STYLES if line.startswith(s[0]))
        fg, bold = next(styles, (None, None))
        click.secho(line, nl=False, err=err, fg=fg, bold=bold)


def fixit_bytes(
    path: Path,
    content: FileContent,
    *,
    config: Config,
    autofix: bool = False,
    metrics_hook: MetricsHook | None = None,
) -> Generator[Result, bool, FileContent | None]:
    """
    Lint raw bytes content representing a single path, using the given configuration.

    Yields :class:`Result` objects for each lint error or exception found, or a single
    empty result if the file is clean. A file is considered clean if no lint errors or
    no rules are enabled for the given path.
    Returns the final :class:`FileContent` including any fixes applied.

    Use :func:`capture` to more easily capture return value after iterating through
    violations. Use ``generator.send(...)`` with a boolean value to apply individual
    fixes for each violation.

    If ``autofix`` is ``True``, all violations with replacements will be applied
    automatically, even if ``False`` is sent back to the generator. After the
    violations of a file whose fixes were applied, a last :class:`Result` tells
    how many were (``applied``), and how many violations are left in the fixed
    text (``remaining``): ``fix`` exits with 1 if any are (#40).

    It runs the new engine (#21). The fixes that ``autofix`` takes are applied
    round after round; those sent back to the generator, in one round. The fixed
    text is formatted with ``ruff format``.

    A rule of ``config`` that cannot be loaded is the error of the file, without
    a traceback, and no rule runs (#40).
    """
    try:
        rules = load_rules(config)
    except ConfigError as error:
        yield Result(path, violation=None, error=_error(error))
        return None
    try:
        if not rules:
            yield Result(path, violation=None)
            return None
        try:
            source = Source.from_bytes(content, path)
        except ParseError as error:
            # The file is wrong, not tukuroi: no traceback.
            yield Result(path, violation=None, error=_error(error))
            return None

        start = time.perf_counter()
        linted = lint(source, rules)
        duration = int(1_000_000 * (time.perf_counter() - start))
        for bad in linted.bad_directives:
            kind = "lint-fixme" if bad.text.startswith("lint-fixme") else "lint-ignore"
            line = bad.position.line
            LOG.warning("%s:%d: invalid %s directive", _shown(path), line, kind)
        if metrics_hook:
            metrics_hook(_metrics(rules, linted.reports, duration))

        chosen: list[Report] = []
        for report in linted.reports:
            answer = yield Result(path, _violation(path, source, report))
            if (answer or autofix) and report.edits:
                chosen.append(report)
        if not linted.reports:
            yield Result(path, violation=None)
        if not chosen:
            return None

        fixed = fix(source, rules, choose=None if autofix else chosen.__contains__)
        if not fixed.converged:
            rounds = f"{MAX_ROUNDS} rounds"
            LOG.warning("%s: fixes did not converge after %s", _shown(path), rounds)
        if fixed.applied:
            left = lint(Source.from_text(fixed.text, path), rules).reports
            yield Result(
                path, violation=None, applied=fixed.applied, remaining=len(left)
            )
        if fixed.text != source.text:
            return source.encode(fixed.text)

    except Exception as error:
        # An exception in a rule is the result of the file.
        LOG.debug("Exception while linting", exc_info=error)
        yield Result(path, violation=None, error=_error(error, traceback.format_exc()))

    return None


def _violation(path: Path, source: Source, report: Report) -> Violation:
    """``report`` as the CLI and the LSP show it, with the diff of its fix."""
    end = source.lines.position(report.span.end)
    diff = ""
    if report.edits:
        after = apply_fixes(source.text, [report.edits]).text
        # The path as the violation shows it (#40), with "/" as a diff has it.
        diff = unified_diff(source.text, after, _shown(path).as_posix(), n=1)
    where = Range(report.position, end)
    return Violation(report.rule, where, report.message, bool(report.edits), diff)


def _metrics(
    rules: Sequence[type[Rule]], reports: Sequence[Report], duration: int
) -> Metrics:
    """The reports of each rule, those with a fix, and the time to lint (µs)."""
    metrics: Metrics = {"Count.Total": len(reports), "Duration.Total": duration}
    for rule in rules:
        mine = [r for r in reports if r.rule == rule.name()]
        metrics[f"Count.{rule.name()}"] = len(mine)
        metrics[f"FixCount.{rule.name()}"] = sum(1 for r in mine if r.edits)
    return metrics


def fixit_stdin(
    path: Path,
    *,
    autofix: bool = False,
    options: Options | None = None,
    metrics_hook: MetricsHook | None = None,
) -> Generator[Result, bool]:
    """
    Wrapper around :func:`fixit_bytes` for formatting content from STDIN.

    The resulting fixed content will be printed to STDOUT.

    Requires passing a path that represents the filesystem location matching the
    contents to be linted. This will be used to resolve the ``fixit.toml`` config
    file(s).
    """
    path = path.resolve()

    try:
        content: FileContent = sys.stdin.buffer.read()
        config = generate_config(path, options=options, check=True)

        updated = yield from fixit_bytes(
            path, content, config=config, autofix=autofix, metrics_hook=metrics_hook
        )
        if autofix:
            sys.stdout.buffer.write(updated or content)

    except ConfigError as error:
        # The config is wrong, not tukuroi: no traceback (#40).
        yield Result(path, violation=None, error=_error(error))
    except Exception as error:
        LOG.debug("Exception while fixit_stdin", exc_info=error)
        yield Result(path, violation=None, error=_error(error, traceback.format_exc()))


def fixit_file(
    path: Path,
    *,
    autofix: bool = False,
    options: Options | None = None,
    metrics_hook: MetricsHook | None = None,
) -> Generator[Result, bool]:
    """
    Lint a single file on disk, detecting and generating appropriate configuration.

    Generates a merged :ref:`configuration` based on all applicable config files.
    Reads file from disk as raw bytes, and uses :func:`fixit_bytes` to lint and apply
    any fixes to the content. Writes content back to disk if changes are detected.

    Yields :class:`Result` objects for each lint error or exception found, or a single
    empty result if the file is clean.
    See :func:`fixit_bytes` for semantics.
    """
    path = path.resolve()

    try:
        content: FileContent = path.read_bytes()
        config = generate_config(path, options=options, check=True)

        updated = yield from fixit_bytes(
            path, content, config=config, autofix=autofix, metrics_hook=metrics_hook
        )
        if updated and updated != content:
            LOG.info(f"{path}: writing changes to file")
            path.write_bytes(updated)

    except ConfigError as error:
        # The config is wrong, not tukuroi: no traceback (#40).
        yield Result(path, violation=None, error=_error(error))
    except Exception as error:
        LOG.debug("Exception while fixit_file", exc_info=error)
        yield Result(path, violation=None, error=_error(error, traceback.format_exc()))


def _fixit_file_wrapper(
    path: Path,
    *,
    autofix: bool = False,
    options: Options | None = None,
    metrics_hook: MetricsHook | None = None,
) -> list[Result]:
    """
    Wrapper because generators can't be pickled or used directly via multiprocessing
    TODO: replace this with some sort of queue or whatever
    """
    return list(
        fixit_file(path, autofix=autofix, options=options, metrics_hook=metrics_hook)
    )


def fixit_paths(
    paths: Iterable[Path],
    *,
    autofix: bool = False,
    options: Options | None = None,
    parallel: bool = True,
    metrics_hook: MetricsHook | None = None,
) -> Generator[Result, bool]:
    """
    Lint multiple files or directories, recursively expanding each path.

    Walks all paths given, obeying any ``.gitignore`` exclusions, finding Python source
    files. Lints each file found using :func:`fixit_file`, using a process pool when
    more than one file is being linted.

    Yields :class:`Result` objects for each path, lint error, or exception found.
    See :func:`fixit_bytes` for semantics.

    If the first given path is STDIN (``Path("-")``), then content will be linted
    from STDIN using :func:`fixit_stdin`. The fixed content will be written to STDOUT.
    A second path argument may be given, which represents the original content's true
    path name, and will be used:
    - to resolve the ``fixit.toml`` configuration file(s)
    - when printing status messages, diffs, or errors.
    If no second path argument is given, it will default to "stdin" in the current
    working directory.
    Any further path names will result in a runtime error. A STDIN after
    another path is skipped with a warning. The CLI refuses both, as usage
    errors (#40).

    A path that does not exist raises a :class:`FileNotFoundError` before the
    first result. A file given by name is linted though ``.gitignore`` has it,
    and a file given twice, by name or in a directory, is linted once (#40).

    .. note::

        Currently does not support applying individual fixes when ``parallel=True``,
        due to limitations in the multiprocessing method in use.
        Setting ``parallel=False`` will enable interactive fixes.
        Setting ``autofix=True`` will always apply fixes automatically during linting.

    When a rule ends the process that lints a file (``os._exit``, a crash, a
    kill), that file gets an error, and the other files their results (#94).

    Before the first result, the config of the directory of each file is read
    (:func:`~tukuroi.config.check_configs`): a config that tukuroi cannot use raises
    a :class:`~tukuroi.config.ConfigError`, and no file is linted (#40). A file
    linted alone (:func:`fixit_file`) gets such an error as its result.
    """
    expanded_paths: list[Path] = []
    is_stdin = False
    stdin_path = Path("stdin")
    for i, path in enumerate(paths):
        if path == STDIN:
            if i == 0:
                is_stdin = True
            else:
                LOG.warning("Cannot mix stdin ('-') with normal paths, ignoring")
        elif is_stdin:
            if i == 1:
                stdin_path = path
            else:
                raise ValueError("too many stdin paths")
        elif not path.exists():
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(path))
        elif path.is_file():
            expanded_paths.append(path)
        else:
            expanded_paths.extend(trailrunner.walk(path))

    # Each file once, where it comes first.
    unique: dict[Path, Path] = {}
    for path in expanded_paths:
        unique.setdefault(path.resolve(), path)
    expanded_paths = list(unique.values())

    check_configs([stdin_path] if is_stdin else expanded_paths, options)

    if is_stdin:
        yield from fixit_stdin(
            stdin_path, autofix=autofix, options=options, metrics_hook=metrics_hook
        )
    elif len(expanded_paths) == 1 or not parallel:
        for path in expanded_paths:
            yield from fixit_file(
                path, autofix=autofix, options=options, metrics_hook=metrics_hook
            )
    else:
        fn = partial(
            _fixit_file_wrapper,
            autofix=autofix,
            options=options,
            metrics_hook=metrics_hook,
        )
        for _, results in pool.run(expanded_paths, fn):
            yield from results
