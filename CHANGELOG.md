# Changelog

## v3.0.0 (unreleased)

The first release of tukuroi, an unofficial fork of `Instagram/Fixit` after its
version 2.2.1. To move from Fixit, see [Coming from Fixit] in the README.

### BREAKING CHANGE

- **names**: the package, the command, the configuration (`[tool.tukuroi]`,
  `tukuroi.toml`, `.tukuroi.toml`), the environment variable
  `TUKUROI_CUSTOM_RULES`, the built-in rules (`tukuroi.rules`) and the
  pre-commit hooks are named tukuroi. The names of Fixit are not read.
- **engine**: the rules run on `tukuroi.core`, built on Python's `ast`, in place
  of LibCST. A rule is a subclass of `tukuroi.Rule`: the rules of Fixit need to
  be ported.
- **python**: CPython 3.14 and 3.15 only, with their free-threaded builds.
- **rules**: fewer built-in rules: ruff has the others.
- **config**: an unknown key, a value of the wrong type, and a rule that cannot
  be loaded are errors, with exit status 2. `python-version`, `options` and
  `tags` are no longer supported.
- **format**: the fixed files are formatted only with `formatter = "ruff"`
  (`pip install "tukuroi[ruff]"`); `black` and `ufmt` are gone.
- **output**: `output-template` takes the names of its fields only.
- **lsp**: the server talks over stdio only.
- **api**: `print_result()` takes an output format as `output=`, and
  `Config.formatter` and `Config.output_format` are names.

### Feat

- **security**: `--no-custom-rules` (or `TUKUROI_CUSTOM_RULES`) loads only the
  built-in rules, for a repository that you do not trust, and the search for
  configurations stops at the root of the repository.
- **plugins**: other packages add formatters and output formats through entry
  points.
- **output**: the output formats `json`, one JSON document of the results, and
  `sarif`, a log of SARIF 2.1.0 for GitHub code scanning. They print nothing
  else on stdout: the errors and the diffs go to stderr.
- **rules**: `report()` takes the span to report (`span=`) and the imports that
  its fix leaves unused (`unused_imports=`), which tukuroi takes out;
  `add_import()` and `remove_import()`; the names of imports follow the scopes
  of Python.
- **fix**: a fix that would break the code is not applied, with a warning.
- **rules**: `tukuroi.rules.strict`, rules that are not enabled with
  `tukuroi.rules`: `NoValueObjectDefault` reports the defaults of the fields of
  value objects, those of dataclasses and of attrs.
- **cli**: `validate-config` loads the rules and the plugins that a config names.

### Fix

- **lint**: a rule that ends its process (a crash, `os._exit`) gives that file
  an error, and the other files their results.
- **lint**: a symbolic link to a directory out of the project no longer stops
  `lint` and `fix`: a link to a directory is not walked, as git keeps the link.
  The files of a directory are found by name, with `pathspec` alone, which reads
  `.gitignore` as git does: `trailrunner` is no longer a dependency.
- **lsp**: the server reads the configuration again for each change.
- **fix**: with `fix -`, `--print-metrics` prints on stderr: stdout is the fixed
  source alone.

[Coming from Fixit]: https://github.com/Fkinds/tukuroi#coming-from-fixit

## Fixit

The versions below are those of `Instagram/Fixit`, with the numbers of its
issues and pull requests.

## 2.2.0 - 2025-11-04

New:

- Add `fixit lsp` subcommands for LSP support by @llllvvuu (`Instagram/Fixit#390`)
- Add `fixit validate-config` command by @surge119 (`Instagram/Fixit#480`)
- Make format of fixit's terminal output configurable by @jvllmr (`Instagram/Fixit#437`)
- Allow a targeted (named rule) enable to override a module disable by @amyreese (`Instagram/Fixit#464`)
- Lintrule collections abc by @surge119 (`Instagram/Fixit#460`)
- Add fixit rule for variadic callable syntax by @yangdanny97 (`Instagram/Fixit#501`)

Fixed:

- Fix Minor Typo in the Docs by @max-muoto (`Instagram/Fixit#407`)
- Add Logging for Timing Metrics by @surge119 (`Instagram/Fixit#473`)
- Update DeprecatedABCImport Rule by @surge119 (`Instagram/Fixit#474`)
- Add More Metrics to be Logged by LoggerHook by @surge119 (`Instagram/Fixit#475`)
- Improved the Handling of Errors in Rule Collection by @surge119 (`Instagram/Fixit#479`)
- Fix validate config by @surge119 (`Instagram/Fixit#481`)
- Allow dash in rule names by @zsol (`Instagram/Fixit#503`)
- Add basic pyrefly configuration by @maggiemoss (`Instagram/Fixit#505`)
- Update pyrefly configuration. by @rchen152 (`Instagram/Fixit#507`)
- Make 3.9 minimum supported Python by @amyreese (`Instagram/Fixit#510`)
- Replace hatch with make+uv, separate docs builds by @amyreese (`Instagram/Fixit#511`)
- Fix version specifier matching for prerelease versions by @amyreese (`Instagram/Fixit#515`)
- Enable testing on 3.14/3.14t by @amyreese (`Instagram/Fixit#516`)
- Better generated docs, add no-index by @amyreese (`Instagram/Fixit#517`)


## 2.1.0 - 2023-10-25

Minor feature release

New:

- Lint and fix via STDIN by passing `-` as path (`Instagram/Fixit#388`)
- Skip linting files when no rules enabled (`Instagram/Fixit#379`)

Fixed:

- Reporting violations on `Module` nodes (`Instagram/Fixit#368`, `Instagram/Fixit#367`)
- Incorrect auto-fixes from `CompareSingletonPrimitivesByIs` (`Instagram/Fixit#391`, `Instagram/Fixit#378`, `Instagram/Fixit#375`)
- Parsing error for `typing.Literal` in `NoStringTypeAnnotation` rule (`Instagram/Fixit#400`, `Instagram/Fixit#377`)
- Error handling when rules fail to import in child processes (`Instagram/Fixit#401`, `Instagram/Fixit#381`)

Thanks:

```
$ git shortlog -sn v2.0.0.post1...
     8  Amethyst Reese
     2  LW
     1  Dave Turner
     1  Uzumaki
     1  Yajus Gakhar
     1  rembridge
```

## 2.0.0 - 2023-07-17

This is the first stable release with the major rework of Fixit. There are many
breaking changes since the `0.1.4` release, including configuration formats,
CLI commands, and lint rule APIs. Existing users should look at the
[Upgrade Guide][] for help migrating to the latest version.

[Upgrade Guide]: https://fixit.rtfd.io/en/latest/upgrade.html

### Major Changes

- Hierarchical configuration via TOML format
- Support for in-repo custom lint rules relative to project configuration
- Simplified CLI binary with subcommands to check for errors and apply fixes
- Interactive review and application of autofixes
- Dedicated API for integration with alternate frontends
- Overhauled documentation, with quick start guide
- Integration with pre-commit
- Support for configurable target version and selection of applicable rules
- Support for selecting and filtering rules by tags at runtime

### New Rules

- Added `UseAsyncSleepInAsyncDef` (`Instagram/Fixit#297`)
- Added `DeprecatedUnittestAsserts` (`Instagram/Fixit#314`)

## 2.0.0b1 - 2023-06-26

### Beta Release

This is a beta release of a major rework of Fixit. There are many breaking
API changes since the `0.1.4` release – existing users should wait for a stable
release before upgrading.

Please see the new [User Guide][] for an overview of the new version.
A migration guide is planned, but not yet available.

[User Guide]: https://fixit.rtfd.io/en/latest/guide.html

### Major Changes

- New `test` command for validating local lint rules (`Instagram/Fixit#300`)
- Support for configurable target version and selection of applicable rules (`Instagram/Fixit#332`)
- Support for selecting and filtering rules by tags at runtime (`Instagram/Fixit#333`)
- Support for `# lint-ignore` and `# lint-fixme` directives (`Instagram/Fixit#334`)

### New Rules

- Added `UseAsyncSleepInAsyncDefRule` (`Instagram/Fixit#297`)
- Added `DeprecatedUnittestAssertsRule` (`Instagram/Fixit#314`)

## 2.0.0a1 - 2023-04-07

### Alpha Release

This is an alpha release of a major rework of Fixit. There are many breaking
API changes since the `0.1.4` release – existing users should wait for a stable
release before upgrading.

Please see the new [User Guide][] for an overview of the new version.
A migration guide is planned, but not yet available.

[User Guide]: https://fixit.rtfd.io/en/latest/guide.html

### Major Changes

- Hierarchical configuration via TOML format
- Support for in-repo custom lint rules relative to project configuration
- Simplified CLI binary with subcommands to check for errors and apply fixes
- Interactive review and application of autofixes
- Dedicated API for integration with alternate frontends
- Overhauled documentation, with quick start guide
- Integration with pre-commit


## 0.1.4 - 2021-07-30
### Updated
- Fix typo [#163](https://github.com/Instagram/Fixit/pull/163)
- Refactor ipc_main [#175](https://github.com/Instagram/Fixit/pull/175)
- Refactor search yaml [#172](https://github.com/Instagram/Fixit/pull/172)
- Bug fix for UseTypesFromTypingRule [#178](https://github.com/Instagram/Fixit/pull/178)
- Fix sentinel type error [#187](https://github.com/Instagram/Fixit/pull/187)
- Autofix docstrings [#190](https://github.com/Instagram/Fixit/pull/190)
- Fix pyre type-check errors [#196](https://github.com/Instagram/Fixit/pull/196)
- Add JSON Schema for Fixit configs [#188](https://github.com/Instagram/Fixit/pull/188)
- Adds allow_list_rules setting for configs [#184](https://github.com/Instagram/Fixit/pull/184)
- Adds allow_list_rules to schema [#197](https://github.com/Instagram/Fixit/pull/197)
- Fix run_rules bug [#200](https://github.com/Instagram/Fixit/pull/200)

## 0.1.3 - 2020-12-09

### New Rules
- Add NoRedundantArgumentsSuperRule [#154](https://github.com/Instagram/Fixit/pull/154)
- Add ExplicitFrozenDataclassRule [#158](https://github.com/Instagram/Fixit/pull/158)
- Add UseLintFixmeCommentRule [#161](https://github.com/Instagram/Fixit/pull/161)
- Add UseAssertInRule [#159](https://github.com/Instagram/Fixit/pull/159)

### Updated
- await async rule does not account for decorators [#150](https://github.com/Instagram/Fixit/pull/150)
- Allow glob patterns instead of parent dirs for matching configs [#156](https://github.com/Instagram/Fixit/pull/156)

## 0.1.2 - 2020-10-29

### New Rules
- Add SortedAttributesRule [#149](https://github.com/Instagram/Fixit/pull/149)

### Added
- New unified `fixit` CLI [#148](https://github.com/Instagram/Fixit/pull/148)

### Updated
- Add `use_noqa` configuration to control support of the `noqa` Flake8 suppression comment. Defaults to `False` [#151](https://github.com/Instagram/Fixit/pull/151)

## 0.1.1 - 2020-10-08

### New Rules
- Add UseAssertIsNotNoneRule [#144](https://github.com/Instagram/Fixit/pull/144)
- Add MissingHeaderRule to check copyright header comments [#142](https://github.com/Instagram/Fixit/pull/142)
- Add NoStringTypeAnnotationRule [#140](https://github.com/Instagram/Fixit/pull/140)
- Add NoNamedTupleRule [#136](https://github.com/Instagram/Fixit/pull/136)
- Add NoAssertTrueForComparisonsRule to catch some incorrect uses of assertTrue() [#135](https://github.com/Instagram/Fixit/pull/135)
- Add CollapseIsinstanceChecksRule [#116](https://github.com/Instagram/Fixit/pull/116)
- Add NoUnnecessaryFormatStringRule and UseFstringRule [#101](https://github.com/Instagram/Fixit/pull/101)
- Add NoRedundantLambdaRule. [#112](https://github.com/Instagram/Fixit/pull/112)

### Added
- add_new_rule CLI for adding new rule file [#123](https://github.com/Instagram/Fixit/pull/123), [#131](https://github.com/Instagram/Fixit/pull/131)

### Updated
- Ensure first lines remain intact with AddMissingHeaderRule [#143](https://github.com/Instagram/Fixit/pull/143)
- Documentation improvements: [#113](https://github.com/Instagram/Fixit/pull/113), [#117](https://github.com/Instagram/Fixit/pull/117),
[#118](https://github.com/Instagram/Fixit/pull/118), [#120](https://github.com/Instagram/Fixit/pull/120)
[#133](https://github.com/Instagram/Fixit/pull/133), [#138](https://github.com/Instagram/Fixit/pull/138)
- Improve test message [#137](https://github.com/Instagram/Fixit/pull/137)

## 0.1.0 - 2020-09-02

### Added

 - First public release of Fixit.
 - Python Lint Framework based on LibCST with autofix functionality.
 - Comes pre-packaged with a set of built-in lint rules.
 - Provides scripts for linting, autofixing and inserting lint suppressions into source code.
 - Provides development kit to build and enforce custom lint rules.
 - Full suite of unit tests.
