"""Session creation use case."""

from dataclasses import dataclass
import secrets

from referee.session.db import SessionDB

ALLOWED_DATASETS = frozenset({"msmarco", "esci", "doug_blog"})
ALLOWED_EVAL_MODES = frozenset({"ndcg"})


@dataclass(frozen=True)
class CreateSessionTask:
    """Structured input for creating a session."""

    dataset_name: str
    eval_mode: str
    training_key_count: int = 1


@dataclass(frozen=True)
class CreateSessionResult:
    """Keys returned to the session creator."""

    holdout_key: str
    training_keys: list[str]


class CreateSessionController:
    """Validate a request, create secure keys, and persist the session."""

    def __init__(self, session_db: SessionDB) -> None:
        self._session_db = session_db

    def create_session(self, task: CreateSessionTask) -> CreateSessionResult:
        if task.dataset_name not in ALLOWED_DATASETS:
            allowed = ", ".join(sorted(ALLOWED_DATASETS))
            raise ValueError(f"dataset_name must be one of: {allowed}")
        if task.eval_mode not in ALLOWED_EVAL_MODES:
            allowed = ", ".join(sorted(ALLOWED_EVAL_MODES))
            raise ValueError(f"eval_mode must be one of: {allowed}")
        if isinstance(task.training_key_count, bool) or task.training_key_count < 1:
            raise ValueError("training_key_count must be a positive integer")

        holdout_key = secrets.token_urlsafe(32)
        training_keys = [
            secrets.token_urlsafe(32) for _ in range(task.training_key_count)
        ]
        self._session_db.create_session(
            dataset_name=task.dataset_name,
            eval_mode=task.eval_mode,
            holdout_key=holdout_key,
            training_keys=training_keys,
        )
        return CreateSessionResult(
            holdout_key=holdout_key,
            training_keys=training_keys,
        )
