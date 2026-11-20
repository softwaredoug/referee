"""FastAPI application entry point."""

import logging
from contextlib import closing

import psycopg2
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from referee.api.dependencies import get_database_url
from referee.api.routes import router
from referee.api.schemas import HealthResponse
from referee.eval.errors import (
    InvalidBearerTokenError,
    TaskAlreadyCompleteError,
    TaskNotFoundError,
)

logger = logging.getLogger(__name__)
API_DESCRIPTION = """\
The Search Autoresearch Referee assigns judged query sets to retrieval runs and
calculates **NDCG** or **MRR** from the submitted rankings. Its main consumers
are an orchestrator and one or more retrieval agents.

## Recommended agent workflow

1. The orchestrator calls `POST /v1/sessions` once with a dataset, metric, and
   ordered split proportions. The response contains one `split_token` per
   proportion, in the same order. Store the token-to-agent mapping securely.
2. Give each agent only its assigned token and the API base URL. The agent calls
   `POST /v1/tasks` with `Authorization: Bearer <split_token>` and receives a
   task ID plus the **complete query list** for that split.
3. The agent runs its retrieval system for every returned query, preserving
   each `query_id`, then calls `POST /v1/tasks/{task_id}/complete` with all
   ranked result rows and the same token.
4. Save and return the successful completion response to the orchestrator. It
   contains an overall score and per-query scores under the session metric key.

Splits are disjoint partitions; their order has no built-in train, validation,
or holdout meaning. For comparisons on identical queries, create one split
(`splits: [1.0]`) and create a separate task for each retrieval run using that
split token. The orchestrator, not this API, decides how to aggregate scores.

## Authentication and lifecycle

There is no overall user/API-key authentication in this version, and session
creation is unauthenticated. Task creation and completion require a split
bearer token. Treat tokens as secrets and do not give an agent tokens for other
splits. A token may create multiple distinct tasks, each covering the same
split. Completion is single-use. There are no session/task lookup or result
recovery routes, so keep the create-session tokens, task IDs, and successful
completion responses in the orchestrator's run state. POST requests are not
idempotent; an ambiguous timeout followed by a retry may create another
session/task or encounter an already-completed task.

## Result requirements

Submit one or more rows for **every** query returned by the task. For each
query, ranks must be unique and contiguous from `1`; document IDs must not
repeat. To report no results, submit exactly one row with `doc_id="-1"`,
`rank=-1`, and `score=-1`. `score` must otherwise be finite but does not affect
the metric; rank determines result order. Optional result metadata is accepted
and ignored. Metrics are calculated at depth 10. Invalid result submissions
return `422` and leave the task incomplete; a successful completion returns
`200`, and a later completion attempt returns `409`.

The detailed consumer guide is in the repository's `docs/api.md` under
"Consumer workflow: orchestrator and subagents". Request examples and field
rules are also shown on each operation below.
"""
OPENAPI_TAGS = [
    {
        "name": "sessions",
        "description": (
            "Create sessions and partition a selected query pool. The returned "
            "split tokens are ordered to match the supplied proportions."
        ),
    },
    {
        "name": "tasks",
        "description": (
            "Create a task for a split token, retrieve its complete query list, "
            "then submit ranked results once to calculate the metric."
        ),
    },
    {
        "name": "health",
        "description": (
            "Container liveness and database/schema readiness probes; these "
            "routes do not require bearer credentials."
        ),
    },
]
REQUIRED_TABLES = (
    "datasets",
    "sessions",
    "session_splits",
    "tasks",
    "queries",
    "judgments",
)


def create_app() -> FastAPI:
    """Build the API app without opening a database connection at import time."""
    application = FastAPI(
        title="Search Autoresearch Referee API",
        description=API_DESCRIPTION,
        version="1.0.0",
        openapi_tags=OPENAPI_TAGS,
    )
    application.include_router(router)

    @application.exception_handler(InvalidBearerTokenError)
    async def invalid_bearer_token_handler(
        request: Request, error: InvalidBearerTokenError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(error)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @application.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(
        request: Request, error: TaskNotFoundError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(error)},
        )

    @application.exception_handler(TaskAlreadyCompleteError)
    async def task_already_complete_handler(
        request: Request, error: TaskAlreadyCompleteError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(error)},
        )

    @application.exception_handler(ValueError)
    async def value_error_handler(
        request: Request, error: ValueError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": str(error)},
        )

    @application.exception_handler(psycopg2.OperationalError)
    async def database_unavailable_handler(
        request: Request, error: psycopg2.OperationalError
    ) -> JSONResponse:
        del request
        logger.error("Database unavailable (%s)", type(error).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Database is unavailable"},
        )

    @application.exception_handler(psycopg2.Error)
    async def database_error_handler(
        request: Request, error: psycopg2.Error
    ) -> JSONResponse:
        del request
        logger.error("Database operation failed (%s)", type(error).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Database operation failed"},
        )

    @application.get(
        "/healthz",
        response_model=HealthResponse,
        tags=["health"],
        summary="Check API process liveness",
        description=(
            "Returns `ok` when the API process can serve requests. This probe "
            "does not contact PostgreSQL; use `/readyz` for database readiness."
        ),
    )
    def liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get(
        "/readyz",
        response_model=HealthResponse,
        tags=["health"],
        summary="Check database and schema readiness",
        description=(
            "Returns `ok` only when PostgreSQL is reachable and the required "
            "schema tables exist. It does not create the schema or load datasets."
        ),
        responses={
            503: {"description": "Database unavailable or schema not initialized."},
        },
    )
    def readiness() -> HealthResponse:
        database_url = get_database_url()
        table_array = list(REQUIRED_TABLES)
        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT to_regclass(table_name) IS NOT NULL "
                        "FROM unnest(%s::text[]) AS table_name",
                        (table_array,),
                    )
                    if not all(row[0] for row in cursor.fetchall()):
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Database schema is not ready",
                        )
        return HealthResponse(status="ok")

    return application


app = create_app()
