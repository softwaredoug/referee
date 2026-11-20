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
        version="1.0.0",
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

    @application.get("/healthz", response_model=HealthResponse, include_in_schema=False)
    def liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get("/readyz", response_model=HealthResponse, include_in_schema=False)
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
