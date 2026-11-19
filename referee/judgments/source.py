"""Adapters from cheat-at-search dataframes to normalized source records."""

from collections.abc import Iterator
from importlib import import_module
from math import isnan
from typing import Any, cast

from referee.judgments.models import JudgmentRecord


def load_source_records(dataset_name: str) -> Iterator[JudgmentRecord]:
    """Load a supported cheat-at-search judgments dataframe and adapt its rows."""
    module_name = {
        "msmarco": "cheat_at_search.msmarco_data",
        "esci": "cheat_at_search.esci_data",
        "doug_blog": "cheat_at_search.doug_blog_data",
    }.get(dataset_name)
    if module_name is None:
        raise ValueError(f"Unsupported dataset: {dataset_name}")

    module = import_module(module_name)
    dataframe = getattr(module, "judgments")
    columns = {str(column): index for index, column in enumerate(dataframe.columns)}
    required_columns = {"query_id", "query", "doc_id", "grade"}
    missing_columns = required_columns - columns.keys()
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(
            f"{dataset_name} judgments dataframe is missing columns: {missing}"
        )

    if dataset_name == "esci":
        esci_columns = {"split", "product_locale"}
        missing_esci_columns = esci_columns - columns.keys()
        if missing_esci_columns:
            missing = ", ".join(sorted(missing_esci_columns))
            raise ValueError(
                f"esci judgments dataframe is missing columns: {missing}"
            )

    for row in dataframe.itertuples(index=False, name=None):
        values = cast(tuple[Any, ...], row)
        source_query_id = _required_text(
            values[columns["query_id"]], "source_query_id"
        )
        keywords = _required_text(values[columns["query"]], "query")
        doc_id = _required_text(values[columns["doc_id"]], "doc_id")
        grade = int(values[columns["grade"]])

        if dataset_name == "msmarco":
            # cheat-at-search's exported `judgments` attribute selects dev.small.
            split = "dev"
            metadata = None
        elif dataset_name == "esci":
            split = _required_text(values[columns["split"]], "split")
            locale = _required_text(values[columns["product_locale"]], "locale")
            metadata = {"locale": locale}
        else:
            split = None
            metadata = None

        yield JudgmentRecord(
            source_query_id=source_query_id,
            split=split,
            keywords=keywords,
            metadata=metadata,
            doc_id=doc_id,
            grade=grade,
        )


def _required_text(value: Any, field_name: str) -> str:
    if value is None or (isinstance(value, float) and isnan(value)):
        raise ValueError(f"{field_name} cannot be null in the source dataframe")
    text = str(value)
    if text == "":
        raise ValueError(f"{field_name} cannot be empty in the source dataframe")
    return text
