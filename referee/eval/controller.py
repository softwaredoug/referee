"""Evaluation task creation, validation, and completion use cases."""

from collections.abc import Sequence
import math
import secrets

from referee.eval.db import EvalDB
from referee.eval.metrics import mrr_at_10, ndcg_at_10
from referee.eval.models import (
    CompleteTaskResult,
    CompleteTaskTask,
    CreateTaskResult,
    CreateTaskTask,
    EvalQuery,
    EvalSessionContext,
    QueryMetric,
    StoredQuery,
    SubmittedResult,
    TaskDescriptor,
)
from referee.session.allocation import allocate_query_splits

ALLOWED_EVAL_MODES = frozenset({"ndcg", "mrr"})


class EvalController:
    """Create tasks from session splits and evaluate their submitted results."""

    def __init__(self, eval_db: EvalDB) -> None:
        self._eval_db = eval_db

    def create_task(self, task: CreateTaskTask) -> CreateTaskResult:
        """Create a distinct task containing all queries in the token's split."""
        if not task.bearer_token:
            raise ValueError("bearer_token must not be empty")

        session = self._eval_db.get_session_context(task.bearer_token)
        if session.eval_mode not in ALLOWED_EVAL_MODES:
            raise ValueError(f"Unsupported session eval_mode: {session.eval_mode}")

        selected_queries = self._selected_queries(session)
        if not selected_queries:
            raise ValueError("The session split contains no queries")

        task_id = secrets.token_urlsafe(24)
        self._eval_db.create_task(task.bearer_token, task_id)
        return CreateTaskResult(
            dataset_name=session.dataset_name,
            task=TaskDescriptor(id=task_id, eval_mode=session.eval_mode),
            queries=[
                EvalQuery(
                    query_id=str(query.query_id),
                    query_text=query.query_text,
                    metadata=query.metadata,
                )
                for query in selected_queries
            ],
        )

    def complete_task(self, task: CompleteTaskTask) -> CompleteTaskResult:
        """Validate results, calculate the session metric, and complete once."""
        if not task.bearer_token:
            raise ValueError("bearer_token must not be empty")
        if not task.task_id:
            raise ValueError("task_id must not be empty")

        context = self._eval_db.get_task_context(task.task_id, task.bearer_token)
        if context.complete:
            raise ValueError("Task is already complete")

        session = context.session
        if session.eval_mode not in ALLOWED_EVAL_MODES:
            raise ValueError(f"Unsupported session eval_mode: {session.eval_mode}")
        selected_queries = self._selected_queries(session)
        if not selected_queries:
            raise ValueError("The session split contains no queries")

        grouped_results = self._validate_results(task.results, selected_queries)
        query_ids = [query.query_id for query in selected_queries]
        judgments = self._eval_db.get_judgments(query_ids)

        query_metrics: list[QueryMetric] = []
        for query in selected_queries:
            ranked_doc_ids = grouped_results[query.query_id]
            query_judgments = judgments[query.query_id]
            if session.eval_mode == "ndcg":
                score = ndcg_at_10(ranked_doc_ids, query_judgments)
            else:
                score = mrr_at_10(ranked_doc_ids, query_judgments)
            query_metrics.append(
                QueryMetric(
                    query_id=str(query.query_id),
                    query_text=query.query_text,
                    score=score,
                )
            )

        metric_score = sum(metric.score for metric in query_metrics) / len(
            query_metrics
        )
        self._eval_db.mark_task_complete(task.task_id, task.bearer_token)
        return CompleteTaskResult(
            task_id=task.task_id,
            metric_name=session.eval_mode,
            metric_score=metric_score,
            queries=query_metrics,
        )

    @staticmethod
    def _selected_queries(session: EvalSessionContext) -> list[StoredQuery]:
        query_by_identity = {query.identity: query for query in session.queries}
        query_splits = allocate_query_splits(
            [query.identity for query in session.queries],
            num_queries=session.num_queries,
            seed=session.seed,
            sort_salt=session.sort_salt,
            proportions=session.split_proportions,
        )
        selected_identities = query_splits[session.split_ordinal - 1]
        return [query_by_identity[identity] for identity in selected_identities]

    @staticmethod
    def _validate_results(
        results: Sequence[SubmittedResult], queries: Sequence[StoredQuery]
    ) -> dict[int, list[str]]:
        query_by_public_id = {str(query.query_id): query for query in queries}
        grouped: dict[int, list[SubmittedResult]] = {
            query.query_id: [] for query in queries
        }

        for result in results:
            query = query_by_public_id.get(result.query_id)
            if query is None:
                raise ValueError(
                    f"query_id is not part of this task: {result.query_id}"
                )
            if type(result.rank) is not int:
                raise ValueError("rank must be an integer")
            if type(result.score) not in (int, float) or not math.isfinite(
                result.score
            ):
                raise ValueError("score must be a finite number")

            is_sentinel = result.rank == -1
            if is_sentinel:
                if result.doc_id != "-1" or result.score != -1:
                    raise ValueError(
                        "no-results rows must have doc_id=-1, rank=-1, and score=-1"
                    )
            elif result.rank <= 0:
                raise ValueError("rank must be positive except for the no-results row")
            elif not result.doc_id:
                raise ValueError("doc_id must not be empty")

            grouped[query.query_id].append(result)

        ranked_doc_ids: dict[int, list[str]] = {}
        for query in queries:
            query_results = grouped[query.query_id]
            if not query_results:
                raise ValueError(
                    f"Every task query needs a result row: {query.query_id}"
                )
            if any(result.rank == -1 for result in query_results):
                if len(query_results) != 1:
                    raise ValueError(
                        "A no-results row cannot be combined with result rows"
                    )
                ranked_doc_ids[query.query_id] = []
                continue

            doc_ids = [result.doc_id for result in query_results]
            if len(set(doc_ids)) != len(doc_ids):
                raise ValueError(
                    f"Duplicate doc_id for query_id {query.query_id}"
                )
            ranks = sorted(result.rank for result in query_results)
            expected_ranks = list(range(1, len(query_results) + 1))
            if ranks != expected_ranks:
                raise ValueError(
                    f"Ranks for query_id {query.query_id} must be unique and "
                    "contiguous starting at 1"
                )
            ranked_doc_ids[query.query_id] = [
                result.doc_id
                for result in sorted(query_results, key=lambda row: row.rank)
            ]
        return ranked_doc_ids
