"""FastAPI dependencies for the existing subsystem controllers."""

import os

from fastapi import HTTPException, status

from referee.eval.controller import EvalController
from referee.eval.db import EvalDB
from referee.session.controller import CreateSessionController
from referee.session.db import SessionDB


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured",
        )
    return database_url


def get_session_controller() -> CreateSessionController:
    """Create a session controller using the configured PostgreSQL URL."""
    return CreateSessionController(SessionDB(get_database_url()))


def get_eval_controller() -> EvalController:
    """Create an eval controller using the configured PostgreSQL URL."""
    return EvalController(EvalDB(get_database_url()))
