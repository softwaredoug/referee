"""Behavioral coverage for loading and normalizing judgment datasets."""

import os
from contextlib import closing
from types import SimpleNamespace
from uuid import uuid4

import psycopg2
import pytest

from referee.judgments import source
from referee.judgments.controller import LoadJudgmentsController
from referee.judgments.db import JudgmentsDB
from referee.judgments.models import (
    DatasetDefinition,
    JudgmentRecord,
    LoadJudgmentsTask,
)


class FakeDataFrame:
    """Minimal dataframe surface used to test the cheat-at-search adapter."""

    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]) -> None:
        self.columns = columns
        self._rows = rows

    def itertuples(self, *, index: bool, name: None) -> list[tuple[object, ...]]:
        assert index is False
        assert name is None
        return self._rows


def test_msmarco_uses_cheat_at_search_judgments_and_marks_dev_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataframe = FakeDataFrame(
        ["query_id", "query", "doc_id", "grade"],
        [(1234, "capital of France", 99, 1)],
    )
    monkeypatch.setattr(
        source,
        "import_module",
        lambda module_name: SimpleNamespace(judgments=dataframe),
    )

    records = list(source.load_source_records("msmarco"))

    assert records == [
        JudgmentRecord(
            source_query_id="1234",
            split="dev",
            keywords="capital of France",
            metadata=None,
            doc_id="99",
            grade=1,
        )
    ]


def test_esci_preserves_source_split_and_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataframe = FakeDataFrame(
        [
            "query_id",
            "query",
            "doc_id",
            "grade",
            "split",
            "product_locale",
        ],
        [("q-1", "pasta", "product-1", 3, "test", "en-US")],
    )
    monkeypatch.setattr(
        source,
        "import_module",
        lambda module_name: SimpleNamespace(judgments=dataframe),
    )

    records = list(source.load_source_records("esci"))

    assert records == [
        JudgmentRecord(
            source_query_id="q-1",
            split="test",
            keywords="pasta",
            metadata={"locale": "en-US"},
            doc_id="product-1",
            grade=3,
        )
    ]


def test_doug_blog_imports_real_small_dataset_into_postgres() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL is required for the PostgreSQL judgment tests")

    dataset_name = f"doug_blog_test_{uuid4().hex}"
    database = JudgmentsDB(database_url)
    controller = LoadJudgmentsController(
        database,
        source_loader=lambda _: source.load_source_records("doug_blog"),
        dataset_definitions={
            dataset_name: DatasetDefinition(
                dataset_name=dataset_name,
                min_grade=0,
                max_grade=1,
                metric="mrr",
            )
        },
    )
    try:
        result = controller.load_judgments(LoadJudgmentsTask(dataset_name))
        assert len(result.datasets) == 1
        assert result.datasets[0].dataset_name == dataset_name
        assert result.datasets[0].query_count > 0
        assert result.datasets[0].judgment_count >= result.datasets[0].query_count

        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT count(*), count(DISTINCT q.query_id),
                               count(DISTINCT q.query_id)
                                   FILTER (WHERE q.split IS NULL),
                               min(j.grade), max(j.grade), d.metric
                        FROM datasets AS d
                        JOIN queries AS q USING (dataset_id)
                        JOIN judgments AS j USING (query_id)
                        WHERE d.dataset_name = %s
                        GROUP BY d.metric
                        """,
                        (dataset_name,),
                    )
                    row = cursor.fetchone()

        assert row is not None
        assert row[0] == result.datasets[0].judgment_count
        assert row[1] == result.datasets[0].query_count
        assert row[2] == result.datasets[0].query_count
        assert (row[3], row[4], row[5]) == (1, 1, "mrr")
    finally:
        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM datasets WHERE dataset_name = %s", (dataset_name,)
                    )


def test_bulk_load_normalizes_queries_and_replaces_dataset() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL is required for the PostgreSQL judgment tests")

    dataset_name = f"judgments_test_{uuid4().hex}"
    definition = DatasetDefinition(
        dataset_name=dataset_name, min_grade=0, max_grade=3, metric="ndcg"
    )
    database = JudgmentsDB(database_url)
    first_records = [
        JudgmentRecord("q-1", "train", "pasta", {"locale": "en-US"}, "p-1", 3),
        JudgmentRecord("q-1", "train", "pasta", {"locale": "en-US"}, "p-2", 1),
        JudgmentRecord("q-1", "test", "pasta", {"locale": "en-US"}, "p-1", 0),
        JudgmentRecord("q-2", "test", "bread", {"locale": "en-GB"}, "p-3", 2),
    ]

    try:
        first_result = database.replace_dataset(definition, first_records, batch_size=2)
        assert (first_result.query_count, first_result.judgment_count) == (3, 4)

        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT q.source_query_id, q.split, count(j.judgment_id)
                        FROM datasets AS d
                        JOIN queries AS q USING (dataset_id)
                        JOIN judgments AS j USING (query_id)
                        WHERE d.dataset_name = %s
                        GROUP BY q.source_query_id, q.split
                        ORDER BY q.source_query_id, q.split
                        """,
                        (dataset_name,),
                    )
                    split_rows = cursor.fetchall()

        assert split_rows == [
            ("q-1", "test", 1),
            ("q-1", "train", 2),
            ("q-2", "test", 1),
        ]

        replacement_records = [
            JudgmentRecord("q-3", "test", "soup", {"locale": "en-US"}, "p-4", 0)
        ]
        replacement_result = database.replace_dataset(definition, replacement_records)
        assert (replacement_result.query_count, replacement_result.judgment_count) == (
            1,
            1,
        )

        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT q.source_query_id, q.split, q.keywords, q.metadata,
                               j.doc_id, j.grade, d.min_grade, d.max_grade, d.metric
                        FROM datasets AS d
                        JOIN queries AS q USING (dataset_id)
                        JOIN judgments AS j USING (query_id)
                        WHERE d.dataset_name = %s
                        """,
                        (dataset_name,),
                    )
                    rows = cursor.fetchall()

        assert rows == [
            (
                "q-3",
                "test",
                "soup",
                {"locale": "en-US"},
                "p-4",
                0,
                0,
                3,
                "ndcg",
            )
        ]
    finally:
        with closing(psycopg2.connect(database_url)) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM datasets WHERE dataset_name = %s", (dataset_name,)
                    )
