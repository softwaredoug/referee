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
    parser.add_argument("--num_queries", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--splits", type=float, nargs="+", required=True)
    args = parser.parse_args()

    task = CreateSessionTask(
        dataset_name=args.dataset_name,
        eval_mode=args.eval_mode,
        num_queries=args.num_queries,
        seed=args.seed,
        splits=tuple(args.splits),
    )
    try:
        controller = CreateSessionController(SessionDB())
        result = controller.create_session(task)
    except (ValueError, psycopg2.Error) as error:
        parser.error(str(error))

    print(json.dumps(asdict(result)))
