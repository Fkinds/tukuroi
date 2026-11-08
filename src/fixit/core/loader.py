# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
How the new engine imports the rules named in a config (#21).

A name is a module (``fixit.rules``, ``mycompany.lint_rules``), or a module in
the repo relative to the directory of the config that names it (``.rules``),
with the name of one rule after a colon (``.rules:NoBadName``). For a module in
the repo, the directory is part of the name: ``.rules`` of two configs are two
modules.

The modules in the repo of a directory are imported under a package of their
own, named after the directory and at the top level: ``..`` in them cannot go
above the directory. Every module is imported once in a process, so a rule is
one class however it is named; a change to a module needs a new process (a
restart of ``fixit lsp``).

The errors keep the name and the words of the libcst engine
(``CollectionError: could not import rule(s) .rules from <dir>``).

:func:`collect_rules` turns the ``enable`` and ``disable`` of a config into
rules. A module that cannot be imported is a warning (on the logger
``fixit.config``, as before), given once in a process. A package imported
through ``enable-root-import`` is not used for a file of another root: its
module is the one of the root that imported it first.
"""

import hashlib
import importlib
import importlib.machinery
import inspect
import logging
import pkgutil
import re
import sys
import types
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from .rule import Rule

_NAME = re.compile(
    r"""
    ^
    (?P<module>\.?[a-zA-Z0-9_]+(\.[a-zA-Z0-9_-]+)*)
    (?::(?P<name>[a-zA-Z0-9_-]+))?
    $
    """,
    re.VERBOSE,
)


class CollectionError(RuntimeError):
    """A module of rules, or a rule, cannot be imported or found."""


@dataclass(frozen=True, slots=True)
class RuleName:
    """
    A module of rules, or one rule of it. ``root`` is the directory of the config
    that names a module in the repo (``.rules``), and ``None`` for another.
    """

    module: str
    name: str | None = None
    root: Path | None = field(default=None)

    @classmethod
    def parse(cls, text: str, root: Path) -> Self:
        """The name in ``text``, from a config in ``root``. ``ValueError`` if wrong."""
        match = _NAME.match(text)
        if match is None:
            raise ValueError(f"invalid rule name {text!r}")
        module = match["module"]
        local = module.startswith(".")
        return cls(module, match["name"], root.resolve() if local else None)

    @property
    def local(self) -> bool:
        """Whether the module is in the repo, relative to ``root``."""
        return self.module.startswith(".")

    def __str__(self) -> str:
        return self.module + (f":{self.name}" if self.name else "")


def import_rules(name: RuleName) -> tuple[type[Rule], ...]:
    """
    The rules of ``name``: all the rules of its module (and of the modules of a
    package, not of its packages), sorted by name, or the one rule named, with
    or without "Rule" at the end of its name. Raises ``CollectionError``.
    """
    where = f" from {name.root}" if name.local else ""
    try:
        module = _import(name)
        rules = _rules_of(module)
    except ModuleNotFoundError as e:
        missing = e.name or ""
        if _is_part_of(missing, _absolute(name)):
            raise CollectionError(f"could not import rule(s) {name}{where}") from e
        message = f"could not import rule(s) {name}{where}: {type(e).__name__}: {e}"
        raise CollectionError(message) from e
    if name.name is None:
        return tuple(rules[key] for key in sorted(rules))
    for key in (name.name, f"{name.name}Rule"):
        if key in rules:
            return (rules[key],)
    where = f" in {name.root}" if name.local else ""
    raise CollectionError(f"could not find rule {name}{where}")


def _package(root: Path) -> str:
    """The top-level package of the modules in ``root``, made the first time."""
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    package = f"__fixit_local_{digest}__"
    if package not in sys.modules:
        spec = importlib.machinery.ModuleSpec(package, None, is_package=True)
        spec.submodule_search_locations = [str(root)]
        module = types.ModuleType(package)
        module.__spec__ = spec
        module.__path__ = [str(root)]
        sys.modules[package] = module
    return package


# Until the last stage of #21, the built-in rules of the new engine are in
# fixit.core.rules, and fixit.rules has those of the libcst engine: the name
# fixit.rules imports fixit.core.rules. The last stage moves the rules to
# fixit/rules, and takes this out.
_ALIAS, _ALIASED = "fixit.rules", "fixit.core.rules"


def _absolute(name: RuleName) -> str:
    """The name under which the module of ``name`` is imported."""
    if name.local and name.root is not None:
        return _package(name.root) + name.module
    if name.module == _ALIAS or name.module.startswith(f"{_ALIAS}."):
        return _ALIASED + name.module.removeprefix(_ALIAS)
    return name.module


def _import(name: RuleName) -> types.ModuleType:
    return importlib.import_module(_absolute(name))


def _is_part_of(missing: str, module: str) -> bool:
    """Whether ``missing`` is ``module``, or a package it is in."""
    return module == missing or module.startswith(f"{missing}.")


def _rules_of(module: types.ModuleType) -> dict[str, type[Rule]]:
    """The rules in ``module``, and in the modules of a package, by name."""
    rules = dict(inspect.getmembers(module, _is_rule))
    if hasattr(module, "__path__"):
        for info in pkgutil.iter_modules(module.__path__):
            if not info.ispkg:
                submodule = importlib.import_module(f"{module.__name__}.{info.name}")
                rules.update(_rules_of(submodule))
    return rules


def _is_rule(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, Rule) and value is not Rule


# The packages of the rules that come with Fixit. With custom rules turned off
# (#12), the engine imports no other rules.
BUILTIN_PACKAGES = ("fixit.rules",)

log = logging.getLogger("fixit.config")

# The warnings already given: each one is given once in a process (#21).
_WARNED: set[str] = set()

# The top-level packages imported through enable-root-import, and the path
# that they were imported from.
_ROOT_IMPORTED: dict[str, Path] = {}


def is_builtin(name: RuleName) -> bool:
    """Whether ``name`` names rules that come with Fixit, not custom rules."""
    return any(
        name.module == package or name.module.startswith(f"{package}.")
        for package in BUILTIN_PACKAGES
    )


def collect_rules(
    enable: Sequence[RuleName],
    disable: Sequence[RuleName],
    *,
    root_import: Path | None = None,
    custom_rules: bool = True,
) -> tuple[type[Rule], ...]:
    """
    The rules of ``enable`` without those of ``disable``, but for the rules that
    ``enable`` names one by one, sorted by name. A module that cannot be imported
    is a warning. ``root_import`` is the path that ``enable-root-import`` adds to
    ``sys.path``. With ``custom_rules`` false, only the built-in rules are
    imported: the others in ``enable`` are skipped with a warning, those in
    ``disable`` and ``root_import`` silently.
    """
    if not custom_rules:
        root_import = None
    enabled: set[type[Rule]] = set()
    named: set[type[Rule]] = set()
    disabled: set[type[Rule]] = set()
    with _on_path(root_import):
        for name in enable:
            if not (custom_rules or is_builtin(name)):
                _warn(f"Skipped rules '{name}': custom rules are turned off")
                continue
            rules = _load(name, root_import)
            if rules is not None and not rules and name.name is None:
                _warn(
                    f"No rules in '{name}'"
                    + (f" from {name.root}" if name.local else "")
                )
            enabled.update(rules or ())
            if name.name is not None:
                named.update(rules or ())
        for name in disable:
            if custom_rules or is_builtin(name):
                disabled.update(_load(name, root_import) or ())
    rules = enabled - (disabled - named)
    return tuple(sorted(rules, key=lambda r: (r.name(), r.__module__)))


def _load(name: RuleName, root_import: Path | None) -> tuple[type[Rule], ...] | None:
    """The rules of ``name``, or ``None`` after a warning."""
    top = name.module.partition(".")[0]
    if not name.local and top in _ROOT_IMPORTED and _ROOT_IMPORTED[top] != root_import:
        path = _ROOT_IMPORTED[top]
        message = f"could not import rule(s) {name}: imported from another root, {path}"
        _warn(f"Failed to load rules '{name.module}': CollectionError: {message}")
        return None
    try:
        rules = import_rules(name)
    # Importing a rule runs its code, which can raise any exception.
    except Exception as e:  # noqa: BLE001
        _warn(f"Failed to load rules '{name.module}': {type(e).__name__}: {e}")
        return None
    if root_import is not None and not name.local and _is_under(top, root_import):
        _ROOT_IMPORTED.setdefault(top, root_import)
    return rules


def _is_under(package: str, path: Path) -> bool:
    """Whether the module ``package`` was imported from under ``path``."""
    module = sys.modules.get(package)
    places = [getattr(module, "__file__", None), *getattr(module, "__path__", [])]
    return any(p and Path(p).resolve().is_relative_to(path) for p in places)


@contextmanager
def _on_path(path: Path | None) -> Iterator[None]:
    """``path`` at the end of ``sys.path``, while in the block."""
    if path is None:
        yield
        return
    sys.path.append(str(path))
    try:
        yield
    finally:
        sys.path.remove(str(path))


def _warn(message: str) -> None:
    if message not in _WARNED:
        _WARNED.add(message)
        log.warning(message)
