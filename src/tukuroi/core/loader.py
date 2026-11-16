# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
How the new engine imports the rules named in a config (#21).

A name is a module (``tukuroi.rules``, ``mycompany.lint_rules``), or a module in
the repo relative to the directory of the config that names it (``.rules``),
with the name of one rule after a colon (``.rules:NoBadName``). For a module in
the repo, the directory is part of the name: ``.rules`` of two configs are two
modules.

The modules in the repo of a directory are imported under a package of their
own, named after the directory and at the top level: ``..`` in them cannot go
above the directory. Every module is imported once in a process, so a rule is
one class however it is named; a change to a module needs a new process (a
restart of ``tukuroi lsp``).

:meth:`RuleLoader.collect` turns the ``enable`` and ``disable`` of a config
into rules. A name whose rules cannot be loaded is a :class:`CollectionError`
(#40): the module cannot be imported, its code raises, it has no rules, or the
rule is not in it. A package imported through ``enable-root-import`` cannot be
used for a file of another root: its module is the one of the root that
imported it first. The rules skipped with custom rules turned off are a warning
(on the logger ``tukuroi.config``), given once in a process (:class:`OnceLog`).

A :class:`CollectionError` says why (#201): ``could not import rule(s) .rules
from <dir>: ModuleNotFoundError: No module named '.rules'``, with a module in
the repo named as the config names it. A package that cannot be found at all,
with no ``enable-root-import``, gets a hint at the end: it may be in the repo.
When another module of a package than the one named fails, the error says
which (#213): ``could not import rule(s) .rules from <dir>: in .rules.wip:
...``.

One rule of a package (``.rules:NoBadName``) is imported from the modules of
the package that define a class of its name, as their source says (#213): the
other modules are not imported, nor run. When none does, all of them are, as
for the rules of a whole package.
"""

import ast
import functools
import hashlib
import importlib
import importlib.machinery
import inspect
import logging
import pkgutil
import re
import sys
import threading
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
    or without "Rule" at the end of its name. Raises ``CollectionError``, or
    :class:`ModuleError` for another exception of a module of a package.
    """
    wanted = () if name.name is None else (name.name, f"{name.name}Rule")
    try:
        module = _import(name)
        rules = _rules_of(module, wanted)
    except ModuleNotFoundError as e:
        raise CollectionError(_could_not_import(name, e)) from e
    except ModuleError as e:
        if isinstance(e.__cause__, ModuleNotFoundError):
            message = _could_not_import(name, e.__cause__, e.module)
            raise CollectionError(message) from e.__cause__
        raise
    if not wanted:
        return tuple(rules[key] for key in sorted(rules))
    for key in wanted:
        if key in rules:
            return (rules[key],)
    where = f" in {name.root}" if name.local else ""
    raise CollectionError(f"could not find rule {name}{where}")


def _package(root: Path) -> str:
    """The top-level package of the modules in ``root``, made the first time."""
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    package = f"__tukuroi_local_{digest}__"
    if package not in sys.modules:
        spec = importlib.machinery.ModuleSpec(package, None, is_package=True)
        spec.submodule_search_locations = [str(root)]
        module = types.ModuleType(package)
        module.__spec__ = spec
        module.__path__ = [str(root)]
        sys.modules[package] = module
    return package


def _absolute(name: RuleName) -> str:
    """The name under which the module of ``name`` is imported."""
    if name.local and name.root is not None:
        return _package(name.root) + name.module
    return name.module


def _import(name: RuleName) -> types.ModuleType:
    return importlib.import_module(_absolute(name))


def _could_not_import(
    name: RuleName, error: BaseException, module: str | None = None
) -> str:
    """
    Why the rules of ``name`` cannot be imported: ``error``, in ``module`` when
    another module of a package fails (#213). A module in the repo is named as
    the config names it (``.rules``), not by its package.
    """
    reason = f"{type(error).__name__}: {error}"
    if module is not None:
        reason = f"in {module}: {reason}"
    where = ""
    if name.local and name.root is not None:
        reason = reason.replace(_package(name.root), "")
        where = f" from {name.root}"
    return f"could not import rule(s) {name}{where}: {reason}"


def _not_found(name: RuleName, error: BaseException | None) -> bool:
    """
    Whether ``error`` is that the top-level package of ``name``, not a module in
    the repo, is not found at all.
    """
    return (
        not name.local
        and isinstance(error, ModuleNotFoundError)
        and error.name == name.module.partition(".")[0]
    )


class ModuleError(Exception):
    """
    An exception of ``module``, a module of a package that rules are imported
    from, which is its cause (#213).
    """

    def __init__(self, module: str) -> None:
        super().__init__(module)
        self.module = module


def _rules_of(
    module: types.ModuleType, wanted: Sequence[str] = ()
) -> dict[str, type[Rule]]:
    """
    The rules in ``module``, and in the modules of a package (not of its
    packages), by name: the rule of a module later by name wins. With
    ``wanted``, the names of one rule (#213), only the modules whose source
    defines a class of one of them are imported; when none does, none if the
    package has the rule, and all of them if it does not.
    """
    rules = dict(inspect.getmembers(module, _is_rule))
    if not hasattr(module, "__path__"):
        return rules
    infos = [info for info in pkgutil.iter_modules(module.__path__) if not info.ispkg]
    if wanted:
        defining = [info for info in infos if _defines(info, wanted)]
        if defining or any(key in rules for key in wanted):
            infos = defining
    for info in infos:
        name = f"{module.__name__}.{info.name}"
        try:
            submodule = importlib.import_module(name)
        # Importing a module runs its code, which can raise any exception.
        except Exception as e:
            raise ModuleError(name) from e
        rules.update(_rules_of(submodule))
    return rules


def _defines(info: pkgutil.ModuleInfo, classes: Sequence[str]) -> bool:
    """
    Whether the source of the module of ``info`` defines one of ``classes`` at
    its top level. Without a source that can be read and parsed (a module in a
    zip, compiled, or with a syntax error), it does not say so.
    """
    directory = getattr(info.module_finder, "path", None)
    if directory is None:
        return False
    return not _top_classes(Path(directory) / f"{info.name}.py").isdisjoint(classes)


@functools.cache
def _top_classes(path: Path) -> frozenset[str]:
    """
    The names of the classes that the source at ``path`` defines at its top
    level: none without a source that can be read and parsed. It is read once
    in a process, as its module is imported once: a config is read for each
    file, and its rules loaded again.
    """
    try:
        tree = ast.parse(path.read_bytes())
    except OSError, SyntaxError:
        return frozenset()
    return frozenset(n.name for n in tree.body if isinstance(n, ast.ClassDef))


def _is_rule(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, Rule) and value is not Rule


# The hint for a package that is not found, with no enable-root-import (#201).
ROOT_IMPORT_HINT = "for a package in the repository, set enable-root-import"

# The packages of the rules that come with tukuroi. With custom rules turned off
# (#12), the engine imports no other rules.
BUILTIN_PACKAGES = ("tukuroi.rules",)

log = logging.getLogger("tukuroi.config")

# The attribute that marks a record of :class:`OnceLog`: a process of a pool
# sends it to the process that runs the pool, which gives it once too (#209).
ONCE = "tukuroi_once"


@dataclass
class OnceLog:
    """
    Warnings given once (#21), on the logger ``tukuroi.config``: the rules and
    the plugins (#169) skipped with custom rules turned off, and the configs of
    Fixit (#202). :data:`WARNINGS` are those of the process. A warning that a
    process of a pool gives comes to the process that runs the pool, which
    gives it once with its own (:meth:`handle`, #209).
    """

    given: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def warn(self, message: str) -> None:
        """Log ``message`` as a warning, unless it was given."""
        if self._first(message):
            log.warning(message, extra={ONCE: True})

    def handle(self, record: logging.LogRecord) -> None:
        """Log ``record``, a warning of another process, unless it was given."""
        if self._first(record.getMessage()) and log.isEnabledFor(record.levelno):
            log.handle(record)

    def _first(self, message: str) -> bool:
        """Whether ``message`` was not given, which it is from now on."""
        # The threads that take the records of a pool call it too.
        with self._lock:
            if message in self.given:
                return False
            self.given.add(message)
            return True


def is_builtin(name: RuleName) -> bool:
    """Whether ``name`` names rules that come with tukuroi, not custom rules."""
    return any(
        name.module == package or name.module.startswith(f"{package}.")
        for package in BUILTIN_PACKAGES
    )


@dataclass
class RuleLoader:
    """
    Loads the rules that configs name, and warns with ``warnings``. It keeps
    the top-level packages that it imported through ``enable-root-import``,
    with the path that they were imported from (``root_imported``).

    Python imports a module once in a process (``sys.modules``), and the
    packages it keeps are among them: a process uses one loader,
    :data:`LOADER`. Another one is for a ``sys.modules`` without the packages
    that the first one imported, as in the tests.
    """

    warnings: OnceLog = field(default_factory=OnceLog)
    root_imported: dict[str, Path] = field(default_factory=dict)

    def collect(
        self,
        enable: Sequence[RuleName],
        disable: Sequence[RuleName],
        *,
        root_import: Path | None = None,
        custom_rules: bool = True,
    ) -> tuple[type[Rule], ...]:
        """
        The rules of ``enable`` without those of ``disable``, sorted by name.
        For a rule in both, the more specific name wins (#40, see
        :func:`_specificity`), and ``disable`` if they are as specific. A name
        whose rules cannot be loaded raises a :class:`CollectionError` (see
        :meth:`load`). ``root_import`` is the path that
        ``enable-root-import`` adds to ``sys.path``. With ``custom_rules``
        false, only the built-in rules are imported: the others in ``enable``
        are skipped with a warning, those in ``disable`` and ``root_import``
        silently.
        """
        if not custom_rules:
            root_import = None
        # Each rule, with the most specific of the names that give it.
        enabled: dict[type[Rule], int] = {}
        disabled: dict[type[Rule], int] = {}
        with _on_path(root_import):
            for name in enable:
                if not (custom_rules or is_builtin(name)):
                    message = f"Skipped rules '{name}': custom rules are turned off"
                    self.warnings.warn(message)
                    continue
                for rule in self._load(name, root_import):
                    enabled[rule] = max(enabled.get(rule, -1), _specificity(name))
            for name in disable:
                if custom_rules or is_builtin(name):
                    for rule in self._load(name, root_import):
                        specificity = _specificity(name)
                        disabled[rule] = max(disabled.get(rule, -1), specificity)
        rules = (rule for rule, n in enabled.items() if n > disabled.get(rule, -1))
        return tuple(sorted(rules, key=lambda r: (r.name(), r.__module__)))

    def load(
        self, name: RuleName, root_import: Path | None = None
    ) -> tuple[type[Rule], ...]:
        """
        The rules of ``name``, with ``root_import`` on ``sys.path``, as
        :meth:`collect` loads them. Raises a :class:`CollectionError`.
        """
        with _on_path(root_import):
            return self._load(name, root_import)

    def _load(self, name: RuleName, root_import: Path | None) -> tuple[type[Rule], ...]:
        """
        The rules of ``name``. Raises a :class:`CollectionError` for each reason
        that they cannot be loaded, with the exception of the code of the
        module in the message; ``--debug`` logs its traceback.
        """
        top = name.module.partition(".")[0]
        imported = self.root_imported.get(top)
        if not name.local and imported is not None and imported != root_import:
            message = (
                f"could not import rule(s) {name}: imported from another root, "
                f"{imported}"
            )
            raise CollectionError(message)
        try:
            rules = import_rules(name)
        except CollectionError as e:
            if root_import is None and _not_found(name, e.__cause__):
                raise CollectionError(f"{e} ({ROOT_IMPORT_HINT})") from e.__cause__
            raise
        except ModuleError as e:
            cause = e.__cause__
            log.debug("Exception while importing %s", name, exc_info=cause)
            message = _could_not_import(name, cause or e, e.module)
            raise CollectionError(message) from cause
        # Importing a rule runs its code, which can raise any exception.
        except Exception as e:
            log.debug("Exception while importing %s", name, exc_info=e)
            raise CollectionError(_could_not_import(name, e)) from e
        where = f" from {name.root}" if name.local else ""
        if not rules:
            raise CollectionError(f"no rules in {name}{where}")
        if root_import is not None and not name.local and _is_under(top, root_import):
            self.root_imported.setdefault(top, root_import)
        return rules


def _specificity(name: RuleName) -> int:
    """
    How specific ``name`` is (#40): a module by its depth, and one rule more
    than any module. ``tukuroi.rules`` is less specific than
    ``tukuroi.rules.no_static_if_condition``, which is less specific than
    ``tukuroi.rules:NoStaticIfCondition``.
    """
    if name.name is not None:
        return sys.maxsize
    return name.module.count(".")


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


# The warnings of this process, and its loader, which warns with them.
WARNINGS = OnceLog()
LOADER = RuleLoader(WARNINGS)
