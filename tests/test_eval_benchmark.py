"""Latency benchmark coverage for a 100-query ESCI evaluation."""

import pytest

from referee.eval.benchmark import benchmark_esci_eval


def test_esci_100_query_eval_latency(record_property: pytest.RecordProperty) -> None:
    result = benchmark_esci_eval()

    record_property(
        "esci_100_query_task_creation_seconds", result.task_creation_seconds
    )
    record_property("esci_100_query_completion_seconds", result.completion_seconds)
    for phase, seconds in result.phase_timings.items():
        record_property(f"esci_100_query_{phase}_seconds", seconds)
    print(
        "ESCI 100-query benchmark: "
        f"create_task={result.task_creation_seconds:.4f}s, "
        f"complete_task={result.completion_seconds:.4f}s, "
        f"rows={result.result_row_count}, "
        f"{result.metric_name}={result.metric_score:.5f}"
    )
    for phase, seconds in sorted(
        result.phase_timings.items(), key=lambda item: item[1], reverse=True
    ):
        count = result.phase_counts[phase]
        average = seconds / count
        print(
            f"  {phase}: total={seconds:.4f}s, calls={count}, "
            f"mean={average:.4f}s"
        )

    assert result.query_count == 100
    assert result.result_row_count >= 100
    assert result.metric_name == "ndcg"
    assert 0.0 <= result.metric_score <= 1.0
