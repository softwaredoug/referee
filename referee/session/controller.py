"""Session creation use case."""

from dataclasses import dataclass
import secrets

from referee.session.allocation import normalize_split_proportions
from referee.session.db import SessionDB

ALLOWED_DATASETS = frozenset({"msmarco", "esci", "doug_blog"})
ALLOWED_EVAL_MODES = frozenset({"ndcg", "mrr"})
MIN_SEED = -(2**63)
MAX_SEED = 2**63 - 1


@dataclass(frozen=True)
class CreateSessionTask:
    """Structured input for creating a session."""

    dataset_name: str
    eval_mode: str
    splits: tuple[float, ...]
    num_queries: int | None = None
    seed: int = 42


@dataclass(frozen=True)
class CreateSessionResult:
    """Split tokens returned to the session creator in ordinal order."""

    split_tokens: list[str]


class CreateSessionController:
    """Validate a request, create split tokens, and persist the session."""

    def __init__(self, session_db: SessionDB) -> None:
        self._session_db = session_db

    def create_session(self, task: CreateSessionTask) -> CreateSessionResult:
        if task.dataset_name not in ALLOWED_DATASETS:
            allowed = ", ".join(sorted(ALLOWED_DATASETS))
            raise ValueError(f"dataset_name must be one of: {allowed}")
        if task.eval_mode not in ALLOWED_EVAL_MODES:
            allowed = ", ".join(sorted(ALLOWED_EVAL_MODES))
            raise ValueError(f"eval_mode must be one of: {allowed}")
        if task.num_queries is not None and (
            type(task.num_queries) is not int
            or task.num_queries < 1
        ):
            raise ValueError("num_queries must be a positive integer")
        if (
            type(task.seed) is not int
            or not MIN_SEED <= task.seed <= MAX_SEED
        ):
            raise ValueError("seed must be a signed 64-bit integer")

        proportions = normalize_split_proportions(task.splits)
        split_tokens = [secrets.token_urlsafe(32) for _ in proportions]
        sort_salt = secrets.token_hex(32)

        self._session_db.create_session(
            dataset_name=task.dataset_name,
            eval_mode=task.eval_mode,
            num_queries=task.num_queries,
            seed=task.seed,
            sort_salt=sort_salt,
            splits=[
                (token, proportion, ordinal)
                for ordinal, (token, proportion) in enumerate(
                    zip(split_tokens, proportions, strict=True), start=1
                )
            ],
        )
        return CreateSessionResult(split_tokens=split_tokens)
