# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click

from fixit import __version__

from .api import fixit_paths, print_result
from .config import (
    ConfigError,
    RulesOptionError,
    generate_config,
    load_rules,
    parse_rule,
    validate_config,
)
from .core.testing import generate_test_cases
from .ftypes import STDIN, LSPOptions, Options, OutputFormat, QualifiedRule
from .template import template_error
from .util import capture


def splash(
    visited: set[Path], dirty: set[Path], autofixes: int = 0, fixed: int = 0
) -> None:
    def f(v: int) -> str:
        return "file" if v == 1 else "files"

    if dirty:
        reports = [
            click.style(f"{len(visited)} {f(len(visited))} checked"),
            click.style(
                f"{len(dirty)} {f(len(dirty))} with errors", fg="yellow", bold=True
            ),
        ]
        if autofixes:
            word = "fix" if autofixes == 1 else "fixes"
            reports += [click.style(f"{autofixes} auto-{word} available", bold=True)]
        if fixed:
            word = "fix" if fixed == 1 else "fixes"
            reports += [click.style(f"{fixed} {word} applied", bold=True)]

        message = ", ".join(reports)
        click.secho(f"🛠️  {message} 🛠️", err=True)
    else:
        click.secho(f"🧼 {len(visited)} {f(len(visited))} clean 🧼", err=True)


def require_builtin(ctx: click.Context, rules: Sequence[QualifiedRule]) -> None:
    """
    With custom rules turned off, a custom rule named on the command line is a
    usage error: unlike one in a config, the person running fixit wrote it.
    """
    if custom := [str(rule) for rule in rules if not rule.builtin]:
        names = ", ".join(repr(name) for name in custom)
        raise click.UsageError(
            f"Custom rules are turned off: {names}. Pass --custom-rules to load them.",
            ctx=ctx,
        )


def parse_rules(
    ctx: click.Context, param: click.Parameter, value: str
) -> list[QualifiedRule]:
    """``--rules``: names separated by commas. An invalid one is a usage error."""
    names = (name.strip() for name in value.split(","))
    try:
        return sorted({parse_rule(name, Path.cwd()) for name in names if name})
    except ConfigError as error:
        raise click.BadParameter(str(error), ctx, param) from error


def check_paths(
    ctx: click.Context, param: click.Parameter, value: tuple[Path, ...]
) -> tuple[Path, ...]:
    """
    "-" (stdin) comes first, and then at most the name of its file: anything
    else is a usage error. ``fixit_paths`` warns about the one, and raises a
    ValueError on the other (#40). A path that does not exist is a usage error
    too, as with ``debug`` (#40); the name of the file of stdin is a name only.
    """
    if STDIN in value[1:]:
        message = "'-' (stdin) must be the first path"
        raise click.BadParameter(message, ctx, param)
    if value[:1] == (STDIN,):
        if len(value) > 2:
            message = "only one path may follow '-' (stdin): the name of its file"
            raise click.BadParameter(message, ctx, param)
        return value
    exists = click.Path(exists=True)
    for path in value:
        exists.convert(str(path), param, ctx)
    return value


def check_template(ctx: click.Context, param: click.Parameter, value: str) -> str:
    """``--output-template``: a template that is not valid is a usage error (#14)."""
    if value and (error := template_error(value)):
        raise click.BadParameter(error, ctx, param)
    return value


class ConfigFailure(click.ClickException):
    """A config that fixit cannot use: exit with 2, as with a usage error."""

    exit_code = 2


class _FixitGroup(click.Group):
    """
    Keep the pre-Click 8.2 behavior for an empty command line. A
    :class:`ConfigError` in any command is printed without a traceback (#40).
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args and self.no_args_is_help and not ctx.resilient_parsing:
            click.echo(ctx.get_help(), color=ctx.color)
            ctx.exit()

        return super().parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        # As an invalid name in --rules (#40).
        except RulesOptionError as error:
            raise click.BadParameter(str(error), ctx, param_hint="'--rules'") from error
        except ConfigError as error:
            raise ConfigFailure(error.describe()) from error


@click.group(cls=_FixitGroup)
@click.pass_context
@click.version_option(__version__, "--version", "-V", prog_name="fixit")
@click.option(
    "--debug/--quiet", is_flag=True, default=None, help="Increase decrease verbosity"
)
@click.option(
    "--config-file",
    "-c",
    type=click.Path(dir_okay=False, exists=True, path_type=Path),
    default=None,
    help="Override default config file search behavior",
)
@click.option(
    "--rules",
    type=str,
    default="",
    callback=parse_rules,
    help="Override configured rules",
)
@click.option(
    "--custom-rules/--no-custom-rules",
    default=True,
    envvar="FIXIT_CUSTOM_RULES",
    show_envvar=True,
    help="Load rules other than the built-in ones (default: load)",
)
@click.option(
    "--output-format",
    "-o",
    type=click.Choice([o.name for o in OutputFormat], case_sensitive=False),
    show_choices=True,
    default=None,
    help="Select output format type",
)
@click.option(
    "--output-template",
    type=str,
    default="",
    callback=check_template,
    help="Python format template to use with output format 'custom'",
)
@click.option("--print-metrics", is_flag=True, help="Print metrics of this run")
def main(
    ctx: click.Context,
    debug: bool | None,
    config_file: Path | None,
    rules: list[QualifiedRule],
    custom_rules: bool,
    output_format: OutputFormat | None,
    output_template: str,
    print_metrics: bool,
) -> None:
    level = logging.WARNING
    if debug is not None:
        level = logging.DEBUG if debug else logging.ERROR
    logging.basicConfig(level=level, stream=sys.stderr)

    if not custom_rules:
        require_builtin(ctx, rules)

    ctx.obj = Options(
        debug=debug,
        config_file=config_file,
        rules=rules,
        output_format=output_format,
        output_template=output_template,
        print_metrics=print_metrics,
        custom_rules=custom_rules,
    )


@main.command()
@click.pass_context
@click.option("--diff", "-d", is_flag=True, help="Show diff of suggested changes")
@click.argument(
    "paths", nargs=-1, type=click.Path(path_type=Path), callback=check_paths
)
def lint(
    ctx: click.Context,
    diff: bool,
    paths: Sequence[Path],
) -> None:
    """
    lint one or more paths and return suggestions

    pass "- <FILENAME>" for STDIN representing <FILENAME>
    """
    options: Options = ctx.obj

    if not paths:
        paths = [Path.cwd()]

    exit_code = 0
    visited: set[Path] = set()
    dirty: set[Path] = set()
    autofixes = 0
    config = generate_config(options=options)
    for result in fixit_paths(
        paths, options=options, metrics_hook=print if options.print_metrics else None
    ):
        visited.add(result.path)
        if print_result(
            result,
            show_diff=diff,
            output_format=config.output_format,
            output_template=config.output_template,
        ):
            dirty.add(result.path)
            if result.violation:
                exit_code |= 1
                if result.violation.autofixable:
                    autofixes += 1
            if result.error:
                exit_code |= 2

    splash(visited, dirty, autofixes)
    ctx.exit(exit_code)


@main.command()
@click.pass_context
@click.option(
    "--interactive/--automatic",
    "-i/-a",
    is_flag=True,
    default=True,
    help="how to apply fixes; interactive by default unless STDIN",
)
@click.option("--diff", "-d", is_flag=True, help="show diff even with --automatic")
@click.argument(
    "paths", nargs=-1, type=click.Path(path_type=Path), callback=check_paths
)
def fix(
    ctx: click.Context,
    interactive: bool,
    diff: bool,
    paths: Sequence[Path],
) -> None:
    """
    lint and autofix one or more files and return results

    pass "- <FILENAME>" for STDIN representing <FILENAME>;
    this will ignore "--interactive" and always use "--automatic"
    """
    options: Options = ctx.obj

    if not paths:
        paths = [Path.cwd()]

    is_stdin = bool(paths[0] and str(paths[0]) == "-")
    interactive = interactive and not is_stdin
    autofix = not interactive
    exit_code = 0

    visited: set[Path] = set()
    dirty: set[Path] = set()
    autofixes = 0
    fixed = 0
    # The violations of each file: those reported, or those left after the
    # fixes applied to it. 1 if any are left, as `ruff check --fix` (#40).
    left: dict[Path, int] = {}

    # TODO: make this parallel
    generator = capture(
        fixit_paths(
            paths,
            autofix=autofix,
            options=options,
            parallel=False,
            metrics_hook=print if options.print_metrics else None,
        )
    )
    config = generate_config(options=options)
    for result in generator:
        visited.add(result.path)
        # for STDIN, we need STDOUT to equal the fixed content, so
        # move everything else to STDERR
        if print_result(
            result,
            show_diff=interactive or diff,
            stderr=is_stdin,
            output_format=config.output_format,
            output_template=config.output_template,
        ):
            dirty.add(result.path)
            if autofix and result.violation and result.violation.autofixable:
                autofixes += 1
        if result.violation:
            left[result.path] = left.get(result.path, 0) + 1
        if result.error:
            exit_code |= 2
        # The fixes applied to a file, after its violations.
        if result.applied:
            fixed += result.applied
            left[result.path] = result.remaining
        if interactive and result.violation and result.violation.autofixable:
            autofixes += 1
            answer = click.prompt(
                "Apply autofix?", default="y", type=click.Choice("ynq", False)
            )
            if answer == "y":
                generator.respond(True)  # noqa: B038
            elif answer == "q":
                break

    if any(left.values()):
        exit_code |= 1
    splash(visited, dirty, autofixes, fixed)
    ctx.exit(exit_code)


@main.command()
@click.pass_context
# Over stdio only (#15). --stdio is taken, for the clients that pass it.
@click.option(
    "--stdio",
    is_flag=True,
    expose_value=False,
    help="Serve LSP over stdio (the default)",
)
@click.option(
    "--debounce-interval",
    type=float,
    default=LSPOptions.debounce_interval,
    help="Delay in seconds for server-side debounce",
)
def lsp(ctx: click.Context, debounce_interval: float) -> None:
    """
    Start server for:
    https://microsoft.github.io/language-server-protocol/
    """
    from .lsp import LSP

    main_options = ctx.obj
    lsp_options = LSPOptions(debounce_interval=debounce_interval)
    ctx.exit(LSP(main_options, lsp_options).start())


@main.command()
@click.pass_context
@click.argument("rules", nargs=-1, required=True, type=str)
def test(ctx: click.Context, rules: Sequence[str]) -> None:
    """
    test lint rules and their VALID/INVALID cases
    """
    options: Options = ctx.obj
    qual_rules = [parse_rule(rule, Path.cwd().resolve()) for rule in rules]
    if not options.custom_rules:
        require_builtin(ctx, qual_rules)
    run_rule_tests(ctx, options, qual_rules)


def run_rule_tests(
    ctx: click.Context, options: Options, rules: Sequence[QualifiedRule]
) -> None:
    """
    Run the tests of ``rules`` on the new engine (#21). The config of the current
    directory applies (``enable-root-import``, the switch for custom rules).
    Exits with 5 when no test ran, as unittest and pytest do: no standard
    defines it.
    """
    config = generate_config(options=options)
    config.enable, config.disable = list(rules), []
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for case in generate_test_cases(load_rules(config)):
        suite.addTest(loader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.testsRun:
        ctx.exit(5)
    if not result.wasSuccessful():
        ctx.exit(1)


@main.command()
@click.pass_context
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
def debug(ctx: click.Context, paths: Sequence[Path]) -> None:
    """
    print materialized configuration for paths
    """
    options: Options = ctx.obj

    if not paths:
        paths = [Path.cwd()]

    try:
        from rich import print as pprint
    except ImportError:
        # Not pprint.pprint, which takes the second argument as the stream.
        pprint = print  # type: ignore[assignment]

    pprint(options)

    for path in paths:
        path = path.resolve()
        # A rule that cannot be loaded is an error, with its config (#40).
        config = generate_config(path, options=options, check=True)
        enabled = load_rules(config)

        pprint(">>> ", path)
        pprint(config)
        pprint("enabled:", [f"{rule.__module__}:{rule.__name__}" for rule in enabled])


@main.command(name="validate-config")
@click.pass_context
@click.argument(
    "path", nargs=1, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
def validate_config_command(ctx: click.Context, path: Path) -> None:
    """
    validate the config provided
    """
    options: Options = ctx.obj
    errors = validate_config(path, custom_rules=options.custom_rules)
    # As the other commands show an error of the config, with 2 (#100).
    for error in errors:
        click.echo(f"Error: {error}", err=True)
    if errors:
        ctx.exit(2)
