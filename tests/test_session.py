"""Behavioral coverage for session creation."""

import json
import os
import sys
from contextlib import closing

import psycopg2
import pytest

from referee.cli.create_session import main
from referee.session.controller import CreateSessionController, CreateSessionTask
from referee.session.db import SessionDB


@pytest.mark.parametrize(
    ("dataset_name", "eval_mode", "training_key_count", "message"),
    [
        ("unknown", "ndcg", 1, "dataset_name"),
        ("msmarco", "unknown", 1, "eval_mode"),
        ("msmarco", "ndcg", 0, "training_key_count"),
        ("msmarco", "ndcg", True, "training_key_count"),
    ],
)
def test_create_session_rejects_invalid_input(
    dataset_name: str,
    eval_mode: str,
    training_key_count: int,
    message: str,
) -> None:
    controller = CreateSessionController(SessionDB("unused"))

    with pytest.raises(ValueError, match=message):
        controller.create_session(
            CreateSessionTask(
                dataset_name=dataset_name,
                eval_mode=eval_mode,
                training_key_count=training_key_count,
            )
        )


@pytest.mark.parametrize(
    ("training_key_args", "expected_training_keys"),
    [([], 1), (["--training_key_count", "2"], 2)],
)
def test_cli_creates_and_persists_holdout_and_training_keys(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    training_key_args: list[str],
    expected_training_keys: int,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run the PostgreSQL session test")

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create-session",
            "--dataset_name",
            "msmarco",
            "--eval_mode",
            "ndcg",
            *training_key_args,
        ],
    )
    main()
    result_data = json.loads(capsys.readouterr().out)
    holdout_key = result_data["holdout_key"]
    training_keys = result_data["training_keys"]

    try:
        assert set(result_data) == {"holdout_key", "training_keys"}
        assert len(training_keys) == expected_training_keys
        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT session_key_id, key_type, dataset_name,
                               eval_mode, parent_key
                        FROM session_keys
                        WHERE key_value = %s OR key_value = ANY(%s)
                        ORDER BY key_type, key_value
                        """,
                        (holdout_key, training_keys),
                    )
                    rows = cursor.fetchall()

                    assert len(rows) == expected_training_keys + 1
                    holdout_rows = [row for row in rows if row[1] == "holdout"]
                    training_rows = [row for row in rows if row[1] == "training"]
                    assert len(holdout_rows) == 1
                    assert len(training_rows) == expected_training_keys
                    assert all(row[2:4] == ("msmarco", "ndcg") for row in rows)
                    assert all(row[4] == holdout_rows[0][0] for row in training_rows)
                    assert holdout_rows[0][4] is None
    finally:
        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM session_keys WHERE key_value = %s",
                        (holdout_key,),
                    )
