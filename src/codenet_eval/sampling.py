"""Reproducibly sample a fraction of the eligible problems."""

from __future__ import annotations

import math
import random
from typing import Optional

from .utils import get_logger

log = get_logger(__name__)


def sample_count(population: int, percent: float, max_samples: Optional[int]) -> int:
    """Number of items to draw for ``percent`` of ``population``.

    Rounds to the nearest integer but guarantees at least one item whenever the
    population is non-empty and ``percent`` is positive, and honours
    ``max_samples`` as an upper bound.
    """
    if population <= 0 or percent <= 0:
        return 0
    n = int(round(population * percent / 100.0))
    n = max(1, n)
    n = min(n, population)
    if max_samples is not None:
        n = min(n, max_samples)
    return n


def select_problem_ids(
    eligible_ids: list[str],
    percent: float,
    seed: int,
    max_samples: Optional[int] = None,
) -> list[str]:
    """Deterministically pick ``percent`` % of ``eligible_ids``.

    Selection is a seeded shuffle so the same seed + population always yields the
    same sample, and the result is returned in sorted order for stable output.
    """
    unique_sorted = sorted(set(eligible_ids))
    n = sample_count(len(unique_sorted), percent, max_samples)
    rng = random.Random(seed)
    shuffled = unique_sorted[:]
    rng.shuffle(shuffled)
    chosen = shuffled[:n]
    log.info(
        "Sampled %d of %d eligible problems (%.3f%%, seed=%d)",
        len(chosen),
        len(unique_sorted),
        percent,
        seed,
    )
    return sorted(chosen)
