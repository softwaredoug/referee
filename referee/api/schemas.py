"""HTTP request and response models for the referee API."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

SplitValue = Annotated[
    StrictInt | StrictFloat,
    Field(gt=0, allow_inf_nan=False),
]
FiniteNumber = Annotated[
    StrictInt | StrictFloat,
    Field(allow_inf_nan=False),
]


class RequestModel(BaseModel):
    """Base class that rejects unknown JSON fields."""

    model_config = ConfigDict(extra="forbid")


class CreateSessionRequest(RequestModel):
    """Create-session input translated to CreateSessionTask."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "dataset_name": "msmarco",
                    "eval_mode": "mrr",
                    "num_queries": 1000,
                    "seed": 42,
                    "splits": [0.6, 0.2, 0.2],
                }
            ]
        },
    )

    dataset_name: Literal["msmarco", "esci", "doug_blog"] = Field(
        description="Loaded judgment dataset to evaluate."
    )
    eval_mode: Literal["ndcg", "mrr"] = Field(
        description="Metric calculated when a task is completed."
    )
    splits: list[SplitValue] = Field(
        min_length=1,
        description=(
            "Positive proportions summing to 1. Their order defines token and "
            "split order; it does not assign train/holdout roles."
        ),
    )
    num_queries: Annotated[
        StrictInt,
        Field(
            ge=1,
            description=(
                "Number of queries in the selected pool. Omit to use all "
                "queries in the dataset."
            ),
        ),
    ] | None = None
    seed: Annotated[
        StrictInt,
        Field(
            ge=-(2**63),
            le=2**63 - 1,
            description="Seed for repeatable query-pool selection; defaults to 42.",
        ),
    ] = 42


class CreateSessionResponse(BaseModel):
    """Split credentials returned by session creation."""

    split_tokens: list[str] = Field(
        description=(
            "Bearer tokens ordered to correspond to the request's splits. "
            "Store securely; tokens cannot be retrieved later."
        )
    )


class EvalQueryResponse(BaseModel):
    """A query assigned to a created task."""

    query_id: str = Field(description="Opaque query ID; echo it unchanged in results.")
    query_text: str = Field(description="Text to send to the retrieval system.")
    metadata: dict[str, Any] | None = Field(
        description="Dataset-specific query metadata, if present."
    )


class TaskResponse(BaseModel):
    """Task identifier and selected evaluation metric."""

    id: str = Field(description="Task ID required to submit this task's results.")
    eval_mode: str = Field(description="Metric selected for this session.")


class CreateTaskResponse(BaseModel):
    """Task and its complete assigned query list."""

    dataset_name: str
    task: TaskResponse
    queries: list[EvalQueryResponse]


class SubmittedResultRequest(RequestModel):
    """One document result; extra metadata is accepted and ignored."""

    model_config = ConfigDict(extra="ignore")

    query_id: StrictStr = Field(
        description="A query_id returned in the task's queries array."
    )
    doc_id: StrictStr = Field(
        description=(
            'Retrieved document ID as a string. For no results, use the '
            'sentinel "-1" with rank and score both -1.'
        )
    )
    rank: StrictInt = Field(
        description=(
            "Positive contiguous rank starting at 1, or -1 only for the "
            "no-results sentinel."
        )
    )
    score: FiniteNumber = Field(
        description=(
            "Finite retrieval score (required for input compatibility, but "
            "not used by NDCG or MRR). Use -1 for the no-results sentinel."
        )
    )


class CompleteTaskRequest(RequestModel):
    """Structured JSON equivalent of the CLI results CSV."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "results": [
                        {
                            "query_id": "123",
                            "doc_id": "doc-123",
                            "rank": 1,
                            "score": 12.4,
                            "title": "Optional display metadata",
                        },
                        {
                            "query_id": "456",
                            "doc_id": "-1",
                            "rank": -1,
                            "score": -1,
                        },
                    ]
                }
            ]
        },
    )

    results: list[SubmittedResultRequest] = Field(
        description=(
            "All result rows for the task. Every task query must have at least "
            "one row; rows for a query must be grouped by query_id logically, "
            "though request ordering is not significant."
        )
    )


class CompleteTaskResponse(BaseModel):
    """Metric output; the metric key is `ndcg` or `mrr`."""

    task_id: str = Field(description="The task that was completed.")
    metrics: dict[str, float] = Field(
        description="Overall arithmetic mean; key is the session metric (ndcg or mrr)."
    )
    queries: list[dict[str, str | float]] = Field(
        description=(
            "Per-query metric values. Each entry has query_id, query_text, and "
            "a score under the session metric key (ndcg or mrr)."
        )
    )


class DebugQueriesRequest(RequestModel):
    """Selected task queries and their submitted rows to inspect."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "query_ids": ["q1", "q2"],
                    "results": [
                        {
                            "query_id": "q1",
                            "doc_id": "doc-123",
                            "rank": 1,
                            "score": 12.4,
                        },
                        {
                            "query_id": "q2",
                            "doc_id": "-1",
                            "rank": -1,
                            "score": -1,
                        },
                    ],
                    "include_target": True,
                }
            ]
        },
    )

    query_ids: list[StrictStr] = Field(
        min_length=1,
        description=(
            "One or more public query IDs from this task. The response contains "
            "only these queries."
        ),
    )
    results: list[SubmittedResultRequest] = Field(
        description=(
            "Submitted rows for the requested queries. Unlike completion, rows "
            "for every task query are not required; each requested query must "
            "have at least one row."
        ),
    )
    include_target: bool = Field(
        default=False,
        description=(
            "When true, include up to 10 judged target documents per query, "
            "sorted by relevance grade descending and doc_id ascending."
        ),
    )


class DebugResultResponse(BaseModel):
    """One submitted result annotated with its relevance judgment."""

    doc_id: str
    rank: int
    score: float
    relevance_grade: int = Field(
        description="Judgment grade; unjudged documents are assigned grade 0."
    )


class TargetResultResponse(BaseModel):
    """One judged document from the query's ideal target list."""

    doc_id: str
    relevance_grade: int


class DebugQueryResponse(BaseModel):
    """Submitted results and optional target for one query."""

    query_id: str
    query_text: str
    results: list[DebugResultResponse]
    target: list[TargetResultResponse] | None = Field(
        default=None,
        description=(
            "Present only when include_target=true. Up to 10 judged documents "
            "ordered by relevance grade descending, then doc_id ascending."
        ),
    )


class DebugQueriesResponse(BaseModel):
    """Debug information keyed by the requested public query IDs."""

    queries: dict[str, DebugQueryResponse]


class HealthResponse(BaseModel):
    """Basic liveness/readiness response."""

    status: Literal["ok"]
