"""PostgreSQL access for sessions and query splits."""

import os
from contextlib import closing
from typing import Any, cast

import psycopg2


class SessionDB:
    """Persist session parameters and their bearer-token splits."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or os.environ.get("DATABASE_URL")
        if not self._database_url:
            raise ValueError("DATABASE_URL must be set to connect to PostgreSQL")

    def create_session(
        self,
        *,
        dataset_name: str,
        eval_mode: str,
        num_queries: int | None,
        seed: int,
        sort_salt: str,
        splits: list[tuple[str, float, int]],
    ) -> None:
        """Insert a session and its splits atomically after checking the dataset."""
        connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(q.query_id)
                        FROM datasets AS d
                        LEFT JOIN queries AS q USING (dataset_id)
                        WHERE d.dataset_name = %s
                        GROUP BY d.dataset_id
                        """,
                        (dataset_name,),
                    )
                    dataset_row = cursor.fetchone()
                    if dataset_row is None:
                        raise ValueError(
                            f"dataset_name is not loaded: {dataset_name}"
                        )
                    available_query_count = dataset_row[0]
                    if available_query_count == 0:
                        raise ValueError(f"dataset has no queries: {dataset_name}")
                    if (
                        num_queries is not None
                        and num_queries > available_query_count
                    ):
                        raise ValueError(
                            "num_queries cannot exceed the dataset query count "
                            f"({available_query_count})"
                        )

                    cursor.execute(
                        """
                        INSERT INTO sessions (
                            dataset_name,
                            eval_mode,
                            num_queries,
                            user_seed,
                            sort_salt
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING session_id
                        """,
                        (dataset_name, eval_mode, num_queries, seed, sort_salt),
                    )
                    session_row = cursor.fetchone()
                    if session_row is None:
                        raise RuntimeError(
                            "PostgreSQL did not return the session id"
                        )
                    session_id = session_row[0]

                    cursor.executemany(
                        """
                        INSERT INTO session_splits (
                            session_id, bearer_token, proportion, ordinal
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        [
                            (session_id, token, proportion, ordinal)
                            for token, proportion, ordinal in splits
                        ],
                    )
