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

    dataset_name: Literal["msmarco", "esci", "doug_blog"]
    eval_mode: Literal["ndcg", "mrr"]
    splits: list[SplitValue] = Field(min_length=1)
    num_queries: Annotated[StrictInt, Field(ge=1)] | None = None
    seed: Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)] = 42


class CreateSessionResponse(BaseModel):
    """Split credentials returned by session creation."""

    split_tokens: list[str]


class EvalQueryResponse(BaseModel):
    """A query assigned to a created task."""

    query_id: str
    query_text: str
    metadata: dict[str, Any] | None


class TaskResponse(BaseModel):
    """Task identifier and selected evaluation metric."""

    id: str
    eval_mode: str


class CreateTaskResponse(BaseModel):
    """Task and its complete assigned query list."""

    dataset_name: str
    task: TaskResponse
    queries: list[EvalQueryResponse]


class SubmittedResultRequest(RequestModel):
    """One document result; extra metadata is accepted and ignored."""

    model_config = ConfigDict(extra="ignore")

    query_id: StrictStr
    doc_id: StrictStr
    rank: StrictInt
    score: FiniteNumber


class CompleteTaskRequest(RequestModel):
    """Structured JSON equivalent of the CLI results CSV."""

    results: list[SubmittedResultRequest]


class CompleteTaskResponse(BaseModel):
    """Metric output; the metric key is `ndcg` or `mrr`."""

    task_id: str
    metrics: dict[str, float]
    queries: list[dict[str, str | float]]


class HealthResponse(BaseModel):
    """Basic liveness/readiness response."""

    status: Literal["ok"]
