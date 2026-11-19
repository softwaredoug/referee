"""CLI frontend for loading cheat-at-search judgments."""

import argparse
import json
from dataclasses import asdict

import psycopg2

from referee.judgments.controller import DATASETS, LoadJudgmentsController
from referee.judgments.db import JudgmentsDB
from referee.judgments.models import LoadJudgmentsTask


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk load cheat-at-search judgments into PostgreSQL"
    )
    parser.add_argument("--dataset_name", choices=sorted(DATASETS))
    args = parser.parse_args()

    try:
        controller = LoadJudgmentsController(JudgmentsDB())
        result = controller.load_judgments(
            LoadJudgmentsTask(dataset_name=args.dataset_name)
        )
    except (ImportError, ValueError, psycopg2.Error) as error:
        parser.error(str(error))

    print(json.dumps(asdict(result)))
