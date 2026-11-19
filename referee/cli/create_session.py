"""CLI frontend for creating evaluation sessions."""

import argparse
import json
from dataclasses import asdict

import psycopg2

from referee.session.controller import (
    CreateSessionController,
    CreateSessionTask,
)
from referee.session.db import SessionDB


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a referee evaluation session")
    parser.add_argument("--dataset_name", required=True)
    parser.add_argument("--eval_mode", required=True)
    parser.add_argument("--training_key_count", type=int, default=1)
    args = parser.parse_args()

    task = CreateSessionTask(
        dataset_name=args.dataset_name,
        eval_mode=args.eval_mode,
        training_key_count=args.training_key_count,
    )
    try:
        controller = CreateSessionController(SessionDB())
        result = controller.create_session(task)
    except (ValueError, psycopg2.Error) as error:
        parser.error(str(error))

    print(json.dumps(asdict(result)))
