"""PostgreSQL access for session keys."""

import os
from contextlib import closing
from typing import Any, cast

import psycopg2


class SessionDB:
    """Persist session keys using direct PostgreSQL queries."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or os.environ.get("DATABASE_URL")
        if not self._database_url:
            raise ValueError("DATABASE_URL must be set to connect to PostgreSQL")

    def create_session(
        self,
        *,
        dataset_name: str,
        eval_mode: str,
        holdout_key: str,
        training_keys: list[str],
    ) -> None:
        """Insert a holdout key and its training keys atomically."""
        connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO session_keys (
                            key_type, key_value, dataset_name, eval_mode
                        )
                        VALUES (%s, %s, %s, %s)
                        RETURNING session_key_id
                        """,
                        ("holdout", holdout_key, dataset_name, eval_mode),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError(
                            "PostgreSQL did not return the holdout key id"
                        )
                    holdout_id = row[0]

                    cursor.executemany(
                        """
                        INSERT INTO session_keys (
                            key_type,
                            key_value,
                            dataset_name,
                            eval_mode,
                            parent_key
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        [
                            ("training", key, dataset_name, eval_mode, holdout_id)
                            for key in training_keys
                        ],
                    )
