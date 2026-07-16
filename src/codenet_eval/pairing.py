"""Turn a list of languages into the set of language pairs to compare.

Two strategies are supported:

* ``reference`` -- compare one reference language against every other language.
  This yields ``n - 1`` pairs, i.e. two requests for three languages, matching
  the framework's default behaviour.
* ``all`` -- compare every unordered pair, i.e. ``n * (n - 1) / 2`` pairs.
"""

from __future__ import annotations

import itertools

from .utils import get_logger

log = get_logger(__name__)


def language_pairs(
    languages: list[str],
    strategy: str = "reference",
    reference_language: str = "C",
) -> list[tuple[str, str]]:
    if len(languages) < 2:
        return []

    if strategy == "all":
        return [tuple(pair) for pair in itertools.combinations(languages, 2)]

    if strategy == "reference":
        ref = reference_language if reference_language in languages else languages[0]
        if ref != reference_language:
            log.warning(
                "reference_language '%s' not among %s; falling back to '%s'",
                reference_language,
                languages,
                ref,
            )
        return [(ref, other) for other in languages if other != ref]

    raise ValueError(f"Unknown pairing strategy: {strategy!r}")
