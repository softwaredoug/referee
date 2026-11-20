"""Benchmark task creation and completion over a reproducible ESCI sample."""

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import random
import tempfile
from time import perf_counter

import psycopg2

from referee.cli.complete_task import read_results_csv
from referee.eval.controller import EvalController
from referee.eval.db import EvalDB
from referee.eval.models import (
    CompleteTaskTask,
    CreateTaskTask,
    EvalQuery,
    SubmittedResult,
)
from referee.session.controller import CreateSessionController, CreateSessionTask
from referee.session.db import SessionDB


@dataclass(frozen=True)
class EvalBenchmarkResult:
    """Timing and result summary for a single evaluation benchmark run."""

    query_count: int
    result_row_count: int
    session_creation_seconds: float
    task_creation_seconds: float
    completion_seconds: float
    metric_name: str
    metric_score: float
    phase_timings: dict[str, float]
    phase_counts: dict[str, int]


def benchmark_esci_eval(
    database_url: str | None = None,
    *,
    query_count: int = 100,
    seed: int = 42,
    shuffle_seed: int = 137,
    results_csv: Path | None = None,
) -> EvalBenchmarkResult:
    """Create a session/task, shuffle judged documents, and time completion.

    The completion timer covers the controller call, including its database
    reads, result validation, metric calculation, and completion update. CSV
    creation and parsing are outside that timing.
    """
    resolved_database_url = (
        database_url
        or os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not resolved_database_url:
        raise ValueError("TEST_DATABASE_URL or DATABASE_URL must be set")
    if query_count != 100:
        raise ValueError("This benchmark is defined for exactly 100 queries")

    session_started = perf_counter()
    session_result = CreateSessionController(
        SessionDB(resolved_database_url)
    ).create_session(
        CreateSessionTask(
            dataset_name="esci",
            eval_mode="ndcg",
            num_queries=query_count,
            seed=seed,
            splits=(1.0,),
        )
    )
    session_creation_seconds = perf_counter() - session_started
    bearer_token = session_result.split_tokens[0]

    try:
        phase_timings: dict[str, float] = {}
        phase_counts: dict[str, int] = {}

        def record_timing(name: str, duration: float) -> None:
            phase_timings[name] = phase_timings.get(name, 0.0) + duration
            phase_counts[name] = phase_counts.get(name, 0) + 1

        eval_db = EvalDB(resolved_database_url, timing_probe=record_timing)
        controller = EvalController(eval_db, timing_probe=record_timing)

        task_started = perf_counter()
        created_task = controller.create_task(CreateTaskTask(bearer_token))
        task_creation_seconds = perf_counter() - task_started
        if len(created_task.queries) != query_count:
            raise RuntimeError(
                f"Expected {query_count} queries, got {len(created_task.queries)}"
            )

        query_ids = [int(query.query_id) for query in created_task.queries]
        qrels_started = perf_counter()
        judgments = eval_db.get_judgments(query_ids)
        phase_timings["benchmark.load_judgments_for_csv"] = (
            perf_counter() - qrels_started
        )
        phase_counts["benchmark.load_judgments_for_csv"] = 1

        if results_csv is None:
            with tempfile.TemporaryDirectory(prefix="esci-eval-benchmark-") as temp_dir:
                csv_path = Path(temp_dir) / "results.csv"
                result_row_count, submitted_results = _prepare_results_csv(
                    csv_path,
                    created_task.queries,
                    judgments,
                    random.Random(shuffle_seed),
                    phase_timings,
                    phase_counts,
                )
                completion_started = perf_counter()
                completion = controller.complete_task(
                    CompleteTaskTask(
                        bearer_token=bearer_token,
                        task_id=created_task.task.id,
                        results=submitted_results,
                    )
                )
                completion_seconds = perf_counter() - completion_started
        else:
            results_csv.parent.mkdir(parents=True, exist_ok=True)
            result_row_count, submitted_results = _prepare_results_csv(
                results_csv,
                created_task.queries,
                judgments,
                random.Random(shuffle_seed),
                phase_timings,
                phase_counts,
            )
            completion_started = perf_counter()
            completion = controller.complete_task(
                CompleteTaskTask(
                    bearer_token=bearer_token,
                    task_id=created_task.task.id,
                    results=submitted_results,
                )
            )
            completion_seconds = perf_counter() - completion_started

        return EvalBenchmarkResult(
            query_count=query_count,
            result_row_count=result_row_count,
            session_creation_seconds=session_creation_seconds,
            task_creation_seconds=task_creation_seconds,
            completion_seconds=completion_seconds,
            metric_name=completion.metric_name,
            metric_score=completion.metric_score,
            phase_timings=phase_timings,
            phase_counts=phase_counts,
        )
    finally:
        _delete_session(resolved_database_url, bearer_token)


def _write_shuffled_results(
    path: Path,
    queries: list[EvalQuery],
    judgments: dict[int, dict[str, int]],
    randomizer: random.Random,
) -> int:
    """Write all judgments in random rank order for every query."""
    row_count = 0
    with path.open("w", newline="", encoding="utf-8") as results_file:
        writer = csv.writer(results_file)
        writer.writerow(("query_id", "doc_id", "rank", "score"))
        for query in queries:
            query_id = int(query.query_id)
            query_judgments = judgments[query_id]
            if not any(grade > 0 for grade in query_judgments.values()):
                raise ValueError(
                    f"ESCI query {query.query_id} has no positive judgments"
                )
            doc_ids = list(query_judgments)
            randomizer.shuffle(doc_ids)
            for rank, doc_id in enumerate(doc_ids, start=1):
                writer.writerow((query.query_id, doc_id, rank, 1.0 / rank))
                row_count += 1
    return row_count


def _prepare_results_csv(
    path: Path,
    queries: list[EvalQuery],
    judgments: dict[int, dict[str, int]],
    randomizer: random.Random,
    phase_timings: dict[str, float],
    phase_counts: dict[str, int],
) -> tuple[int, list[SubmittedResult]]:
    """Write and parse the benchmark CSV, recording both frontend phases."""
    started = perf_counter()
    row_count = _write_shuffled_results(path, queries, judgments, randomizer)
    phase_timings["benchmark.write_csv"] = perf_counter() - started
    phase_counts["benchmark.write_csv"] = 1

    started = perf_counter()
    submitted_results = read_results_csv(path)
    phase_timings["benchmark.parse_csv"] = perf_counter() - started
    phase_counts["benchmark.parse_csv"] = 1
    return row_count, submitted_results


def _delete_session(database_url: str, bearer_token: str) -> None:
    """Delete benchmark session and its tasks after measuring."""
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM sessions
                    WHERE session_id = (
                        SELECT session_id
                        FROM session_splits
                        WHERE bearer_token = %s
                    )
                    """,
                    (bearer_token,),
                )
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark eval completion for 100 ESCI queries"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--shuffle_seed", type=int, default=137)
    parser.add_argument("--results_csv", type=Path)
    args = parser.parse_args()

    try:
        result = benchmark_esci_eval(
            seed=args.seed,
            shuffle_seed=args.shuffle_seed,
            results_csv=args.results_csv,
        )
    except (ValueError, psycopg2.Error) as error:
        parser.error(str(error))

    print(json.dumps(asdict(result), indent=2))
