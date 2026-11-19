"""Judgment loading use case."""

from collections.abc import Callable, Iterable, Mapping

from referee.judgments.db import JudgmentsDB
from referee.judgments.models import (
    DatasetDefinition,
    DatasetLoadResult,
    JudgmentRecord,
    LoadJudgmentsResult,
    LoadJudgmentsTask,
)
from referee.judgments.source import load_source_records

DATASETS = {
    "msmarco": DatasetDefinition(
        dataset_name="msmarco", min_grade=0, max_grade=1, metric="mrr"
    ),
    "esci": DatasetDefinition(
        dataset_name="esci", min_grade=0, max_grade=3, metric="ndcg"
    ),
    "doug_blog": DatasetDefinition(
        dataset_name="doug_blog", min_grade=0, max_grade=1, metric="mrr"
    ),
}

SourceLoader = Callable[[str], Iterable[JudgmentRecord]]


class LoadJudgmentsController:
    """Load the selected cheat-at-search judgments into PostgreSQL."""

    def __init__(
        self,
        judgments_db: JudgmentsDB,
        source_loader: SourceLoader = load_source_records,
        dataset_definitions: Mapping[str, DatasetDefinition] | None = None,
    ) -> None:
        self._judgments_db = judgments_db
        self._source_loader = source_loader
        self._dataset_definitions = (
            dataset_definitions if dataset_definitions is not None else DATASETS
        )

    def load_judgments(self, task: LoadJudgmentsTask) -> LoadJudgmentsResult:
        if (
            task.dataset_name is not None
            and task.dataset_name not in self._dataset_definitions
        ):
            allowed = ", ".join(sorted(self._dataset_definitions))
            raise ValueError(f"dataset_name must be one of: {allowed}")

        dataset_names = (
            [task.dataset_name]
            if task.dataset_name is not None
            else sorted(self._dataset_definitions)
        )
        results: list[DatasetLoadResult] = []
        for dataset_name in dataset_names:
            definition = self._dataset_definitions[dataset_name]
            results.append(
                self._judgments_db.replace_dataset(
                    definition, self._source_loader(dataset_name)
                )
            )
        return LoadJudgmentsResult(datasets=results)
