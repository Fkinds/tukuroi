# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Characterization tests of scripts/repository_settings.py (#157): what it reads
and sends with `gh api`, what it prints, and how it exits. The calls go to a
fake gh, in place of subprocess.run, and the clock is a fake one too: the
tests go through main() only, so that the script can be built again.
"""

import io
import json
import subprocess
import sys
from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase
from unittest.mock import patch

import repository_settings
import yaml

REPO = "owner/repo"
BASE = f"repos/{REPO}/actions/permissions"

CONFIG: dict[str, Any] = {
    "name": REPO,
    "repository": {"has_wiki": False, "homepage": ""},
    "security_and_analysis": {"secret_scanning": {"status": "enabled"}},
    "topics": ["linter", "python"],
    "vulnerability_alerts": True,
    "automated_security_fixes": False,
    "private_vulnerability_reporting": True,
    "immutable_releases": True,
    "actions": {
        "permissions": {"enabled": True, "allowed_actions": "selected"},
        "selected_actions": {"patterns_allowed": ["owner/action@*"]},
        "workflow": {"default_workflow_permissions": "read"},
        "fork_pr_contributor_approval": {
            "approval_policy": "all_external_contributors"
        },
    },
    "code_scanning_default_setup": {"state": "configured", "languages": ["python"]},
    "pages": {"build_type": "workflow"},
    "environments": [
        {
            "name": "pypi",
            "wait_timer": 0,
            "prevent_self_review": False,
            "reviewers": [{"type": "User", "id": 1}],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
            "policies": [{"name": "v*", "type": "tag"}],
        }
    ],
    "rulesets": [
        {
            "name": "main",
            "enforcement": "active",
            "rules": [
                {"type": "deletion"},
                {
                    "type": "pull_request",
                    "parameters": {"required_approving_review_count": 0},
                },
            ],
        }
    ],
    "labels": [
        {"name": "bug", "color": "D73A4A", "description": "Something is wrong"},
        {"name": "good first issue", "color": "7057ff", "description": "For newcomers"},
    ],
}

# The names of the settings, in the order that the script checks them.
NAMES = [
    "repository",
    "security_and_analysis",
    "topics",
    "vulnerability_alerts",
    "automated_security_fixes",
    "private_vulnerability_reporting",
    "immutable_releases",
    "actions.permissions",
    "actions.selected_actions",
    "actions.workflow",
    "actions.fork_pr_contributor_approval",
    "code_scanning_default_setup",
    "pages",
    "environments",
    "rulesets",
    "labels",
]
ALL_OK = [f"{name}: ok" for name in NAMES]


@dataclass(frozen=True)
class Reply:
    """What gh prints, and its exit status."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def ok(value: object = None) -> Reply:
    """A success, with ``value`` as JSON: none for 204 No Content."""
    return Reply("" if value is None else json.dumps(value))


def failed(status: int, message: str = "Not Found") -> Reply:
    """An error of the API, as gh prints it: the status in the JSON and in stderr."""
    body = json.dumps({"message": message, "status": str(status)})
    return Reply(body, f"gh: {message} (HTTP {status})", 1)


Replies = Mapping[tuple[str, str], Reply | list[Reply]]

# GET /repos/{name}, as CONFIG has it.
REPOSITORY = {
    "full_name": REPO,
    "has_wiki": False,
    # An empty string of the config is no value.
    "homepage": None,
    "security_and_analysis": {
        "secret_scanning": {"status": "enabled"},
        "dependabot_security_updates": {"status": "disabled"},
    },
}


# An environment, as GitHub lists it: the rules, and the policies apart.
PYPI = {
    "id": 5,
    "name": "pypi",
    "protection_rules": [
        {
            "id": 1,
            "type": "required_reviewers",
            "prevent_self_review": False,
            "reviewers": [
                {"type": "User", "reviewer": {"id": 1, "login": "maintainer"}}
            ],
        },
        {"id": 2, "type": "branch_policy"},
    ],
    "deployment_branch_policy": {
        "protected_branches": False,
        "custom_branch_policies": True,
    },
}
POLICIES = f"repos/{REPO}/environments/pypi/deployment-branch-policies"


def policies(*found: tuple[int, str, str]) -> Reply:
    """The deployment branch policies of an environment: id, name and type."""
    listed = [{"id": i, "node_id": f"N{i}", "name": n, "type": t} for i, n, t in found]
    return ok({"total_count": len(listed), "branch_policies": listed})


# GET /repos/{name}/pages, as CONFIG has it.
SITE = ok(
    {
        "build_type": "workflow",
        "https_enforced": True,
        "html_url": "https://owner.github.io/repo/",
    }
)


def github() -> dict[tuple[str, str], Reply | list[Reply]]:
    """The replies of a repository whose settings are as CONFIG has them."""
    return {
        ("GET", f"repos/{REPO}"): ok(REPOSITORY),
        # A list is a set.
        ("GET", f"repos/{REPO}/topics"): ok({"names": ["python", "linter"]}),
        # 204 when they are on.
        ("GET", f"repos/{REPO}/vulnerability-alerts"): ok(),
        ("GET", f"repos/{REPO}/automated-security-fixes"): ok(
            {"enabled": False, "paused": False}
        ),
        ("GET", f"repos/{REPO}/private-vulnerability-reporting"): ok({"enabled": True}),
        ("GET", f"repos/{REPO}/immutable-releases"): ok(
            {"enabled": True, "enforced_by_owner": False}
        ),
        ("GET", BASE): ok(
            {"enabled": True, "allowed_actions": "selected", "sha_pinning_required": True}
        ),
        ("GET", f"{BASE}/selected-actions"): ok(
            {"github_owned_allowed": True, "patterns_allowed": ["owner/action@*"]}
        ),
        ("GET", f"{BASE}/workflow"): ok(
            {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}
        ),
        ("GET", f"{BASE}/fork-pr-contributor-approval"): ok(
            {"approval_policy": "all_external_contributors"}
        ),
        ("GET", f"repos/{REPO}/code-scanning/default-setup"): ok(
            {"state": "configured", "languages": ["python"], "schedule": "weekly"}
        ),
        ("GET", f"repos/{REPO}/pages"): SITE,
        ("GET", f"repos/{REPO}/environments"): ok({"total_count": 1, "environments": [PYPI]}),
        ("GET", POLICIES): policies((3, "v*", "tag")),
        ("GET", f"repos/{REPO}/rulesets?includes_parents=false"): ok(
            [{"name": "main", "id": 7}]
        ),
        # GitHub adds parameters of its own: only those of the config count.
        ("GET", f"repos/{REPO}/rulesets/7"): ok(
            {
                "id": 7,
                "name": "main",
                "enforcement": "active",
                "rules": [
                    {"type": "deletion"},
                    {
                        "type": "pull_request",
                        "parameters": {
                            "required_approving_review_count": 0,
                            "dismiss_stale_reviews_on_push": False,
                        },
                    },
                ],
            }
        ),
        # The color in any case, and no description as an empty one.
        ("GET", f"repos/{REPO}/labels?per_page=100"): ok(
            [
                {"name": "bug", "color": "d73a4a", "description": "Something is wrong"},
                {"name": "good first issue", "color": "7057FF", "description": "For newcomers"},
            ]
        ),
    }  # fmt: skip


@dataclass
class FakeGh:
    """
    `gh api`, in place of subprocess.run: the reply of each method and path,
    and the calls, with their bodies. A list of replies gives one a call, and
    its last one after them. A call without a reply fails the test.
    """

    replies: Replies
    calls: list[tuple[str, str, object]] = field(default_factory=list)
    _used: dict[tuple[str, str], int] = field(default_factory=dict)

    def __call__(
        self, command: list[str], **options: Any
    ) -> subprocess.CompletedProcess[str]:
        expected = {"capture_output": True, "text": True, "check": False}
        if (
            command[:3] != ["gh", "api", "--method"]
            or {key: options[key] for key in expected} != expected
        ):
            raise AssertionError(f"not a call of gh api: {command} {options}")
        method, path, rest = command[3], command[4], command[5:]
        if rest == ["--input", "-"]:
            body = json.loads(options["input"])
        elif not rest and options["input"] is None:
            body = None
        else:
            raise AssertionError(f"unexpected arguments: {command} {options}")
        self.calls.append((method, path, body))
        key = (method, path)
        if key not in self.replies:
            raise AssertionError(f"no reply for {method} {path}")
        reply = self.replies[key]
        if isinstance(reply, list):
            index = self._used.get(key, 0)
            self._used[key] = index + 1
            reply = reply[min(index, len(reply) - 1)]
        return subprocess.CompletedProcess(
            command, reply.returncode, reply.stdout, reply.stderr
        )

    def writes(self) -> list[tuple[str, str, object]]:
        return [call for call in self.calls if call[0] != "GET"]


@dataclass
class Clock:
    """time.monotonic and time.sleep: sleeping moves the clock on."""

    now: float = 1000.0
    slept: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@dataclass
class Run:
    code: int
    lines: list[str]
    gh: FakeGh
    clock: Clock


def run(args: list[str], replies: Replies, config: Mapping[str, Any] = CONFIG) -> Run:
    """main() with ``args``, the config, and gh replying with ``replies``."""
    gh = FakeGh(replies)
    clock = Clock()
    out = io.StringIO()
    with TemporaryDirectory() as directory:
        settings = Path(directory) / "repository.yml"
        settings.write_text(yaml.safe_dump(dict(config), sort_keys=False))
        with (
            patch.object(repository_settings, "SETTINGS", settings),
            patch.object(sys, "argv", ["repository_settings.py", *args]),
            patch("subprocess.run", gh),
            patch("time.monotonic", clock.monotonic),
            patch("time.sleep", clock.sleep),
            redirect_stdout(out),
        ):
            code = repository_settings.main()
    return Run(code, out.getvalue().splitlines(), gh, clock)


def replace(lines: list[str], name: str, *found: str) -> list[str]:
    """``lines``, with the line of ``name`` replaced by ``found``."""
    index = lines.index(f"{name}: ok")
    return [*lines[:index], *found, *lines[index + 1 :]]


class CheckTest(TestCase):
    def test_as_wanted(self) -> None:
        for args in ([], ["--check"]):
            with self.subTest(args=args):
                result = run(args, github())
                self.assertEqual(result.lines, ALL_OK)
                self.assertEqual(result.code, 0)
                self.assertEqual(result.gh.writes(), [])

    def test_reads(self) -> None:
        # Each setting is read once; the repository twice, for two settings.
        result = run([], github())
        paths = [path for _, path, _ in result.gh.calls]
        self.assertEqual(
            paths,
            [
                f"repos/{REPO}",
                f"repos/{REPO}",
                f"repos/{REPO}/topics",
                f"repos/{REPO}/vulnerability-alerts",
                f"repos/{REPO}/automated-security-fixes",
                f"repos/{REPO}/private-vulnerability-reporting",
                f"repos/{REPO}/immutable-releases",
                BASE,
                f"{BASE}/selected-actions",
                f"{BASE}/workflow",
                f"{BASE}/fork-pr-contributor-approval",
                f"repos/{REPO}/code-scanning/default-setup",
                f"repos/{REPO}/pages",
                f"repos/{REPO}/environments",
                POLICIES,
                f"repos/{REPO}/rulesets?includes_parents=false",
                f"repos/{REPO}/rulesets/7",
                f"repos/{REPO}/labels?per_page=100",
            ],
        )

    def test_differences(self) -> None:
        replies = github() | differing()
        result = run(["--check"], replies)
        self.assertEqual(result.lines, DIFFERENCES)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.gh.writes(), [])

    def test_not_shown_by_github(self) -> None:
        # Most security settings, while the repository is private: the others
        # are checked still.
        public = "not shown by GitHub (public repositories only)"
        repository = dict(REPOSITORY)
        del repository["security_and_analysis"]
        replies = github() | {
            ("GET", f"repos/{REPO}"): ok(repository),
            ("GET", f"repos/{REPO}/private-vulnerability-reporting"): failed(404),
            ("GET", f"{BASE}/fork-pr-contributor-approval"): failed(
                422, "Unprocessable"
            ),
            ("GET", f"repos/{REPO}/code-scanning/default-setup"): failed(404),
        }
        result = run([], replies)
        lines = ALL_OK
        for name in (
            "security_and_analysis",
            "private_vulnerability_reporting",
            "actions.fork_pr_contributor_approval",
            "code_scanning_default_setup",
        ):
            lines = replace(lines, name, f"{name}: {public}")
        self.assertEqual(result.lines, lines)
        self.assertEqual(result.code, 1)

    def test_status_of_an_error(self) -> None:
        # The status of a failed call: from its JSON, or else from the
        # "(HTTP 404)" of gh. The alerts are off on 404.
        off = ["vulnerability_alerts: False -> True"]
        path = f"repos/{REPO}/vulnerability-alerts"
        cases = (
            ("JSON", failed(404)),
            ("JSON without stderr", Reply(failed(404).stdout, "", 1)),
            ("stderr", Reply("not JSON", "gh: Not Found (HTTP 404)", 1)),
            ("a status in JSON that is not a number", Reply('{"status": "x"}', "(HTTP 404)", 1)),
            ("JSON that is not an object", Reply("[]", "(HTTP 404)", 1)),
        )  # fmt: skip
        for label, reply in cases:
            with self.subTest(label):
                result = run([], github() | {("GET", path): reply})
                expected = replace(ALL_OK, "vulnerability_alerts", *off)
                self.assertEqual(result.lines, expected)

    def test_other_errors_raise(self) -> None:
        # An error that does not say that the setting is off or not shown.
        cases = (
            # (label, path, reply, the message)
            ("no status", f"repos/{REPO}/vulnerability-alerts", Reply("boom", "", 1), "boom"),
            ("another status of the alerts", f"repos/{REPO}/vulnerability-alerts", failed(500, "Oops"), '{"message": "Oops", "status": "500"}gh: Oops (HTTP 500)'),
            ("another status of the selected actions", f"{BASE}/selected-actions", failed(403, "No"), '{"message": "No", "status": "403"}gh: No (HTTP 403)'),
            ("a status not in unavailable", f"repos/{REPO}/topics", failed(404), '{"message": "Not Found", "status": "404"}gh: Not Found (HTTP 404)'),
            ("no status of a public-only setting", f"repos/{REPO}/code-scanning/default-setup", Reply("", "boom", 1), "boom"),
            ("another status of pages", f"repos/{REPO}/pages", failed(500, "Oops"), '{"message": "Oops", "status": "500"}gh: Oops (HTTP 500)'),
        )  # fmt: skip
        for label, path, reply, message in cases:
            with self.subTest(label):
                with self.assertRaises(repository_settings.GhError) as caught:
                    run([], github() | {("GET", path): reply})
                self.assertEqual(str(caught.exception), message)

    def test_selected_actions_while_all_are_allowed(self) -> None:
        # 409 while every action is allowed: none is selected.
        replies = github() | {("GET", f"{BASE}/selected-actions"): failed(409)}
        result = run([], replies)
        selected = CONFIG["actions"]["selected_actions"]
        expected = replace(
            ALL_OK,
            "actions.selected_actions",
            f"actions.selected_actions: None -> {selected!r}",
        )
        self.assertEqual(result.lines, expected)

    def test_check_and_apply(self) -> None:
        # One or the other: a usage error of argparse.
        with (
            self.assertRaises(SystemExit) as caught,
            redirect_stderr(io.StringIO()) as err,
        ):
            run(["--check", "--apply"], github())
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("not allowed with argument", err.getvalue())


def differing() -> dict[tuple[str, str], Reply | list[Reply]]:
    """Replies of a repository whose settings each differ from CONFIG."""
    return {
        ("GET", f"repos/{REPO}"): ok(
            {
                "has_wiki": True,
                "homepage": "https://example.com",
                "security_and_analysis": {"secret_scanning": {"status": "disabled"}},
            }
        ),
        ("GET", f"repos/{REPO}/topics"): ok({"names": ["linter"]}),
        # 404 when they are off.
        ("GET", f"repos/{REPO}/vulnerability-alerts"): failed(404),
        ("GET", f"repos/{REPO}/automated-security-fixes"): ok({"enabled": True}),
        ("GET", f"repos/{REPO}/private-vulnerability-reporting"): ok(
            {"enabled": False}
        ),
        ("GET", f"repos/{REPO}/immutable-releases"): ok({"enabled": False}),
        ("GET", BASE): ok({"enabled": True, "allowed_actions": "all"}),
        ("GET", f"{BASE}/selected-actions"): ok({"patterns_allowed": []}),
        ("GET", f"{BASE}/workflow"): ok({"default_workflow_permissions": "write"}),
        ("GET", f"{BASE}/fork-pr-contributor-approval"): ok(
            {"approval_policy": "first_time_contributors"}
        ),
        ("GET", f"repos/{REPO}/code-scanning/default-setup"): ok(
            {"state": "not-configured", "languages": []}
        ),
        # 404 while the repository has no site.
        ("GET", f"repos/{REPO}/pages"): failed(404),
        # An environment to delete, and one with a wait in place of the
        # reviewer, and a branch that may deploy too.
        ("GET", f"repos/{REPO}/environments"): ok(
            {
                "total_count": 2,
                "environments": [
                    {
                        "name": "old",
                        "protection_rules": [],
                        "deployment_branch_policy": None,
                    },
                    {
                        **PYPI,
                        "protection_rules": [
                            {"id": 6, "type": "wait_timer", "wait_timer": 5}
                        ],
                    },
                ],
            }
        ),
        ("GET", POLICIES): policies((3, "v*", "tag"), (4, "main", "branch")),
        ("GET", f"repos/{REPO}/rulesets?includes_parents=false"): ok(
            [{"name": "main", "id": 7}, {"name": "old", "id": 9}]
        ),
        ("GET", f"repos/{REPO}/rulesets/7"): ok(
            {
                "name": "main",
                "enforcement": "disabled",
                "rules": [
                    {"type": "non_fast_forward"},
                    {
                        "type": "pull_request",
                        "parameters": {"required_approving_review_count": 1},
                    },
                ],
            }
        ),
        ("GET", f"repos/{REPO}/rulesets/9"): ok({"name": "old", "rules": []}),
        ("GET", f"repos/{REPO}/labels?per_page=100"): ok(
            [
                {"name": "bug", "color": "ffffff", "description": None},
                {"name": "wont fix", "color": "000000", "description": ""},
            ]
        ),
    }


DIFFERENCES = [
    "repository.has_wiki: True -> False",
    "repository.homepage: 'https://example.com' -> ''",
    "security_and_analysis.secret_scanning.status: 'disabled' -> 'enabled'",
    "topics: ['linter'] -> ['linter', 'python']",
    "vulnerability_alerts: False -> True",
    "automated_security_fixes: True -> False",
    "private_vulnerability_reporting: False -> True",
    "immutable_releases: False -> True",
    "actions.permissions.allowed_actions: 'all' -> 'selected'",
    "actions.selected_actions.patterns_allowed: [] -> ['owner/action@*']",
    "actions.workflow.default_workflow_permissions: 'write' -> 'read'",
    "actions.fork_pr_contributor_approval.approval_policy: 'first_time_contributors' -> 'all_external_contributors'",
    "code_scanning_default_setup.state: 'not-configured' -> 'configured'",
    "code_scanning_default_setup.languages: [] -> ['python']",
    "pages: None -> {'build_type': 'workflow'}",
    "environments: delete 'old'",
    "environments['pypi'].wait_timer: 5 -> 0",
    "environments['pypi'].reviewers: [] -> [{'type': 'User', 'id': 1}]",
    "environments['pypi'].policies: [{'name': 'v*', 'type': 'tag'}, {'name': 'main', 'type': 'branch'}] -> [{'name': 'v*', 'type': 'tag'}]",
    "rulesets: delete 'old'",
    "rulesets['main'].enforcement: 'disabled' -> 'active'",
    "rulesets['main'].rules: delete 'non_fast_forward'",
    "rulesets['main'].rules: create 'deletion'",
    "rulesets['main'].rules['pull_request'].required_approving_review_count: 1 -> 0",
    "labels: delete 'wont fix'",
    "labels['bug'].color: 'ffffff' -> 'd73a4a'",
    "labels['bug'].description: '' -> 'Something is wrong'",
    "labels: create 'good first issue'",
]  # fmt: skip


class ApplyTest(TestCase):
    def test_as_wanted(self) -> None:
        # Nothing is sent: the settings are checked twice.
        result = run(["--apply"], github())
        self.assertEqual(result.lines, [*ALL_OK, "", "After --apply:", *ALL_OK])
        self.assertEqual(result.gh.writes(), [])
        self.assertEqual(result.code, 0)

    def test_sets_what_differs(self) -> None:
        # Each setting that differs is sent, in the order of the settings;
        # GitHub still differs after it here, as no reply changes.
        writes = {
            ("PATCH", f"repos/{REPO}"): ok({}),
            ("PUT", f"repos/{REPO}/topics"): ok({"names": []}),
            ("PUT", f"repos/{REPO}/vulnerability-alerts"): ok(),
            ("DELETE", f"repos/{REPO}/automated-security-fixes"): ok(),
            ("PUT", f"repos/{REPO}/private-vulnerability-reporting"): ok(),
            ("PUT", f"repos/{REPO}/immutable-releases"): ok(),
            ("PUT", BASE): ok(),
            ("PUT", f"{BASE}/selected-actions"): ok(),
            ("PUT", f"{BASE}/workflow"): ok(),
            ("PUT", f"{BASE}/fork-pr-contributor-approval"): ok(),
            ("PATCH", f"repos/{REPO}/code-scanning/default-setup"): ok({}),
            ("POST", f"repos/{REPO}/pages"): ok({}),
            ("DELETE", f"repos/{REPO}/environments/old"): ok(),
            ("PUT", f"repos/{REPO}/environments/pypi"): ok({}),
            ("DELETE", f"{POLICIES}/4"): ok(),
            ("DELETE", f"repos/{REPO}/rulesets/9"): ok(),
            ("PUT", f"repos/{REPO}/rulesets/7"): ok({}),
            ("DELETE", f"repos/{REPO}/labels/wont%20fix"): ok(),
            ("POST", f"repos/{REPO}/labels"): ok({}),
            ("PATCH", f"repos/{REPO}/labels/bug"): ok({}),
        }
        result = run(["--apply"], github() | differing() | writes)
        actions = CONFIG["actions"]
        main = CONFIG["rulesets"][0]
        self.assertEqual(
            result.gh.writes(),
            [
                ("PATCH", f"repos/{REPO}", CONFIG["repository"]),
                ("PATCH", f"repos/{REPO}", {"security_and_analysis": CONFIG["security_and_analysis"]}),
                ("PUT", f"repos/{REPO}/topics", {"names": CONFIG["topics"]}),
                ("PUT", f"repos/{REPO}/vulnerability-alerts", None),
                ("DELETE", f"repos/{REPO}/automated-security-fixes", None),
                ("PUT", f"repos/{REPO}/private-vulnerability-reporting", None),
                ("PUT", f"repos/{REPO}/immutable-releases", None),
                ("PUT", BASE, actions["permissions"]),
                ("PUT", f"{BASE}/selected-actions", actions["selected_actions"]),
                ("PUT", f"{BASE}/workflow", actions["workflow"]),
                ("PUT", f"{BASE}/fork-pr-contributor-approval", actions["fork_pr_contributor_approval"]),
                ("PATCH", f"repos/{REPO}/code-scanning/default-setup", CONFIG["code_scanning_default_setup"]),
                ("POST", f"repos/{REPO}/pages", CONFIG["pages"]),
                ("DELETE", f"repos/{REPO}/environments/old", None),
                ("PUT", f"repos/{REPO}/environments/pypi", PYPI_BODY),
                # The branch goes; the tag stays, and is not sent again.
                ("DELETE", f"{POLICIES}/4", None),
                ("DELETE", f"repos/{REPO}/rulesets/9", None),
                ("PUT", f"repos/{REPO}/rulesets/7", main),
                ("DELETE", f"repos/{REPO}/labels/wont%20fix", None),
                ("PATCH", f"repos/{REPO}/labels/bug", {"color": "d73a4a", "description": "Something is wrong"}),
                ("POST", f"repos/{REPO}/labels", {"name": "good first issue", "color": "7057ff", "description": "For newcomers"}),
            ],
        )  # fmt: skip
        set_lines = []
        for name in NAMES:
            set_lines += [line for line in DIFFERENCES if line.startswith(name)]
            set_lines.append(f"{name}: set")
        self.assertEqual(result.lines, [*set_lines, "", "After --apply:", *DIFFERENCES])
        self.assertEqual(result.code, 1)

    def test_creates(self) -> None:
        # A ruleset and a label that GitHub does not have: created.
        replies = github() | {
            ("GET", f"repos/{REPO}/rulesets?includes_parents=false"): [
                ok([]),
                ok([]),
                ok([{"name": "main", "id": 7}]),
            ],
            ("POST", f"repos/{REPO}/rulesets"): ok({}),
            ("GET", f"repos/{REPO}/labels?per_page=100"): [
                ok([]),
                ok([]),
                json_of_labels(),
            ],
            ("POST", f"repos/{REPO}/labels"): ok({}),
        }
        result = run(["--apply"], replies)
        self.assertEqual(
            result.gh.writes(),
            [
                ("POST", f"repos/{REPO}/rulesets", CONFIG["rulesets"][0]),
                ("POST", f"repos/{REPO}/labels", {"name": "bug", "color": "d73a4a", "description": "Something is wrong"}),
                ("POST", f"repos/{REPO}/labels", {"name": "good first issue", "color": "7057ff", "description": "For newcomers"}),
            ],
        )  # fmt: skip
        self.assertEqual(
            result.lines,
            [
                *ALL_OK[:-2],
                "rulesets: create 'main'",
                "rulesets: set",
                "labels: create 'bug'",
                "labels: create 'good first issue'",
                "labels: set",
                "",
                "After --apply:",
                *ALL_OK,
            ],
        )
        self.assertEqual(result.code, 0)

    def test_sends_only_the_labels_that_differ(self) -> None:
        path = f"repos/{REPO}/labels?per_page=100"
        labels = [
            {"name": "bug", "color": "d73a4a", "description": "Something is wrong"},
            {"name": "good first issue", "color": "000000", "description": "For newcomers"},
        ]  # fmt: skip
        replies = github() | {
            ("GET", path): ok(labels),
            ("PATCH", f"repos/{REPO}/labels/good%20first%20issue"): ok({}),
        }
        result = run(["--apply"], replies)
        body = {"color": "7057ff", "description": "For newcomers"}
        self.assertEqual(
            result.gh.writes(),
            [("PATCH", f"repos/{REPO}/labels/good%20first%20issue", body)],
        )

    def test_creates_the_site_and_an_environment(self) -> None:
        # Neither is there: the site is created with POST, the environment
        # with PUT, and then the tag that may deploy to it.
        replies = github() | {
            ("GET", f"repos/{REPO}/pages"): [failed(404), failed(404), SITE],
            ("POST", f"repos/{REPO}/pages"): ok({}),
            ("GET", f"repos/{REPO}/environments"): [
                ok({"total_count": 0, "environments": []}),
                ok({"total_count": 0, "environments": []}),
                ok({"total_count": 1, "environments": [PYPI]}),
            ],
            ("PUT", f"repos/{REPO}/environments/pypi"): ok({}),
            ("GET", POLICIES): [policies(), policies((3, "v*", "tag"))],
            ("POST", POLICIES): ok({}),
        }  # fmt: skip
        result = run(["--apply"], replies)
        self.assertEqual(
            result.gh.writes(),
            [
                ("POST", f"repos/{REPO}/pages", {"build_type": "workflow"}),
                ("PUT", f"repos/{REPO}/environments/pypi", PYPI_BODY),
                ("POST", POLICIES, {"name": "v*", "type": "tag"}),
            ],
        )
        self.assertEqual(result.code, 0)

    def test_updates_the_site(self) -> None:
        # A site that GitHub builds from a branch: PUT sets it to the workflow.
        path = f"repos/{REPO}/pages"
        legacy = ok(
            {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}}
        )
        replies = github() | {
            ("GET", path): [legacy, legacy, SITE],
            ("PUT", path): ok(),
        }
        result = run(["--apply"], replies)
        self.assertEqual(
            result.gh.writes(), [("PUT", path, {"build_type": "workflow"})]
        )
        self.assertIn("pages.build_type: 'legacy' -> 'workflow'", result.lines)
        self.assertEqual(result.code, 0)

    def test_environment_of_any_branch(self) -> None:
        # No deployment branch policy: no policies are read or sent.
        plain = {"name": "plain", "deployment_branch_policy": None}
        config = {**CONFIG, "environments": [plain]}
        listed = {
            "name": "plain",
            "protection_rules": [],
            "deployment_branch_policy": None,
        }
        replies = github() | {
            ("GET", f"repos/{REPO}/environments"): [
                ok({"total_count": 0, "environments": []}),
                ok({"total_count": 0, "environments": []}),
                ok({"total_count": 1, "environments": [listed]}),
            ],
            ("PUT", f"repos/{REPO}/environments/plain"): ok({}),
        }
        result = run(["--apply"], replies, config)
        body = {"deployment_branch_policy": None}
        self.assertEqual(
            result.gh.writes(), [("PUT", f"repos/{REPO}/environments/plain", body)]
        )
        self.assertEqual(result.code, 0)

    def test_waits_for_code_scanning(self) -> None:
        # GitHub sets up CodeQL in a run of its own: --apply reads the setting
        # every 5 seconds, until it is as wanted.
        path = f"repos/{REPO}/code-scanning/default-setup"
        before = ok({"state": "not-configured"})
        after = ok({"state": "configured", "languages": ["python"]})
        replies = github() | {
            ("GET", path): [before, before, before, after],
            ("PATCH", path): ok({}),
        }
        result = run(["--apply"], replies)
        self.assertEqual(result.clock.slept, [5, 5])
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines[-1], "labels: ok")

    def test_waits_for_code_scanning_up_to_3_minutes(self) -> None:
        path = f"repos/{REPO}/code-scanning/default-setup"
        replies = github() | {
            ("GET", path): ok({"state": "not-configured"}),
            ("PATCH", path): ok({}),
        }
        result = run(["--apply"], replies)
        self.assertEqual(result.clock.slept, [5] * 36)
        self.assertEqual(result.code, 1)

    def test_not_shown_is_not_set(self) -> None:
        public = "not shown by GitHub (public repositories only)"
        path = f"repos/{REPO}/private-vulnerability-reporting"
        result = run(["--apply"], github() | {("GET", path): failed(404)})
        line = f"private_vulnerability_reporting: {public}"
        lines = replace(ALL_OK, "private_vulnerability_reporting", line)
        self.assertEqual(result.lines, [*lines, "", "After --apply:", *lines])
        self.assertEqual(result.gh.writes(), [])
        self.assertEqual(result.code, 1)

    def test_turns_off(self) -> None:
        # A switch that is wanted off is sent with DELETE; one wanted on, PUT.
        config = {
            **CONFIG,
            "vulnerability_alerts": False,
            "automated_security_fixes": True,
        }
        replies = github() | {
            ("DELETE", f"repos/{REPO}/vulnerability-alerts"): ok(),
            ("PUT", f"repos/{REPO}/automated-security-fixes"): ok(),
        }
        result = run(["--apply"], replies, config)
        self.assertEqual(
            result.gh.writes(),
            [
                ("DELETE", f"repos/{REPO}/vulnerability-alerts", None),
                ("PUT", f"repos/{REPO}/automated-security-fixes", None),
            ],
        )


# What --apply sends for the environment of CONFIG: all but the policies.
PYPI_BODY = {
    k: v for k, v in CONFIG["environments"][0].items() if k not in ("name", "policies")
}


def json_of_labels() -> Reply:
    return ok(
        [
            {"name": label["name"], "color": label["color"].lower(), "description": label["description"]}
            for label in CONFIG["labels"]
        ]
    )  # fmt: skip
