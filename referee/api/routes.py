"""Thin FastAPI routes that adapt HTTP payloads to subsystem controllers."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from referee.api.dependencies import get_eval_controller, get_session_controller
from referee.api.schemas import (
    CompleteTaskRequest,
    CompleteTaskResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    DebugQueriesRequest,
    DebugQueriesResponse,
    DebugQueryResponse,
    DebugResultResponse,
    CreateTaskResponse,
    EvalQueryResponse,
    SubmittedResultRequest,
    TargetResultResponse,
    TaskResponse,
)
from referee.eval.controller import EvalController
from referee.eval.models import (
    CompleteTaskTask,
    CreateTaskTask,
    DebugQueriesTask,
    SubmittedResult,
)
from referee.session.controller import (
    CreateSessionController,
    CreateSessionTask,
)

router = APIRouter()
bearer_auth = HTTPBearer(
    auto_error=False,
    scheme_name="SplitBearerToken",
    description=(
        "Use the split token returned by `POST /v1/sessions`: "
        "`Authorization: Bearer <split_token>`. It only grants access to the "
        "split's tasks; it is not an overall user or API key."
    ),
)


def _bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


@router.post(
    "/v1/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
    summary="Create a session and its query splits",
    description=(
        "Create one query pool and partition it using the ordered `splits` "
        "proportions. Returns one bearer token per split in the same order. "
        "This endpoint is unauthenticated in the current version. Save the "
        "tokens; there is no session lookup endpoint to recover them. See the "
        "example request for a typical orchestrator setup."
    ),
    responses={
        422: {
            "description": (
                "Invalid fields, unknown dataset, or unavailable query count."
            )
        },
        503: {"description": "Database unavailable or DATABASE_URL is not configured."},
        500: {"description": "Unexpected database operation error."},
    },
)
def create_session(
    request: CreateSessionRequest,
    controller: CreateSessionController = Depends(get_session_controller),
) -> CreateSessionResponse:
    result = controller.create_session(
        CreateSessionTask(
            dataset_name=request.dataset_name,
            eval_mode=request.eval_mode,
            splits=tuple(request.splits),
            num_queries=request.num_queries,
            seed=request.seed,
        )
    )
    return CreateSessionResponse(split_tokens=result.split_tokens)


@router.post(
    "/v1/tasks",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
    summary="Create a task and retrieve its queries",
    description=(
        "Send the assigned split token as a Bearer credential. The response "
        "contains a new `task.id` and the complete query list for that split; "
        "use those exact `query_id` values in the completion request. This "
        "endpoint has no body. Each call creates a distinct task, even when "
        "the same split token is reused."
    ),
    responses={
        401: {"description": "Missing or invalid split bearer token."},
        422: {
            "description": (
                "The split cannot produce a task (for example, it contains no "
                "queries)."
            )
        },
        503: {"description": "Database unavailable or DATABASE_URL is not configured."},
        500: {"description": "Unexpected database operation error."},
    },
)
def create_task(
    token: str = Depends(_bearer_token),
    controller: EvalController = Depends(get_eval_controller),
) -> CreateTaskResponse:
    result = controller.create_task(CreateTaskTask(bearer_token=token))
    return CreateTaskResponse(
        dataset_name=result.dataset_name,
        task=TaskResponse(id=result.task.id, eval_mode=result.task.eval_mode),
        queries=[
            EvalQueryResponse(
                query_id=query.query_id,
                query_text=query.query_text,
                metadata=query.metadata,
            )
            for query in result.queries
        ],
    )


def _submitted_results(
    rows: list[SubmittedResultRequest],
) -> list[SubmittedResult]:
    return [
        SubmittedResult(
            query_id=row.query_id,
            doc_id=row.doc_id,
            rank=row.rank,
            score=row.score,
        )
        for row in rows
    ]


@router.post(
    "/v1/tasks/{task_id}/complete",
    response_model=CompleteTaskResponse,
    tags=["tasks"],
    summary="Submit ranked results and complete a task",
    description=(
        "Submit JSON results for every query in the task, using the same split "
        "token that created it. Ranks must be contiguous from 1 for each "
        'query; use exactly one `doc_id="-1"`, `rank=-1`, `score=-1` sentinel '
        "row when there are no results. The `score` is required but does not "
        "affect the metric. A valid submission completes the task once and "
        "returns overall and per-query scores. Invalid results return 422 and "
        "leave the task incomplete so they can be corrected."
    ),
    responses={
        401: {"description": "Missing split bearer token."},
        404: {"description": "Task does not exist or is not owned by this token."},
        409: {"description": "Task has already been completed."},
        422: {
            "description": (
                "Malformed or invalid result rows, or metric cannot be "
                "calculated."
            )
        },
        503: {"description": "Database unavailable."},
        500: {"description": "Unexpected database operation error."},
    },
)
def complete_task(
    task_id: str,
    request: CompleteTaskRequest,
    token: str = Depends(_bearer_token),
    controller: EvalController = Depends(get_eval_controller),
) -> CompleteTaskResponse:
    result = controller.complete_task(
        CompleteTaskTask(
            bearer_token=token,
            task_id=task_id,
            results=_submitted_results(request.results),
        )
    )
    return CompleteTaskResponse(
        task_id=result.task_id,
        metrics={result.metric_name: result.metric_score},
        queries=[
            {
                "query_id": query.query_id,
                "query_text": query.query_text,
                result.metric_name: query.score,
            }
            for query in result.queries
        ],
    )


@router.post(
    "/v1/tasks/{task_id}/debug",
    response_model=DebugQueriesResponse,
    response_model_exclude_none=True,
    tags=["tasks"],
    summary="Inspect submitted results and judgments for selected queries",
    description=(
        "Debug one or more queries in a task using its owning split bearer "
        "token. Provide the submitted rows for the requested query IDs; unlike "
        "completion, other task queries are not required. Each result is "
        "annotated with its judgment grade (unjudged documents have grade 0). "
        "Set `include_target` to include each query's top 10 judged documents, "
        "ordered by grade descending and doc_id ascending. This endpoint is "
        "read-only and works before or after completion."
    ),
    responses={
        401: {"description": "Missing split bearer token."},
        404: {"description": "Task does not exist or is not owned by this token."},
        422: {
            "description": (
                "Malformed request, a requested query is not in the task split, "
                "or a requested query has no rows in results."
            )
        },
        503: {"description": "Database unavailable."},
        500: {"description": "Unexpected database operation error."},
    },
)
def debug_task_queries(
    task_id: str,
    request: DebugQueriesRequest,
    token: str = Depends(_bearer_token),
    controller: EvalController = Depends(get_eval_controller),
) -> DebugQueriesResponse:
    result = controller.debug_queries(
        DebugQueriesTask(
            bearer_token=token,
            task_id=task_id,
            results=_submitted_results(request.results),
            query_ids=request.query_ids,
            include_target=request.include_target,
        )
    )
    return DebugQueriesResponse(
        queries={
            query_id: DebugQueryResponse(
                query_id=query.query_id,
                query_text=query.query_text,
                results=[
                    DebugResultResponse(
                        doc_id=row.doc_id,
                        rank=row.rank,
                        score=row.score,
                        relevance_grade=row.relevance_grade,
                    )
                    for row in query.results
                ],
                target=(
                    [
                        TargetResultResponse(
                            doc_id=row.doc_id,
                            relevance_grade=row.relevance_grade,
                        )
                        for row in query.target
                    ]
                    if query.target is not None
                    else None
                ),
            )
            for query_id, query in result.queries.items()
        }
    )
