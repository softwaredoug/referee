"""Thin FastAPI routes that adapt HTTP payloads to subsystem controllers."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from referee.api.dependencies import get_eval_controller, get_session_controller
from referee.api.schemas import (
    CompleteTaskRequest,
    CompleteTaskResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    CreateTaskResponse,
    EvalQueryResponse,
    SubmittedResultRequest,
    TaskResponse,
)
from referee.eval.controller import EvalController
from referee.eval.models import (
    CompleteTaskTask,
    CreateTaskTask,
    SubmittedResult,
)
from referee.session.controller import (
    CreateSessionController,
    CreateSessionTask,
)

router = APIRouter()
bearer_auth = HTTPBearer(auto_error=False)


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
