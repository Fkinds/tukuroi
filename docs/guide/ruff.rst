.. _ruff-rules:

Rules Replaced by ruff
----------------------

tukuroi keeps only the built-in rules that `ruff <https://docs.astral.sh/ruff/>`_
does not cover. The other built-in rules of Fixit 2 are removed: use the ruff
rules below instead.

The table was checked with ruff 0.17, against the ``VALID`` and ``INVALID``
cases of each Fixit rule. "Same" means that ruff reports every ``INVALID``
case; "close" means that it misses some, or fixes them another way.

.. list-table::
    :header-rows: 1
    :widths: 30 25 45

    * - Fixit rule
      - ruff rules
      - Differences
    * - ``AvoidOrInExcept``
      - ``PLW0711``, ``B030``
      - Same.
    * - ``CollapseIsinstanceChecks``
      - ``SIM101``
      - Same. ruff also merges a call into a tuple that is already there.
    * - ``ComparePrimitivesByEqual``
      - ``F632``
      - Close: ruff does not take an f-string for a literal (``a is f"1{b}"``).
    * - ``CompareSingletonPrimitivesByIs``
      - ``E711``, ``E712``
      - Close: ruff misses chained comparisons (``x is True == y``). ``E712``
        fixes ``x != True`` to ``not x``, a check of truth, not of identity.
    * - ``DeprecatedABCImport``
      - ``UP035``
      - Close: ruff misses ``import collections.Container`` and
        ``collections.Container`` as a base class. It also reports the
        fallback import in ``except ImportError``.
    * - ``DeprecatedUnittestAsserts``
      - ``UP005``
      - Same.
    * - ``NoInheritFromObject``
      - ``UP004``
      - Same.
    * - ``NoRedundantArgumentsSuper``
      - ``UP008``
      - Same.
    * - ``NoRedundantFString``
      - ``F541``
      - Same.
    * - ``NoRedundantLambda``
      - ``PLW0108``
      - Same.
    * - ``NoRedundantListComprehension``
      - ``C419``
      - Same.
    * - ``NoStringTypeAnnotation``
      - ``UP037``
      - Same. ruff also reports the annotations that are only read by type
        checkers.
    * - ``ReplaceUnionWithOptional``
      - None
      - ruff goes the other way: ``UP007`` and ``UP045`` rewrite ``Union[T,
        None]`` and ``Optional[T]`` to ``T | None``.
    * - ``RewriteToComprehension``
      - ``C400``, ``C401``, ``C402``, ``C403``, ``C404``
      - Close: ruff misses pairs given as lists (``dict([a, b] for ...)``).
    * - ``RewriteToLiteral``
      - ``C405``, ``C406``, ``C408``, ``C409``, ``C410``
      - Close: ruff misses ``dict()`` of a list of lists.
    * - ``UseAsyncSleepInAsyncDef``
      - ``ASYNC251``
      - Same.
    * - ``UseClsInClassmethod``
      - ``N804``
      - Close: ruff misses a class method without arguments.
    * - ``UseFstring``
      - ``UP031``, ``UP032``
      - Close: ``UP032`` skips ``.format()`` with literal arguments. ``UP031``
        reports every ``%`` format, not only ``%s``.
    * - ``UseTypesFromTyping``
      - None
      - It applied only below Python 3.10. tukuroi supports newer versions.
    * - ``ExplicitFrozenDataclass`` (``fixit.rules.extra``)
      - None
      - ruff has no rule for it.
    * - ``UseLintFixmeComment`` (``fixit.rules.extra``)
      - ``PGH004``
      - Close: ``PGH004`` reports a ``# noqa`` without codes only.

Most of these ruff rules are on by default. Turn the others on in the ruff
configuration of the project:

.. code-block:: toml

    [tool.ruff.lint]
    extend-select = ["E711", "E712", "N804", "PGH004", "PLW0108"]
