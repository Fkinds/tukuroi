# Contributing to Fixit

## Setup

Fixit supports the two newest series of Python: 3.14 and 3.15. It uses [uv][]
to manage its environment. Once uv is installed, create the environment from
`uv.lock`, with every extra and dependency group of `pyproject.toml`:

```shell-session
$ make install
```

uv takes the version of Python from `.python-version` (3.14), and installs it
when needed. To use another version, set `UV_PYTHON`:

```shell-session
$ UV_PYTHON=3.15 make install
```

## Developing

`make` runs each command with `uv run`, in the environment of `uv.lock`, so the
environment needs no activation. To run Fixit from the checkout:

```shell-session
$ uv run fixit [args]
```

To run the test suite, type checker, and linters:

```shell-session
$ make test

$ make lint
```

To measure which lines and branches of Fixit the tests run, with coverage.py:

```shell-session
$ make coverage
```

It lists the lines and branches that no test runs, and fails when the total goes
below `fail_under` in `pyproject.toml`: 100%. CI runs the tests this way, on
each version of Python and each system that it tests, and shows the table on the
page of the run. Code that cannot run by its design, such as the last branch of
a check of every case, raises `AssertionError` with the reason, or calls
`typing.assert_never`; coverage leaves those lines out. Do not leave out code
that a test can run.

To format code and sort imports:

```shell-session
$ make format
```

[prek][] runs the checks of `prek.toml` before each commit: ruff, `fixit lint`
and the copyright header on the files that `make lint` checks, [zizmor][] on the
workflows of `.github/workflows`, and its built-in checks (whitespace, line
endings, TOML and YAML syntax, large files, private keys) on every file. It
checks the commit message too (see below). `make install` installs prek; install
its Git hooks once:

```shell-session
$ uv run prek install
```

To run every check on every file, as CI does:

```shell-session
$ uv run prek run --all-files
```

zizmor runs offline here, with no token. CI runs it with the checks that ask
GitHub too: that each action is pinned to a commit of its own repository, that
the comment next to it has the version of that commit, and that no action has a
known vulnerability.

Documentation is built using sphinx. You can generate and view the documentation
locally in your browser:

```shell-session
$ make html

$ open html/index.html
```

To run the full test, typecheck, lint suite, and build the docs all at once:

```shell-session
$ make
```

The dependencies are in `pyproject.toml`: those of the package, its extras
(`lsp`, `pretty`), and the dependency groups for developing (`dev`, `docs`),
which are not part of the package. After changing them, update `uv.lock` with
`make lock`, and commit both. CI installs from `uv.lock`, and fails when it does
not match `pyproject.toml`.

CI builds the package as the release will be built: it takes the build backend
(`[build-system]` of `pyproject.toml`) from `build-constraints.txt`, with
hashes, which `make lock` writes from `build-constraints.in`. `make lock` keeps
the versions that the files have; pass `--upgrade` to `uv lock` and `uv pip
compile` for newer ones. CI uses the version of uv in `UV_VERSION` of its
workflows.

[Renovate][] keeps them up to date, as `.github/renovate.json5` says. Each
Monday morning (Asia/Tokyo) it opens pull requests for the versions released at
least 7 days before: the dependencies of `pyproject.toml`, the actions of the
workflows (pinned to commit SHAs), and `UV_VERSION`. The updates that are not
major come in one pull request for each kind, and a major update in one of its
own. On the first day of each month, it updates the rest of `uv.lock` and
`build-constraints.txt`. It opens the fixes of the vulnerabilities that GitHub
finds too. The Dependency Dashboard issue lists what is pending. Nothing is
merged automatically. The versions of Python (`.python-version`,
`requires-python`) are left as the project chooses them.

To check what `uv.lock` pins, with every extra and group, against the known
vulnerabilities of [osv.dev][osv]:

```shell-session
$ make audit
```

`.github/workflows/audit.yml` runs it each day, and on the pull requests that
change the dependencies. Each day it runs zizmor with GitHub too, for the
actions: they are pinned to commit SHAs, for which GitHub sends no alerts. A
failed run is the alert. A vulnerability that Fixit cannot fix yet goes in
`[tool.uv.audit]` of `pyproject.toml`, with its reason and its issue in a
comment: in `ignore-until-fixed` while no release fixes it, in `ignore` when it
does not affect Fixit. Renovate opens the fixes of what osv.dev has for
`build-constraints.txt` and the dependencies of `pyproject.toml` too.


## Submitting PRs

Before submitting PRs, please address the following items:

- Add tests exercising any fixed bugs or new functionality
- Document any changes to configuration or behavior
- Apply formatting, regenerate documentation, and run the test suite (see above)
- Summarize the high level features or behavior changes in your commit message

### Commit messages

Commit messages, and the titles of pull requests, follow
[Conventional Commits 1.0.0][cc]:

```
<type>(<scope>)!: <description>

<body>

Closes #123
```

- `type` is one of `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
  `refactor`, `revert`, `style`, `test` (the types of commitlint's
  config-conventional).
- `(<scope>)` is optional, such as `(config)` or `(lsp)`. `!` marks a breaking
  change.
- The first line is up to 100 characters. The description of a commit is in
  English, in the imperative mood: `fix(config): stop at the first value that
  fixit cannot use`.
- The merge commits of GitHub, and `Revert` commits, pass as they are.

The commit-msg hook of prek checks each message with `cz check` of
[commitizen][], as configured in `pyproject.toml`, and CI checks the commits and
the title of each pull request. To check a message by hand:

```shell-session
$ uv run cz check -m "fix(config): stop at the first value that fixit cannot use"
```

In a review, fix a commit with `git commit --fixup` (or `--squash`): the hook
lets its `fixup!` message pass. CI fails while a pull request has such a commit,
or a title like it. Squash them into the commits that they fix before the merge:

```shell-session
$ git rebase -i --autosquash origin/main
```

For most developers, we recommend using the [github cli][gh] to submit pull
requests:

```shell-session
$ gh pr create
```

If you are a Fixit maintainer, we recommend using [ghstack][] (see below):

```shell-session
$ ghstack submit
```

## Code style

Fixit uses [ruff][] to format code, sort imports, and lint, with ruff's default
rules and its `S` rules: the security checks of [bandit][]. The settings are in
`pyproject.toml`. `make lint` and CI check them. A finding that is safe by
design gets `# noqa` with the rule, and a comment that says why.

You can ensure your changes are well formatted, and imports are sorted:

```shell-session
$ make format
```

`make format` does not apply other lint fixes. To apply the fixes that ruff
can make safely:

```shell-session
$ uv run ruff check --fix src/fixit/ scripts/
```

If you are using VS Code as your editor, you can use the
[Ruff extension for VS Code](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff)
to format, sort imports, and lint while developing.

`.git-blame-ignore-revs` lists commits that only reformat code. GitHub skips
them in blame views. To skip them in `git blame` locally:

```shell-session
$ git config blame.ignoreRevsFile .git-blame-ignore-revs
```


## VS Code

Make sure you've created an environment for Fixit:

```shell-session
$ make install
```

Now, the VS Code Python module should be able to find and offer the local
`.venv` path as an option for your active Python environment, and should then
be aware of what libraries are available, and enable "Go To Definition" for
those packages.


## git-branchless

[git-branchless](https://github.com/arxanas/git-branchless) is a useful tool
for improving your local git CLI workflow, especially within a stack of commits.
It provides a "smartlog" command (`git sl`) to help visual the hierarchy of
commits and branches in your checkout, as well as `next`/`prev` commands to
make moving through your stacks even easier:

```shell-session
amethyst@luxray ~/workspace/Fixit docs  » git sl
⋮
◇ a80603c 226d (0.x) Update 'master' (branch) references to 'main' (#220)
⋮
◆ c3f8ff9 52d (main, ᐅ docs) Include scripts dir in linters
┃
◯ 33863f4 52d (local-rules) Simple example of local rule for copyright headers
```

git-branchless is a Rust package, and can be installed with cargo:

```shell-session
$ cargo install --locked git-branchless
```

Once installed to your system, it must be enabled on each git repo that you
want to use it with, so that it can install hooks and new commands:

```shell-session
$ git branchless init
```


## ghstack

[ghstack][] is a tool for simplifying and
automating the process of submitting stacked PRs, where each PR in the stack
builds and depends on changes from the previous PR.

Unfortunately, ghstack requires push access to the upstream repo, so this can
only be used by project maintainers.

ghstack is a Python package, and we recommend installing it using [uv][]:

```shell-session
$ uv tool install ghstack
```

Once installed, you can run ghstack to submit a stack of PRs from your active
branch, one PR for each commit in the branch:

```shell-session
$ ghstack submit
```

Note that any PRs created with ghstack *cannot* be merged using the normal
Github merge UI — you must use ghstack to "land" the stack so that it can
automatically rebase and merge each commit in the correct order, and update
any outstanding PRs accordingly. You can do this by passing the URL to the
last PR in the stack that you want to land:

```shell-session
$ ghstack land $PR_URL
```

[gh]: https://cli.github.com/
[ghstack]: https://github.com/ezyang/ghstack
[bandit]: https://bandit.readthedocs.io/
[cc]: https://www.conventionalcommits.org/en/v1.0.0/
[commitizen]: https://commitizen-tools.github.io/commitizen/
[osv]: https://osv.dev/
[pipx]: https://pypa.github.io/pipx/
[prek]: https://prek.j178.dev/
[Renovate]: https://docs.renovatebot.com/
[ruff]: https://docs.astral.sh/ruff/
[uv]: https://docs.astral.sh/uv/
[zizmor]: https://docs.zizmor.sh/

## Supported Python versions

This fork supports only the two newest minor versions of CPython, including
their free-threaded builds. As of November 2026, these are 3.14 and 3.15
(and 3.14t and 3.15t).

- Any patch release of a supported minor version is supported. CI tests the
  latest patch release of each on Ubuntu, and of the builds with the GIL on
  macOS too. Whether to support Windows is open (#124).
- When a new minor version is released, add it once CI passes on it, and drop
  the oldest supported minor version in the same change, so that exactly two
  remain.
- Keep `requires-python` in `pyproject.toml` and the test matrix in
  `.github/workflows/ci.yml` in line with this list.

The newest version can still have experimental features and bugs, and the
ecosystem takes time to catch up, so the previous version stays supported.
Older versions are dropped to keep the set of runtimes we maintain small.
Under PEP 602, each minor version gets two years of full support, so the two
newest minor versions are the ones that still receive bug fixes.

## Relationship to upstream

This repository is a fork of `Instagram/Fixit`. It stopped merging upstream
`main` when it moved its development tools to ruff (#33). The reformatted code
would conflict with almost every upstream change. To use an upstream change,
review it and port it on its own.
