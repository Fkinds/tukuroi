# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The settings of the repository on GitHub, as .github/repository.yml has them.

    python scripts/repository_settings.py [--check]   # how GitHub differs
    python scripts/repository_settings.py --apply     # set what differs

It calls `gh api`, with the token that gh has. It exits with 1 when a setting
differs, or when GitHub does not show it: most security settings, while the
repository is private.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

SETTINGS = Path(__file__).parent.parent / ".github" / "repository.yml"

# The statuses of the settings that GitHub shows for public repositories only.
PUBLIC_ONLY = {404: "public repositories only", 422: "public repositories only"}

# How long --apply waits for GitHub to set up CodeQL, in seconds.
WAIT = 180


class Unavailable(Exception):
    """A setting that GitHub does not show for the repository."""


class GhError(Exception):
    """A call of `gh api` that failed: its HTTP status, if any, and its output."""

    def __init__(self, status: int | None, output: str) -> None:
        super().__init__(output)
        self.status = status


@dataclass(frozen=True)
class GitHub:
    """
    `gh api` on the repository ``repo``: a path is under ``repos/{repo}``, so
    that no other repository can be read or set.
    """

    repo: str

    def call(self, method: str, path: str = "", body: object = None) -> Any:
        """The JSON that `gh api` returns for ``method`` on ``path``, or None."""
        command = ["gh", "api", "--method", method, self._full(path)]
        if body is not None:
            command += ["--input", "-"]
        # The gh of the developer, from PATH, with arguments of its own.
        result = subprocess.run(  # noqa: S603
            command,
            input=None if body is None else json.dumps(body),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise GhError(status_of(result), (result.stdout + result.stderr).strip())
        return json.loads(result.stdout) if result.stdout.strip() else None

    def read(self, path: str, unavailable: Mapping[int, str]) -> Any:
        """GET ``path``: a status in ``unavailable`` is a setting GitHub does not show."""
        try:
            return self.call("GET", path)
        except GhError as e:
            if e.status is not None and e.status in unavailable:
                raise Unavailable(unavailable[e.status]) from e
            raise

    def _full(self, path: str) -> str:
        return f"repos/{self.repo}/{path}" if path else f"repos/{self.repo}"


def status_of(result: subprocess.CompletedProcess[str]) -> int | None:
    """
    The HTTP status of a failed call: from the JSON of the error, which has it
    for every status, or from the "(HTTP 404)" that gh adds for some.
    """
    try:
        error = json.loads(result.stdout)
    except json.JSONDecodeError:
        error = None
    if isinstance(error, dict) and str(error.get("status", "")).isdigit():
        return int(error["status"])
    match = re.search(r"\(HTTP (\d+)\)", result.stderr)
    return int(match.group(1)) if match else None


def differences(want: Any, have: Any, at: str) -> list[str]:
    """
    How ``have`` differs from ``want``: only the keys that ``want`` has count,
    a list is a set, and an empty string is no value.
    """
    if isinstance(want, dict):
        if not isinstance(have, dict):
            return [f"{at}: {have!r} -> {want!r}"]
        found: list[str] = []
        for key, value in want.items():
            found += differences(value, have.get(key), f"{at}.{key}")
        return found
    if isinstance(want, list) and isinstance(have, list):
        same = sorted(map(canonical, want)) == sorted(map(canonical, have))
    elif want == "":
        same = have in ("", None)
    else:
        same = want == have
    return [] if same else [f"{at}: {have!r} -> {want!r}"]


def canonical(value: Any) -> str:
    """``value`` as JSON, with its keys in order: equal for equal values."""
    return json.dumps(value, sort_keys=True)


def named_changes(
    want: Mapping[str, Any],
    have: Mapping[str, Any],
    at: str,
    compare: Callable[[Any, Any, str], list[str]] = differences,
) -> list[str]:
    """
    The things to delete, to create and to change, by name: they are exactly
    ``want``. ``compare`` compares the two of each name.
    """
    found = [f"{at}: delete {name!r}" for name in have if name not in want]
    for name, value in want.items():
        if name not in have:
            found.append(f"{at}: create {name!r}")
        else:
            found += compare(value, have[name], f"{at}[{name!r}]")
    return found


def rule_changes(want: Any, have: Any, at: str) -> list[str]:
    """
    How the rules of a ruleset differ, by type: only the parameters that
    ``want`` has count, as GitHub adds those of its own.
    """
    return named_changes(
        {rule["type"]: rule.get("parameters", {}) for rule in want},
        {rule["type"]: rule.get("parameters", {}) for rule in have},
        at,
    )


def ruleset_changes(want: Any, have: Any, at: str) -> list[str]:
    """How a ruleset differs: its rules by type, and the rest as it is."""
    rest = {key: value for key, value in want.items() if key != "rules"}
    return differences(rest, have, at) + rule_changes(
        want["rules"], have.get("rules", []), f"{at}.rules"
    )


@dataclass(frozen=True)
class Setting(ABC):
    """A setting of the repository: what is wanted, and how to read and set it."""

    github: GitHub
    name: str
    want: Any

    @abstractmethod
    def get(self) -> Any:
        """The setting as GitHub has it; :class:`Unavailable` if not shown."""

    @abstractmethod
    def apply(self) -> None:
        """Set what is wanted."""

    def changes(self, have: Any) -> list[str]:
        """How ``have`` differs from what is wanted."""
        return differences(self.want, have, self.name)

    def check(self) -> list[str]:
        """How GitHub differs from what is wanted."""
        return self.changes(self.get())


@dataclass(frozen=True)
class RestSetting(Setting):
    """
    A setting that GET reads at ``path``, and ``method`` sends there: under
    ``key`` of both, if any. A status in ``unavailable`` is not shown.
    """

    path: str = ""
    method: str = "PUT"
    key: str | None = None
    unavailable: Mapping[int, str] = field(default_factory=dict)

    def get(self) -> Any:
        have = self.github.read(self.path, self.unavailable)
        return have if self.key is None else have[self.key]

    def apply(self) -> None:
        body = self.want if self.key is None else {self.key: self.want}
        self.github.call(self.method, self.path, body)


@dataclass(frozen=True)
class SecurityAndAnalysis(RestSetting):
    """Under the key of the repository that GitHub has for public ones only."""

    def get(self) -> Any:
        have = self.github.read(self.path, self.unavailable).get(self.key)
        if have is None:
            raise Unavailable("public repositories only")
        return have


@dataclass(frozen=True)
class SelectedActions(RestSetting):
    """The actions that may run, as GitHub has them when it allows those only."""

    def get(self) -> Any:
        # 409 while every action is allowed: then none is selected.
        try:
            return self.github.call("GET", self.path)
        except GhError as e:
            if e.status == 409:
                return None
            raise


@dataclass(frozen=True)
class SwitchSetting(Setting):
    """
    A feature at ``path`` that PUT turns on and DELETE turns off: GET reads
    whether it is on under ``key``. A status in ``unavailable`` is not shown.
    """

    path: str = ""
    key: str = "enabled"
    unavailable: Mapping[int, str] = field(default_factory=dict)

    def get(self) -> Any:
        return self.github.read(self.path, self.unavailable)[self.key]

    def apply(self) -> None:
        self.github.call("PUT" if self.want else "DELETE", self.path)


@dataclass(frozen=True)
class VulnerabilityAlerts(SwitchSetting):
    """The Dependabot alerts: GET has no body."""

    def get(self) -> Any:
        # 204 when they are on, 404 when they are off.
        try:
            self.github.call("GET", self.path)
        except GhError as e:
            if e.status == 404:
                return False
            raise
        return True


@dataclass(frozen=True)
class Labels(Setting):
    """The labels, exactly, by name: --apply deletes the others."""

    @classmethod
    def of(cls, github: GitHub, listed: list[Mapping[str, str]]) -> Labels:
        want = {
            label["name"]: {
                "color": str(label["color"]).lower(),
                "description": label["description"],
            }
            for label in listed
        }
        return cls(github, "labels", want)

    def get(self) -> Any:
        return {
            label["name"]: {
                "color": label["color"].lower(),
                "description": label["description"] or "",
            }
            for label in self.github.read("labels?per_page=100", {})
        }

    def apply(self) -> None:
        have = self.get()
        for name in have:
            if name not in self.want:
                self.github.call("DELETE", f"labels/{quote(name)}")
        for name, label in self.want.items():
            if name not in have:
                self.github.call("POST", "labels", {"name": name, **label})
            elif differences(label, have[name], name):
                self.github.call("PATCH", f"labels/{quote(name)}", label)

    def changes(self, have: Any) -> list[str]:
        return named_changes(self.want, have, self.name)


@dataclass(frozen=True)
class Rulesets(Setting):
    """The rulesets, exactly, by name: --apply deletes the others."""

    @classmethod
    def of(cls, github: GitHub, listed: list[Mapping[str, Any]]) -> Rulesets:
        return cls(github, "rulesets", {ruleset["name"]: ruleset for ruleset in listed})

    def get(self) -> Any:
        return {
            name: self.github.read(f"rulesets/{number}", {})
            for name, number in self._ids().items()
        }

    def apply(self) -> None:
        have = self._ids()
        for name, number in have.items():
            if name not in self.want:
                self.github.call("DELETE", f"rulesets/{number}")
        for name, ruleset in self.want.items():
            if name not in have:
                self.github.call("POST", "rulesets", ruleset)
            else:
                self.github.call("PUT", f"rulesets/{have[name]}", ruleset)

    def changes(self, have: Any) -> list[str]:
        return named_changes(self.want, have, self.name, ruleset_changes)

    def _ids(self) -> dict[str, int]:
        return {
            ruleset["name"]: ruleset["id"]
            for ruleset in self.github.read("rulesets?includes_parents=false", {})
        }


@dataclass(frozen=True)
class CodeScanning(Setting):
    """
    The default setup of CodeQL. GitHub sets it in a run of its own: --apply
    waits for the setting, up to ``WAIT`` seconds.
    """

    path: str = "code-scanning/default-setup"

    def get(self) -> Any:
        return self.github.read(self.path, PUBLIC_ONLY)

    def apply(self) -> None:
        self.github.call("PATCH", self.path, self.want)
        deadline = time.monotonic() + WAIT
        while differences(self.want, self.get(), "") and time.monotonic() < deadline:
            time.sleep(5)


def settings(config: Mapping[str, Any]) -> list[Setting]:
    """The settings of ``config``, in the order to set them."""
    github = GitHub(config["name"])
    actions = config["actions"]
    base = "actions/permissions"
    return [
        RestSetting(github, "repository", config["repository"], method="PATCH"),
        SecurityAndAnalysis(
            github,
            "security_and_analysis",
            config["security_and_analysis"],
            method="PATCH",
            key="security_and_analysis",
        ),
        RestSetting(github, "topics", config["topics"], path="topics", key="names"),
        VulnerabilityAlerts(
            github,
            "vulnerability_alerts",
            config["vulnerability_alerts"],
            path="vulnerability-alerts",
        ),
        SwitchSetting(
            github,
            "automated_security_fixes",
            config["automated_security_fixes"],
            path="automated-security-fixes",
        ),
        SwitchSetting(
            github,
            "private_vulnerability_reporting",
            config["private_vulnerability_reporting"],
            path="private-vulnerability-reporting",
            unavailable=PUBLIC_ONLY,
        ),
        # Before the selected actions, which need allowed_actions "selected".
        RestSetting(github, "actions.permissions", actions["permissions"], path=base),
        SelectedActions(
            github,
            "actions.selected_actions",
            actions["selected_actions"],
            path=f"{base}/selected-actions",
        ),
        RestSetting(
            github, "actions.workflow", actions["workflow"], path=f"{base}/workflow"
        ),
        RestSetting(
            github,
            "actions.fork_pr_contributor_approval",
            actions["fork_pr_contributor_approval"],
            path=f"{base}/fork-pr-contributor-approval",
            unavailable=PUBLIC_ONLY,
        ),
        CodeScanning(
            github, "code_scanning_default_setup", config["code_scanning_default_setup"]
        ),
        # After CodeQL and the actions: the ruleset requires checks of CI.
        Rulesets.of(github, config["rulesets"]),
        Labels.of(github, config["labels"]),
    ]


def check(all_settings: list[Setting], *, apply: bool) -> bool:
    """
    Show how each setting differs, and set it when ``apply``. Whether every
    setting is as wanted: none differs, and GitHub shows each.
    """
    good = True
    for setting in all_settings:
        try:
            found = setting.check()
        except Unavailable as e:
            print(f"{setting.name}: not shown by GitHub ({e})")
            good = False
            continue
        if not found:
            print(f"{setting.name}: ok")
            continue
        for line in found:
            print(line)
        if apply:
            setting.apply()
            print(f"{setting.name}: set")
        else:
            good = False
    return good


def main() -> int:
    parser = argparse.ArgumentParser(
        description="The settings of the repository on GitHub, as "
        ".github/repository.yml has them."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="the default")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = yaml.safe_load(SETTINGS.read_text())
    all_settings = settings(config)
    if args.apply:
        check(all_settings, apply=True)
        print("\nAfter --apply:")
    return 0 if check(all_settings, apply=False) else 1


if __name__ == "__main__":
    sys.exit(main())
