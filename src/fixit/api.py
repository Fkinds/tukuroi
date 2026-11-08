# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
import os
import sys
import time
import traceback
from collections.abc import Generator, Iterable, Sequence
from functools import partial
from pathlib import Path

import click
import trailrunner
from moreorless import unified_diff
from moreorless.click import echo_color_precomputed_diff

from .config import collect_rules, generate_config, load_rules
from .core.edits import apply_fixes
from .core.engine import MAX_ROUNDS, fix, lint
from .core.rule import Report, Rule
from .core.source import ParseError, Source
from .core.text import Range
from .engine import LintRunner
from .format import format_module
from .ftypes import (
    CORE_ENGINE,
    STDIN,
    Config,
    FileContent,
    LintViolation,
    Metrics,
    MetricsHook,
    Options,
    OutputFormat,
    Result,
    Violation,
)

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
    return str(error)


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

        if output_format == OutputFormat.fixit:
            line = f"{path}@{start_line}:{start_col} {rule_name}: {message}"
        elif output_format == OutputFormat.vscode:
            line = f"{path}:{start_line}:{start_col} {rule_name}: {message}"
        elif output_format == OutputFormat.custom:
            line = output_template.format(
                message=message,
                path=path,
                result=result,
                rule_name=rule_name,
                start_col=start_col,
                start_line=start_line,
            )
        else:
            raise NotImplementedError(f"output-format = {output_format!r}")
        click.secho(line, fg="yellow", err=stderr)

        if show_diff and result.violation.diff:
            echo_color_precomputed_diff(result.violation.diff)
        return True

    elif result.error:
        # An exception occurred while processing a file
        error, tb = result.error
        click.secho(f"{path}: EXCEPTION: {_describe(error)}", fg="red", err=stderr)
        if tb:
            click.echo(tb.strip(), err=stderr)
        return True

    elif result.applied:
        LOG.debug("%s: %d fixes applied", path, result.applied)
        return False

    else:
        LOG.debug("%s: clean", path)
        return False


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
    how many were (``applied``).

    """
    if os.environ.get(CORE_ENGINE) == "1":
        return (
            yield from _fixit_bytes_core(
                path, content, config=config, autofix=autofix, metrics_hook=metrics_hook
            )
        )
    try:
        rules = collect_rules(config)

        if not rules:
            yield Result(path, violation=None)
            return None

        runner = LintRunner(path, content)
        pending_fixes: list[LintViolation] = []

        clean = True
        for violation in runner.collect_violations(rules, config, metrics_hook):
            clean = False
            fix = yield Result(path, violation)
            if fix or autofix:
                pending_fixes.append(violation)

        if clean:
            yield Result(path, violation=None)

        if pending_fixes:
            updated = runner.apply_replacements(pending_fixes)
            if applied := sum(1 for v in pending_fixes if v.autofixable):
                yield Result(path, violation=None, applied=applied)
            return format_module(updated, path, config)

    except Exception as error:
        # TODO: this is not the right place to catch errors
        LOG.debug("Exception while linting", exc_info=error)
        yield Result(path, violation=None, error=(error, traceback.format_exc()))

    return None


def _fixit_bytes_core(
    path: Path,
    content: FileContent,
    *,
    config: Config,
    autofix: bool,
    metrics_hook: MetricsHook | None,
) -> Generator[Result, bool, FileContent | None]:
    """
    :func:`fixit_bytes` on the new engine (#21). The fixes that ``autofix`` takes
    are applied round after round; those sent back to the generator, in one
    round. The fixed text is formatted with ``ruff format``.
    """
    try:
        rules = load_rules(config)
        if not rules:
            yield Result(path, violation=None)
            return None
        try:
            source = Source.from_bytes(content, path)
        except ParseError as error:
            # The file is wrong, not fixit: no traceback.
            yield Result(path, violation=None, error=(error, ""))
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
            yield Result(path, violation=None, applied=fixed.applied)
        if fixed.text != source.text:
            return source.encode(fixed.text)

    except Exception as error:
        # As fixit_bytes: an exception in a rule is the result of the file.
        LOG.debug("Exception while linting", exc_info=error)
        yield Result(path, violation=None, error=(error, traceback.format_exc()))

    return None


def _violation(path: Path, source: Source, report: Report) -> Violation:
    """``report`` as the CLI and the LSP show it, with the diff of its fix."""
    end = source.lines.position(report.span.end)
    diff = ""
    if report.edits:
        after = apply_fixes(source.text, [report.edits]).text
        diff = unified_diff(source.text, after, path.name, n=1)
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
        config = generate_config(path, options=options)

        updated = yield from fixit_bytes(
            path, content, config=config, autofix=autofix, metrics_hook=metrics_hook
        )
        if autofix:
            sys.stdout.buffer.write(updated or content)

    except Exception as error:
        LOG.debug("Exception while fixit_stdin", exc_info=error)
        yield Result(path, violation=None, error=(error, traceback.format_exc()))


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
        config = generate_config(path, options=options)

        updated = yield from fixit_bytes(
            path, content, config=config, autofix=autofix, metrics_hook=metrics_hook
        )
        if updated and updated != content:
            LOG.info(f"{path}: writing changes to file")
            path.write_bytes(updated)

    except Exception as error:
        LOG.debug("Exception while fixit_file", exc_info=error)
        yield Result(path, violation=None, error=(error, traceback.format_exc()))


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
    Any further path names will result in a runtime error.

    .. note::

        Currently does not support applying individual fixes when ``parallel=True``,
        due to limitations in the multiprocessing method in use.
        Setting ``parallel=False`` will enable interactive fixes.
        Setting ``autofix=True`` will always apply fixes automatically during linting.
    """
    if not paths:
        return

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
        else:
            expanded_paths.extend(trailrunner.walk(path))

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
        for _, results in trailrunner.run_iter(expanded_paths, fn):
            yield from results
