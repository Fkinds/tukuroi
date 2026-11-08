==========
Why Fixit?
==========

**There are many Python linter tools. Why do we need another?**

Linters are built to help developers write better code and many good linters have been built.
In a large codebase, tons of lint suggestions can slow developers down.
Developers may spend too much time on fixing code quality suggestions instead of
focusing on important progress.
At some point, they may start to ignore lint suggestions, even the important ones.

We'd like to help developers move faster by **auto-fixing** lint violations.
The `AST <https://docs.python.org/3/library/ast.html>`_ doesn't preserve formatting
information (comments, whitespaces, etc), so Fixit never turns a tree back into
code. Rules find problematic code in the AST, and fix it by replacing ranges of
the original text: everything outside those ranges is left as it was, and a fix
that would drop a comment is not applied. Fixit then formats the fixed files
with `ruff <https://docs.astral.sh/ruff/>`_, and leaves to ruff the many rules
that it already has.

Learning from building a Flake8 plugin
======================================

Many of our old lint rules are implemented in a monolithic single-file
`Flake8 plugin <https://flake8.pycqa.org/en/latest/plugin-development/index.html>`_.
This offered a lot of flexibility and helped facilitate a shared structure for the
rules, but it led to severe performance and reliability problems:

- Rules were highly coupled, with a significant amount of shared state and helper functions.
  It was common to make a small change to one lint rule which broke the others.
  Because of poor testing practices, these breakages could be missed.
- It wasn't possible to run rules in isolation, making benchmarking and testing more difficult.
  Disabling a rule in Flake8 consists of running the whole linter and
  filtering out the disabled results.
- Visitors were responsible for visiting their children.
  Forgetting to do this could break lint coverage inside of the given construct.
- To work around some of these issues, developers would often define their own node visitor.
  Traversing the AST multiple times slows down the linter.

The result was a large file with lots of visitors and helper functions which was hard to
develop upon.

Design Principles
=================
When designing Fixit, we used the following list of principles.

- **Autofix.** Lint rules should provide autofix whenever possible to help developers
  write better code faster. The autofix can run as a codemod on an existing codebase to
  avoid introducing lots of lint violations when adding a new lint rule.
- **Modular.** A lint rule is a standalone class which keeps its own logic and states
  from other rules. That makes developing a lint rule simple and less likely to break
  others.
- **Fast.** All lint rules are applied during a single traversal of the syntax tree and
  reuse shared metadata to provide lint suggestions fast.
- **Configurable.** Each lint rule is configurable in the config file. That makes lint
  rules highly customizable. When a lint rule is disabled, it doesn't run at all.
- **Testable.** Testing a lint rule is as simple as providing code examples. These
  are also used as documentation to help developers understand the line rule.
