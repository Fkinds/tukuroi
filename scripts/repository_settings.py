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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

SETTINGS = Path(__file__).parent.parent / ".github" / "repository.yml"

# The statuses of the settings that GitHub shows for public repositories only.
PUBLIC_ONLY = {404: "public repositories only", 422: "public repositories only"}


class Unavailable(Exception):
    """A setting that GitHub does not show for the repository."""


class GhError(Exception):
    """A call of `gh api` that failed: its HTTP status, if any, and its output."""

    def __init__(self, status: int | None, output: str) -> None:
        super().__init__(output)
        self.status = status


def gh(method: str, path: str, body: object = None) -> Any:
    """The JSON that `gh api` returns for ``method`` on ``path``, or None."""
    command = ["gh", "api", "--method", method, path]
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


def read(path: str, unavailable: Mapping[int, str]) -> Any:
    """GET ``path``: a status in ``unavailable`` is a setting GitHub does not show."""
    try:
        return gh("GET", path)
    except GhError as e:
        if e.status is not None and e.status in unavailable:
            raise Unavailable(unavailable[e.status]) from e
        raise


def sender(method: str, path: str, wrap: str | None) -> Callable[[Any], None]:
    """A setter that sends what is wanted to ``path``, under the key ``wrap``."""

    def send(want: Any) -> None:
        gh(method, path, want if wrap is None else {wrap: want})

    return send


def switch(path: str) -> Callable[[Any], None]:
    """A setter of a feature that PUT turns on and DELETE turns off."""

    def send(want: Any) -> None:
        gh("PUT" if want else "DELETE", path)

    return send


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
        same = sorted(map(str, want)) == sorted(map(str, have))
    elif want == "":
        same = have in ("", None)
    else:
        same = want == have
    return [] if same else [f"{at}: {have!r} -> {want!r}"]


@dataclass(frozen=True)
class Setting:
    """A setting: what is wanted, and how to read, compare and set it."""

    name: str
    want: Any
    get: Callable[[], Any]
    set: Callable[[Any], None]
    compare: Callable[[Any, Any, str], list[str]]

    def check(self) -> list[str]:
        return self.compare(self.want, self.get(), self.name)


def label_changes(want: Any, have: Any, at: str) -> list[str]:
    """The labels to delete, to create and to change: they are exactly ``want``."""
    found = [f"{at}: delete {name!r}" for name in have if name not in want]
    for name, label in want.items():
        if name not in have:
            found.append(f"{at}: create {name!r}")
        else:
            found += differences(label, have[name], f"{at}[{name!r}]")
    return found


def labels(repo: str, listed: list[Mapping[str, str]]) -> Setting:
    want = {
        label["name"]: {
            "color": str(label["color"]).lower(),
            "description": label["description"],
        }
        for label in listed
    }

    def get() -> Any:
        return {
            label["name"]: {
                "color": label["color"].lower(),
                "description": label["description"] or "",
            }
            for label in read(f"repos/{repo}/labels?per_page=100", {})
        }

    def put(want: Any) -> None:
        have = get()
        for name in have:
            if name not in want:
                gh("DELETE", f"repos/{repo}/labels/{quote(name)}")
        for name, label in want.items():
            if name not in have:
                gh("POST", f"repos/{repo}/labels", {"name": name, **label})
            elif differences(label, have[name], name):
                gh("PATCH", f"repos/{repo}/labels/{quote(name)}", label)

    return Setting("labels", want, get, put, label_changes)


def settings(config: Mapping[str, Any]) -> list[Setting]:
    """The settings of ``config``, in the order to set them."""
    repo = config["name"]
    actions = config["actions"]
    base = f"repos/{repo}/actions/permissions"

    def security() -> Any:
        have = read(f"repos/{repo}", {}).get("security_and_analysis")
        if have is None:
            raise Unavailable("public repositories only")
        return have

    def alerts() -> bool:
        # 204 when they are on, 404 when they are off.
        try:
            gh("GET", f"repos/{repo}/vulnerability-alerts")
        except GhError as e:
            if e.status == 404:
                return False
            raise
        return True

    def selected() -> Any:
        # 409 while every action is allowed: then none is selected.
        try:
            return gh("GET", f"{base}/selected-actions")
        except GhError as e:
            if e.status == 409:
                return None
            raise

    return [
        Setting(
            "repository",
            config["repository"],
            lambda: read(f"repos/{repo}", {}),
            sender("PATCH", f"repos/{repo}", None),
            differences,
        ),
        Setting(
            "security_and_analysis",
            config["security_and_analysis"],
            security,
            sender("PATCH", f"repos/{repo}", "security_and_analysis"),
            differences,
        ),
        Setting(
            "topics",
            config["topics"],
            lambda: read(f"repos/{repo}/topics", {})["names"],
            sender("PUT", f"repos/{repo}/topics", "names"),
            differences,
        ),
        Setting(
            "vulnerability_alerts",
            config["vulnerability_alerts"],
            alerts,
            switch(f"repos/{repo}/vulnerability-alerts"),
            differences,
        ),
        Setting(
            "automated_security_fixes",
            config["automated_security_fixes"],
            lambda: read(f"repos/{repo}/automated-security-fixes", {})["enabled"],
            switch(f"repos/{repo}/automated-security-fixes"),
            differences,
        ),
        Setting(
            "private_vulnerability_reporting",
            config["private_vulnerability_reporting"],
            lambda: read(f"repos/{repo}/private-vulnerability-reporting", PUBLIC_ONLY)[
                "enabled"
            ],
            switch(f"repos/{repo}/private-vulnerability-reporting"),
            differences,
        ),
        # Before the selected actions, which need allowed_actions "selected".
        Setting(
            "actions.permissions",
            actions["permissions"],
            lambda: read(base, {}),
            sender("PUT", base, None),
            differences,
        ),
        Setting(
            "actions.selected_actions",
            actions["selected_actions"],
            selected,
            sender("PUT", f"{base}/selected-actions", None),
            differences,
        ),
        Setting(
            "actions.workflow",
            actions["workflow"],
            lambda: read(f"{base}/workflow", {}),
            sender("PUT", f"{base}/workflow", None),
            differences,
        ),
        Setting(
            "actions.fork_pr_contributor_approval",
            actions["fork_pr_contributor_approval"],
            lambda: read(f"{base}/fork-pr-contributor-approval", PUBLIC_ONLY),
            sender("PUT", f"{base}/fork-pr-contributor-approval", None),
            differences,
        ),
        labels(repo, config["labels"]),
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
            setting.set(setting.want)
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
