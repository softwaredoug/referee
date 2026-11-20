"""Structured inputs and outputs for evaluation tasks."""

from dataclasses import dataclass
from typing import Any

from referee.session.allocation import QueryIdentity


@dataclass(frozen=True)
class StoredQuery:
    """A query loaded from the judgments database."""

    query_id: int
    source_query_id: str
    source_split: str | None
    query_text: str
    metadata: dict[str, Any] | None

    @property
    def identity(self) -> QueryIdentity:
        """Return the stable source identity used by session allocation."""
        return self.source_query_id, self.source_split


@dataclass(frozen=True)
class EvalSessionContext:
    """Session allocation and query data needed to create or evaluate a task."""

    session_id: int
    session_split_id: int
    dataset_name: str
    eval_mode: str
    num_queries: int | None
    seed: int
    sort_salt: str
    split_ordinal: int
    split_proportions: tuple[float, ...]
    queries: tuple[StoredQuery, ...]


@dataclass(frozen=True)
class TaskEvalContext:
    """A task and its associated session data."""

    task_id: str
    complete: bool
    session: EvalSessionContext


@dataclass(frozen=True)
class EvalQuery:
    """A query returned to a caller for retrieval."""

    query_id: str
    query_text: str
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class TaskDescriptor:
    """Public task identity and its session-selected metric."""

    id: str
    eval_mode: str


@dataclass(frozen=True)
class CreateTaskTask:
    """Structured input for creating a task from a split token."""

    bearer_token: str


@dataclass(frozen=True)
class CreateTaskResult:
    """Task metadata and all queries assigned to its split."""

    dataset_name: str
    task: TaskDescriptor
    queries: list[EvalQuery]


@dataclass(frozen=True)
class SubmittedResult:
    """One returned document, with rank and an informational score."""

    query_id: str
    doc_id: str
    rank: int
    score: float


@dataclass(frozen=True)
class CompleteTaskTask:
    """Structured input for submitting results for an existing task."""

    bearer_token: str
    task_id: str
    results: list[SubmittedResult]


@dataclass(frozen=True)
class QueryMetric:
    """One per-query evaluation result."""

    query_id: str
    query_text: str
    score: float


@dataclass(frozen=True)
class CompleteTaskResult:
    """Metric results returned after successfully completing a task."""

    task_id: str
    metric_name: str
    metric_score: float
    queries: list[QueryMetric]
