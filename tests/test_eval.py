"""Behavioral coverage for evaluation task creation and completion."""

import os
import sys
from contextlib import closing
from pathlib import Path

import psycopg2
import pytest

from referee.cli.complete_task import main as complete_task_main
from referee.cli.complete_task import read_results_csv
from referee.cli.create_task import main as create_task_main
from referee.eval.controller import EvalController
from referee.eval.db import EvalDB
from referee.eval.metrics import mrr_at_10, ndcg_at_10
from referee.eval.models import (
    CompleteTaskTask,
    CreateTaskTask,
    StoredQuery,
    SubmittedResult,
)
from referee.session.controller import CreateSessionController, CreateSessionTask
from referee.session.db import SessionDB


def _database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL is required for the PostgreSQL eval tests")
    return database_url


def _create_session(
    database_url: str,
    *,
    eval_mode: str = "ndcg",
    splits: tuple[float, ...] = (1.0,),
) -> tuple[list[str], int]:
    result = CreateSessionController(SessionDB(database_url)).create_session(
        CreateSessionTask(
            dataset_name="doug_blog",
            eval_mode=eval_mode,
            splits=splits,
        )
    )
    with closing(psycopg2.connect(database_url)) as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT session_id
                    FROM session_splits
                    WHERE bearer_token = %s
                    """,
                    (result.split_tokens[0],),
                )
                row = cursor.fetchone()
    assert row is not None
    return result.split_tokens, row[0]


def _delete_session(database_url: str, session_id: int) -> None:
    with closing(psycopg2.connect(database_url)) as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sessions WHERE session_id = %s", (session_id,)
                )


@pytest.mark.parametrize("eval_mode", ["ndcg", "mrr"])
def test_create_task_returns_all_split_queries_and_completion_is_single_use(
    eval_mode: str,
) -> None:
    database_url = _database_url()
    split_tokens, session_id = _create_session(
        database_url, eval_mode=eval_mode
    )
    controller = EvalController(EvalDB(database_url))

    try:
        first_task = controller.create_task(
            CreateTaskTask(bearer_token=split_tokens[0])
        )
        second_task = controller.create_task(
            CreateTaskTask(bearer_token=split_tokens[0])
        )

        assert first_task.dataset_name == "doug_blog"
        assert first_task.task.eval_mode == eval_mode
        assert first_task.task.id != second_task.task.id
        assert [query.query_id for query in first_task.queries] == [
            query.query_id for query in second_task.queries
        ]
        assert first_task.queries

        eval_db = EvalDB(database_url)
        query_ids = [int(query.query_id) for query in first_task.queries]
        judgments = eval_db.get_judgments(query_ids)
        assert all(
            any(grade > 0 for grade in judgments[qid].values())
            for qid in query_ids
        )

        # One query returns no results; the remaining queries return a judged
        # document at rank 1, giving the no-results query a zero score.
        no_result_query_id = first_task.queries[0].query_id
        submitted_results: list[SubmittedResult] = []
        for query in first_task.queries:
            if query.query_id == no_result_query_id:
                submitted_results.append(
                    SubmittedResult(
                        query_id=query.query_id,
                        doc_id="-1",
                        rank=-1,
                        score=-1,
                    )
                )
                continue
            query_judgments = judgments[int(query.query_id)]
            ideal_results = sorted(
                query_judgments.items(),
                key=lambda judgment: (-judgment[1], judgment[0]),
            )
            submitted_results.extend(
                SubmittedResult(
                    query_id=query.query_id,
                    doc_id=doc_id,
                    rank=rank,
                    score=1.0,
                )
                for rank, (doc_id, _) in enumerate(ideal_results, start=1)
            )

        # A partial CSV fails and leaves the task available for a corrected
        # submission.
        with pytest.raises(ValueError, match="Every task query"):
            controller.complete_task(
                CompleteTaskTask(
                    bearer_token=split_tokens[0],
                    task_id=first_task.task.id,
                    results=submitted_results[1:],
                )
            )
        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT complete FROM tasks WHERE task_id = %s",
                        (first_task.task.id,),
                    )
                    assert cursor.fetchone() == (False,)

        completed = controller.complete_task(
            CompleteTaskTask(
                bearer_token=split_tokens[0],
                task_id=first_task.task.id,
                results=submitted_results,
            )
        )
        assert completed.metric_name == eval_mode
        assert completed.metric_score == pytest.approx(
            (len(first_task.queries) - 1) / len(first_task.queries)
        )
        assert completed.queries[0].score == 0.0

        with pytest.raises(ValueError, match="already complete"):
            controller.complete_task(
                CompleteTaskTask(
                    bearer_token=split_tokens[0],
                    task_id=first_task.task.id,
                    results=submitted_results,
                )
            )
    finally:
        _delete_session(database_url, session_id)


def test_task_cannot_be_completed_using_another_splits_token() -> None:
    database_url = _database_url()
    split_tokens, session_id = _create_session(database_url)
    other_tokens, other_session_id = _create_session(database_url)
    controller = EvalController(EvalDB(database_url))

    try:
        task = controller.create_task(CreateTaskTask(split_tokens[0]))
        with pytest.raises(ValueError, match="does not belong"):
            controller.complete_task(
                CompleteTaskTask(
                    bearer_token=other_tokens[0],
                    task_id=task.task.id,
                    results=[],
                )
            )
    finally:
        _delete_session(database_url, session_id)
        _delete_session(database_url, other_session_id)


def test_ndcg_uses_linear_grade_gain_and_log_discount() -> None:
    judgments = {"high": 3, "low": 1}
    score = ndcg_at_10(["low", "high"], judgments)
    low_first_dcg = 1.0 + 3.0 / 1.584962500721156
    ideal_dcg = 3.0 + 1.0 / 1.584962500721156

    assert score == pytest.approx(low_first_dcg / ideal_dcg)


def test_ndcg_fails_when_ideal_dcg_is_zero() -> None:
    with pytest.raises(ValueError, match="zero ideal DCG"):
        ndcg_at_10(["unjudged"], {"irrelevant": 0})


def test_mrr_uses_positive_grades_and_is_cut_off_at_ten() -> None:
    judgments = {"relevant": 2}
    assert mrr_at_10(["unjudged", "relevant"], judgments) == 0.5
    ranked = [f"unjudged-{rank}" for rank in range(10)] + ["relevant"]
    assert mrr_at_10(ranked, judgments) == 0.0


def test_result_validation_rejects_noncontiguous_ranks() -> None:
    query = StoredQuery(
        query_id=1,
        source_query_id="source-q1",
        source_split=None,
        query_text="pasta",
        metadata=None,
    )

    with pytest.raises(ValueError, match="contiguous"):
        EvalController._validate_results(
            [
                SubmittedResult("1", "doc-1", 1, 0.9),
                SubmittedResult("1", "doc-2", 3, 0.8),
            ],
            [query],
        )


def test_csv_reader_accepts_optional_metadata_and_no_results_row(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "results.csv"
    results_path.write_text(
        "query_id,doc_id,rank,score,title\n"
        "1,doc-1,1,0.9,example\n"
        "2,-1,-1,-1,\n",
        encoding="utf-8",
    )

    results = read_results_csv(results_path)

    assert results == [
        SubmittedResult("1", "doc-1", 1, 0.9),
        SubmittedResult("2", "-1", -1, -1.0),
    ]


def test_complete_task_cli_requires_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["complete-task"])

    with pytest.raises(SystemExit):
        complete_task_main()


def test_create_task_cli_requires_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["create-task"])

    with pytest.raises(SystemExit):
        create_task_main()
