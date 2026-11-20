"""CLI frontend for submitting results to an evaluation task."""

import argparse
import csv
import json
import math
from pathlib import Path

import psycopg2

from referee.eval.controller import EvalController
from referee.eval.db import EvalDB
from referee.eval.models import (
    CompleteTaskResult,
    CompleteTaskTask,
    SubmittedResult,
)

REQUIRED_COLUMNS = ("query_id", "doc_id", "rank", "score")


def read_results_csv(path: str | Path) -> list[SubmittedResult]:
    """Parse required result columns; extra columns are accepted and ignored."""
    try:
        with Path(path).open(newline="", encoding="utf-8") as results_file:
            reader = csv.DictReader(results_file)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise ValueError("results CSV must have a header row")
            if len(fieldnames) != len(set(fieldnames)):
                raise ValueError("results CSV header contains duplicate columns")
            missing_columns = [
                column for column in REQUIRED_COLUMNS if column not in fieldnames
            ]
            if missing_columns:
                missing = ", ".join(missing_columns)
                raise ValueError(f"results CSV is missing required columns: {missing}")

            results: list[SubmittedResult] = []
            for line_number, row in enumerate(reader, start=2):
                if all(value in (None, "") for value in row.values()):
                    continue
                if None in row:
                    raise ValueError(
                        f"too many fields in results CSV at line {line_number}"
                    )
                query_id = row.get("query_id")
                doc_id = row.get("doc_id")
                rank_text = row.get("rank")
                score_text = row.get("score")
                if not query_id or doc_id is None or rank_text is None:
                    raise ValueError(f"incomplete result row at line {line_number}")
                try:
                    rank = int(rank_text)
                except ValueError as error:
                    raise ValueError(
                        f"rank must be an integer at line {line_number}"
                    ) from error
                try:
                    score = float(score_text) if score_text is not None else math.nan
                except ValueError as error:
                    raise ValueError(
                        f"score must be numeric at line {line_number}"
                    ) from error
                if not math.isfinite(score):
                    raise ValueError(f"score must be finite at line {line_number}")
                results.append(
                    SubmittedResult(
                        query_id=query_id,
                        doc_id=doc_id,
                        rank=rank,
                        score=score,
                    )
                )
            return results
    except csv.Error as error:
        raise ValueError(f"invalid results CSV: {error}") from error
    except OSError as error:
        raise ValueError(f"cannot read results CSV: {error}") from error


def _completion_response(result: CompleteTaskResult) -> dict[str, object]:
    metric_name = result.metric_name
    return {
        "task_id": result.task_id,
        "metrics": {metric_name: result.metric_score},
        "queries": [
            {
                "query_id": query.query_id,
                "query_text": query.query_text,
                metric_name: query.score,
            }
            for query in result.queries
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete a referee evaluation task")
    parser.add_argument("--bearer_token", required=True)
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--results", required=True)
    args = parser.parse_args()

    try:
        results = read_results_csv(args.results)
        controller = EvalController(EvalDB())
        result = controller.complete_task(
            CompleteTaskTask(
                bearer_token=args.bearer_token,
                task_id=args.task_id,
                results=results,
            )
        )
    except (ValueError, psycopg2.Error) as error:
        parser.error(str(error))

    print(json.dumps(_completion_response(result)))
