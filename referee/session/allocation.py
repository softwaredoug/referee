"""Deterministic selection and partitioning of a session's queries."""

import hashlib
import json
import math
from collections.abc import Sequence

QueryIdentity = tuple[str, str | None]


def normalize_split_proportions(proportions: Sequence[float]) -> tuple[float, ...]:
    """Validate and normalize a non-empty list of proportions summing to one."""
    if not proportions:
        raise ValueError("splits must contain at least one proportion")

    normalized: list[float] = []
    for proportion in proportions:
        if type(proportion) not in (int, float):
            raise ValueError("each split proportion must be a positive finite number")
        value = float(proportion)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("each split proportion must be a positive finite number")
        normalized.append(value)

    total = math.fsum(normalized)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("split proportions must sum to 1")
    return tuple(proportion / total for proportion in normalized)


def split_sizes(query_count: int, proportions: Sequence[float]) -> tuple[int, ...]:
    """Convert proportions to deterministic integer sizes summing to query_count.

    Any remaining queries after taking the floor of each ideal size go to the
    largest fractional remainders; ties are resolved by split ordinal.
    """
    if (
        type(query_count) is not int
        or query_count < 0
    ):
        raise ValueError("query_count must be a non-negative integer")
    normalized = normalize_split_proportions(proportions)
    ideal_sizes = [query_count * proportion for proportion in normalized]
    sizes = [math.floor(size) for size in ideal_sizes]
    remaining = query_count - sum(sizes)
    remainder_order = sorted(
        range(len(normalized)),
        key=lambda ordinal: (-(ideal_sizes[ordinal] - sizes[ordinal]), ordinal),
    )
    for ordinal in remainder_order[:remaining]:
        sizes[ordinal] += 1
    return tuple(sizes)


def allocate_query_splits(
    query_ids: Sequence[QueryIdentity],
    *,
    num_queries: int | None,
    seed: int,
    sort_salt: str,
    proportions: Sequence[float],
) -> list[list[QueryIdentity]]:
    """Select a seeded query pool, salt-sort it, and return ordinal splits.

    Query identities use the source query ID and source dataset split. The
    seed makes pool selection repeatable; the per-session sort salt independently
    determines how that pool is divided.
    """
    normalized = normalize_split_proportions(proportions)
    if num_queries is not None and (
        type(num_queries) is not int
        or num_queries < 1
    ):
        raise ValueError("num_queries must be a positive integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if not sort_salt:
        raise ValueError("sort_salt must be a non-empty string")
    if len(set(query_ids)) != len(query_ids):
        raise ValueError("query_ids must be unique")
    if num_queries is not None and num_queries > len(query_ids):
        raise ValueError("num_queries cannot exceed the available query count")

    def identity_bytes(identity: QueryIdentity) -> bytes:
        return json.dumps(
            identity, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def sample_rank(identity: QueryIdentity) -> bytes:
        payload = json.dumps(
            (seed, identity), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).digest()

    pool = sorted(
        query_ids,
        key=lambda identity: (sample_rank(identity), identity_bytes(identity)),
    )
    if num_queries is not None:
        pool = pool[:num_queries]

    salt_bytes = sort_salt.encode("utf-8")

    def split_rank(identity: QueryIdentity) -> bytes:
        return hashlib.sha256(salt_bytes + b"\0" + identity_bytes(identity)).digest()

    ordered_pool = sorted(
        pool,
        key=lambda identity: (split_rank(identity), identity_bytes(identity)),
    )
    sizes = split_sizes(len(ordered_pool), normalized)

    splits: list[list[QueryIdentity]] = []
    start = 0
    for size in sizes:
        splits.append(ordered_pool[start:start + size])
        start += size
    return splits
