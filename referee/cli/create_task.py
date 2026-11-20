"""CLI frontend for creating an evaluation task."""

import argparse
from dataclasses import asdict
import json

import psycopg2

from referee.eval.controller import EvalController
from referee.eval.db import EvalDB
from referee.eval.models import CreateTaskTask


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a referee evaluation task")
    parser.add_argument("--bearer_token", required=True)
    args = parser.parse_args()

    try:
        controller = EvalController(EvalDB())
        result = controller.create_task(CreateTaskTask(bearer_token=args.bearer_token))
    except (ValueError, psycopg2.Error) as error:
        parser.error(str(error))

    print(json.dumps(asdict(result)))
