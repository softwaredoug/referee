"""Behavioral coverage for session creation and query allocation."""

import json
import os
import sys
from contextlib import closing

import psycopg2
import pytest

from referee.cli.create_session import main
from referee.session.allocation import allocate_query_splits, split_sizes
from referee.session.controller import CreateSessionController, CreateSessionTask
from referee.session.db import SessionDB


@pytest.mark.parametrize(
    ("task", "message"),
    [
        (
            CreateSessionTask("unknown", "ndcg", (0.5, 0.5)),
            "dataset_name",
        ),
        (
            CreateSessionTask("msmarco", "unknown", (0.5, 0.5)),
            "eval_mode",
        ),
        (
            CreateSessionTask("msmarco", "ndcg", ()),
            "splits",
        ),
        (
            CreateSessionTask("msmarco", "ndcg", (0.7, 0.2)),
            "sum to 1",
        ),
        (
            CreateSessionTask("msmarco", "ndcg", (1.0, 0.0)),
            "positive finite",
        ),
        (
            CreateSessionTask("msmarco", "ndcg", (float("nan"),)),
            "positive finite",
        ),
        (
            CreateSessionTask("msmarco", "ndcg", (1.0,), num_queries=0),
            "num_queries",
        ),
        (
            CreateSessionTask("msmarco", "ndcg", (1.0,), seed=True),
            "seed",
        ),
    ],
)
def test_create_session_rejects_invalid_input(
    task: CreateSessionTask, message: str
) -> None:
    controller = CreateSessionController(SessionDB("unused"))

    with pytest.raises(ValueError, match=message):
        controller.create_session(task)


def test_split_sizes_use_largest_remainder_and_ordinal_tiebreak() -> None:
    assert split_sizes(10, (0.6, 0.2, 0.2)) == (6, 2, 2)
    assert split_sizes(3, (0.5, 0.5)) == (2, 1)


def test_query_allocation_is_repeatable_and_disjoint() -> None:
    query_ids = [(f"q-{index}", "test") for index in range(20)]
    kwargs = {
        "num_queries": 10,
        "seed": 42,
        "sort_salt": "per-session-salt",
        "proportions": (0.6, 0.2, 0.2),
    }

    first = allocate_query_splits(query_ids, **kwargs)
    second = allocate_query_splits(query_ids, **kwargs)

    assert first == second
    assert [len(split) for split in first] == [6, 2, 2]
    flattened = [query_id for split in first for query_id in split]
    assert len(flattened) == len(set(flattened))
    assert len(flattened) == 10


@pytest.mark.parametrize("dataset_name", ["msmarco", "doug_blog"])
def test_cli_creates_and_persists_session_splits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dataset_name: str,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL is required for the PostgreSQL session tests")

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create-session",
            "--dataset_name",
            dataset_name,
            "--eval_mode",
            "ndcg",
            "--num_queries",
            "10",
            "--seed",
            "42",
            "--splits",
            "0.6",
            "0.2",
            "0.2",
        ],
    )
    main()
    result_data = json.loads(capsys.readouterr().out)
    split_tokens = result_data["split_tokens"]
    session_id: int | None = None

    try:
        assert set(result_data) == {"split_tokens"}
        assert len(split_tokens) == 3
        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT s.session_id, s.dataset_name, s.eval_mode,
                               s.num_queries, s.user_seed, s.sort_salt,
                               sp.bearer_token, sp.proportion, sp.ordinal
                        FROM sessions AS s
                        JOIN session_splits AS sp USING (session_id)
                        WHERE sp.bearer_token = ANY(%s)
                        ORDER BY sp.ordinal
                        """,
                        (split_tokens,),
                    )
                    rows = cursor.fetchall()

        assert len(rows) == 3
        session_id = rows[0][0]
        assert all(row[0] == session_id for row in rows)
        assert all(row[1:5] == (dataset_name, "ndcg", 10, 42) for row in rows)
        assert all(len(row[5]) == 64 for row in rows)
        assert [row[6] for row in rows] == split_tokens
        assert [row[7] for row in rows] == pytest.approx([0.6, 0.2, 0.2])
        assert [row[8] for row in rows] == [1, 2, 3]
    finally:
        if session_id is not None:
            with closing(psycopg2.connect(database_url)) as connection:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "DELETE FROM sessions WHERE session_id = %s",
                            (session_id,),
                        )


def test_cli_requires_splits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["create-session", "--dataset_name", "msmarco", "--eval_mode", "ndcg"],
    )

    with pytest.raises(SystemExit):
        main()
