"""Classic BEIR-compatible ranking metrics used by evaluation tasks."""

from collections.abc import Mapping, Sequence
import math


def ndcg_at_10(
    ranked_doc_ids: Sequence[str], judgments: Mapping[str, int]
) -> float:
    """Calculate linear-gain NDCG@10 using relevance grades as gains."""
    ideal_grades = sorted(judgments.values(), reverse=True)[:10]
    ideal_dcg = sum(
        grade / math.log2(rank + 1)
        for rank, grade in enumerate(ideal_grades, start=1)
    )
    if ideal_dcg <= 0:
        raise ValueError("NDCG cannot be computed for a query with zero ideal DCG")

    actual_dcg = sum(
        judgments.get(doc_id, 0) / math.log2(rank + 1)
        for rank, doc_id in enumerate(ranked_doc_ids[:10], start=1)
    )
    return actual_dcg / ideal_dcg


def mrr_at_10(
    ranked_doc_ids: Sequence[str], judgments: Mapping[str, int]
) -> float:
    """Calculate MRR@10, treating any positive judgment grade as relevant."""
    for rank, doc_id in enumerate(ranked_doc_ids[:10], start=1):
        if judgments.get(doc_id, 0) > 0:
            return 1.0 / rank
    return 0.0
