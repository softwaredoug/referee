"""PostgreSQL bulk loading for normalized judgment data."""

import csv
import json
import os
from collections.abc import Iterable
from contextlib import closing
from io import StringIO
from typing import Any, cast

import psycopg2

from referee.judgments.models import (
    DatasetDefinition,
    DatasetLoadResult,
    JudgmentRecord,
)


class JudgmentsDB:
    """Replace dataset judgments using PostgreSQL staging and COPY."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or os.environ.get("DATABASE_URL")
        if not self._database_url:
            raise ValueError("DATABASE_URL must be set to connect to PostgreSQL")

    def replace_dataset(
        self,
        definition: DatasetDefinition,
        records: Iterable[JudgmentRecord],
        *,
        batch_size: int = 10_000,
    ) -> DatasetLoadResult:
        """Atomically replace a dataset with normalized queries and judgments."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        connection = cast(Any, psycopg2.connect(self._database_url))
        with closing(connection):
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO datasets (
                            dataset_name, min_grade, max_grade, metric
                        )
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (dataset_name) DO UPDATE SET
                            min_grade = EXCLUDED.min_grade,
                            max_grade = EXCLUDED.max_grade,
                            metric = EXCLUDED.metric
                        RETURNING dataset_id
                        """,
                        (
                            definition.dataset_name,
                            definition.min_grade,
                            definition.max_grade,
                            definition.metric,
                        ),
                    )
                    dataset_row = cursor.fetchone()
                    if dataset_row is None:
                        raise RuntimeError("PostgreSQL did not return the dataset id")
                    dataset_id = dataset_row[0]

                    cursor.execute(
                        "DELETE FROM queries WHERE dataset_id = %s", (dataset_id,)
                    )
                    cursor.execute(
                        """
                        CREATE TEMP TABLE judgment_stage (
                            source_query_id TEXT NOT NULL,
                            split TEXT,
                            keywords TEXT NOT NULL,
                            metadata JSONB,
                            doc_id TEXT NOT NULL,
                            grade INTEGER NOT NULL
                        ) ON COMMIT DROP
                        """
                    )

                    copied_rows = self._copy_records(
                        cursor, records, definition, batch_size
                    )
                    if copied_rows == 0:
                        raise ValueError(
                            f"No judgments were supplied for {definition.dataset_name}"
                        )

                    cursor.execute(
                        """
                        SELECT source_query_id
                        FROM judgment_stage
                        GROUP BY source_query_id
                        HAVING COUNT(DISTINCT (split, keywords, metadata)) > 1
                        LIMIT 1
                        """
                    )
                    conflicting_query = cursor.fetchone()
                    if conflicting_query is not None:
                        raise ValueError(
                            "Conflicting query text, split, or metadata for source "
                            f"query id {conflicting_query[0]}"
                        )

                    cursor.execute(
                        """
                        SELECT source_query_id, doc_id
                        FROM judgment_stage
                        GROUP BY source_query_id, doc_id
                        HAVING COUNT(DISTINCT grade) > 1
                        LIMIT 1
                        """
                    )
                    conflicting_grade = cursor.fetchone()
                    if conflicting_grade is not None:
                        raise ValueError(
                            "Conflicting grades for source query/document pair "
                            f"({conflicting_grade[0]}, {conflicting_grade[1]})"
                        )

                    cursor.execute(
                        """
                        INSERT INTO queries (
                            source_query_id, split, dataset_id, keywords, metadata
                        )
                        SELECT source_query_id, split, %s, keywords, metadata
                        FROM judgment_stage
                        GROUP BY source_query_id, split, keywords, metadata
                        """,
                        (dataset_id,),
                    )
                    query_count = cursor.rowcount

                    cursor.execute(
                        """
                        INSERT INTO judgments (query_id, doc_id, grade)
                        SELECT DISTINCT q.query_id, stage.doc_id, stage.grade
                        FROM judgment_stage AS stage
                        JOIN queries AS q
                          ON q.dataset_id = %s
                         AND q.source_query_id = stage.source_query_id
                        ON CONFLICT (query_id, doc_id) DO NOTHING
                        """,
                        (dataset_id,),
                    )
                    judgment_count = cursor.rowcount

        return DatasetLoadResult(
            dataset_name=definition.dataset_name,
            query_count=query_count,
            judgment_count=judgment_count,
        )

    @staticmethod
    def _copy_records(
        cursor: Any,
        records: Iterable[JudgmentRecord],
        definition: DatasetDefinition,
        batch_size: int,
    ) -> int:
        copy_statement = """
            COPY judgment_stage (
                source_query_id, split, keywords, metadata, doc_id, grade
            ) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '')
        """
        batch: list[JudgmentRecord] = []
        copied_rows = 0
        for record in records:
            if not definition.min_grade <= record.grade <= definition.max_grade:
                raise ValueError(
                    f"Grade {record.grade} is outside the allowed range "
                    f"[{definition.min_grade}, {definition.max_grade}] for "
                    f"{definition.dataset_name}"
                )
            batch.append(record)
            if len(batch) == batch_size:
                JudgmentsDB._copy_batch(cursor, copy_statement, batch)
                copied_rows += len(batch)
                batch.clear()
        if batch:
            JudgmentsDB._copy_batch(cursor, copy_statement, batch)
            copied_rows += len(batch)
        return copied_rows

    @staticmethod
    def _copy_batch(
        cursor: Any, copy_statement: str, records: list[JudgmentRecord]
    ) -> None:
        buffer = StringIO()
        writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
        for record in records:
            writer.writerow(
                (
                    record.source_query_id,
                    record.split or "",
                    record.keywords,
                    json.dumps(record.metadata, ensure_ascii=False)
                    if record.metadata is not None
                    else "",
                    record.doc_id,
                    record.grade,
                )
            )
        buffer.seek(0)
        cursor.copy_expert(copy_statement, buffer)
