"""PostgreSQL access for evaluation tasks."""

import os
from contextlib import closing
from typing import Any, cast

import psycopg2

from referee.eval.models import EvalSessionContext, StoredQuery, TaskEvalContext
from referee.eval.timing import TimingProbe, timed
from referee.eval.errors import (
    InvalidBearerTokenError,
    TaskAlreadyCompleteError,
    TaskNotFoundError,
)


class EvalDB:
    """Read session/query judgments and persist task completion state."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        timing_probe: TimingProbe | None = None,
    ) -> None:
        self._database_url = database_url or os.environ.get("DATABASE_URL")
        if not self._database_url:
            raise ValueError("DATABASE_URL must be set to connect to PostgreSQL")
        self._timing_probe = timing_probe

    def get_session_context(self, bearer_token: str) -> EvalSessionContext:
        """Load session allocation data for a valid split bearer token."""
        with timed(self._timing_probe, "db.session_context.connect"):
            connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    with timed(self._timing_probe, "db.session_context.token_lookup"):
                        cursor.execute(
                            """
                            SELECT session_split_id
                            FROM session_splits
                            WHERE bearer_token = %s
                            """,
                            (bearer_token,),
                        )
                        split_row = cursor.fetchone()
                    if split_row is None:
                        raise InvalidBearerTokenError("Invalid bearer token")
                    return self._load_session_context(cursor, split_row[0])

    def create_task(self, bearer_token: str, task_id: str) -> None:
        """Create a task and update last-used timestamps atomically."""
        with timed(self._timing_probe, "db.create_task.connect"):
            connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    with timed(self._timing_probe, "db.create_task.insert"):
                        cursor.execute(
                            """
                            INSERT INTO tasks (task_id, session_split_id)
                            SELECT %s, session_split_id
                            FROM session_splits
                            WHERE bearer_token = %s
                            RETURNING session_split_id
                            """,
                            (task_id, bearer_token),
                        )
                        task_row = cursor.fetchone()
                    if task_row is None:
                        raise InvalidBearerTokenError("Invalid bearer token")
                    with timed(self._timing_probe, "db.create_task.touch_split"):
                        cursor.execute(
                            """
                            UPDATE session_splits
                            SET last_used_at = CURRENT_TIMESTAMP
                            WHERE session_split_id = %s
                            RETURNING session_id
                            """,
                            (task_row[0],),
                        )
                        split_row = cursor.fetchone()
                    if split_row is None:
                        raise RuntimeError("Created task has no session split")
                    with timed(self._timing_probe, "db.create_task.touch_session"):
                        cursor.execute(
                            """
                            UPDATE sessions
                            SET last_used_at = CURRENT_TIMESTAMP
                            WHERE session_id = %s
                            """,
                            (split_row[0],),
                        )

    def get_task_context(
        self, task_id: str, bearer_token: str
    ) -> TaskEvalContext:
        """Load a task only when the supplied bearer token owns its split."""
        with timed(self._timing_probe, "db.task_context.connect"):
            connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    with timed(self._timing_probe, "db.task_context.task_lookup"):
                        cursor.execute(
                            """
                            SELECT task_id, complete, session_split_id
                            FROM tasks
                            JOIN session_splits USING (session_split_id)
                            WHERE task_id = %s AND bearer_token = %s
                            """,
                            (task_id, bearer_token),
                        )
                        task_row = cursor.fetchone()
                    if task_row is None:
                        raise TaskNotFoundError(
                            "Task does not exist or does not belong to "
                            "this bearer token"
                        )
                    session = self._load_session_context(cursor, task_row[2])
                    return TaskEvalContext(
                        task_id=task_row[0],
                        complete=task_row[1],
                        session=session,
                    )

    def get_judgments(
        self, query_ids: list[int]
    ) -> dict[int, dict[str, int]]:
        """Load judgments for the requested query IDs."""
        judgments: dict[int, dict[str, int]] = {
            query_id: {} for query_id in query_ids
        }
        if not query_ids:
            return judgments

        with timed(self._timing_probe, "db.judgments.connect"):
            connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    with timed(self._timing_probe, "db.judgments.load"):
                        cursor.execute(
                            """
                            SELECT query_id, doc_id, grade
                            FROM judgments
                            WHERE query_id = ANY(%s)
                            """,
                            (query_ids,),
                        )
                        for query_id, doc_id, grade in cursor.fetchall():
                            judgments[query_id][doc_id] = grade
        return judgments

    def mark_task_complete(self, task_id: str, bearer_token: str) -> None:
        """Mark a task complete once, guarded by its owning bearer token."""
        with timed(self._timing_probe, "db.complete_task.connect"):
            connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    with timed(self._timing_probe, "db.complete_task.update"):
                        cursor.execute(
                            """
                            UPDATE tasks AS t
                            SET complete = TRUE,
                                last_modified_at = CURRENT_TIMESTAMP
                            FROM session_splits AS sp
                            WHERE t.session_split_id = sp.session_split_id
                              AND t.task_id = %s
                              AND sp.bearer_token = %s
                              AND t.complete = FALSE
                            RETURNING sp.session_split_id
                            """,
                            (task_id, bearer_token),
                        )
                        split_row = cursor.fetchone()
                    if split_row is None:
                        raise TaskAlreadyCompleteError("Task is already complete")
                    with timed(self._timing_probe, "db.complete_task.touch_split"):
                        cursor.execute(
                            """
                            UPDATE session_splits
                            SET last_used_at = CURRENT_TIMESTAMP
                            WHERE session_split_id = %s
                            RETURNING session_id
                            """,
                            (split_row[0],),
                        )
                        session_row = cursor.fetchone()
                    if session_row is None:
                        raise RuntimeError("Completed task has no session split")
                    with timed(self._timing_probe, "db.complete_task.touch_session"):
                        cursor.execute(
                            """
                            UPDATE sessions
                            SET last_used_at = CURRENT_TIMESTAMP
                            WHERE session_id = %s
                            """,
                            (session_row[0],),
                        )

    def _load_session_context(
        self, cursor: Any, session_split_id: int
    ) -> EvalSessionContext:
        with timed(self._timing_probe, "db.session_context.session_lookup"):
            cursor.execute(
                """
                SELECT s.session_id, sp.session_split_id, s.dataset_name,
                       s.eval_mode, s.num_queries, s.user_seed, s.sort_salt,
                       sp.ordinal
                FROM sessions AS s
                JOIN session_splits AS sp USING (session_id)
                WHERE sp.session_split_id = %s
                """,
                (session_split_id,),
            )
            session_row = cursor.fetchone()
        if session_row is None:
            raise ValueError("Session split does not exist")

        session_id = session_row[0]
        with timed(self._timing_probe, "db.session_context.load_splits"):
            cursor.execute(
                """
                SELECT proportion
                FROM session_splits
                WHERE session_id = %s
                ORDER BY ordinal
                """,
                (session_id,),
            )
            split_proportions = tuple(row[0] for row in cursor.fetchall())

        with timed(self._timing_probe, "db.session_context.load_queries"):
            cursor.execute(
                """
                SELECT q.query_id, q.source_query_id, q.split, q.keywords,
                       q.metadata
                FROM queries AS q
                JOIN datasets AS d USING (dataset_id)
                WHERE d.dataset_name = %s
                """,
                (session_row[2],),
            )
            queries = tuple(
                StoredQuery(
                    query_id=row[0],
                    source_query_id=row[1],
                    source_split=row[2],
                    query_text=row[3],
                    metadata=cast(dict[str, Any] | None, row[4]),
                )
                for row in cursor.fetchall()
            )

        return EvalSessionContext(
            session_id=session_row[0],
            session_split_id=session_row[1],
            dataset_name=session_row[2],
            eval_mode=session_row[3],
            num_queries=session_row[4],
            seed=session_row[5],
            sort_salt=session_row[6],
            split_ordinal=session_row[7],
            split_proportions=split_proportions,
            queries=queries,
        )
