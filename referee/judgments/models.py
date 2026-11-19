"""Structured data types for judgment imports."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetDefinition:
    """Metadata and grade bounds for a supported dataset."""

    dataset_name: str
    min_grade: int
    max_grade: int
    metric: str


@dataclass(frozen=True)
class JudgmentRecord:
    """One flattened source judgment, before query normalization."""

    source_query_id: str
    split: str | None
    keywords: str
    metadata: dict[str, str] | None
    doc_id: str
    grade: int


@dataclass(frozen=True)
class DatasetLoadResult:
    """Counts produced by loading one dataset."""

    dataset_name: str
    query_count: int
    judgment_count: int


@dataclass(frozen=True)
class LoadJudgmentsTask:
    """Select a supported dataset, or all supported datasets, to load."""

    dataset_name: str | None = None


@dataclass(frozen=True)
class LoadJudgmentsResult:
    """Results for a judgment import invocation."""

    datasets: list[DatasetLoadResult]
