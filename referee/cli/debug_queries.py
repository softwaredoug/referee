"""CLI frontend for inspecting evaluation task results."""

import argparse
from dataclasses import asdict
import json

import psycopg2

from referee.cli.complete_task import read_results_csv
from referee.eval.controller import EvalController
from referee.eval.db import EvalDB
from referee.eval.models import DebugQueriesResult, DebugQueriesTask


def _debug_response(result: DebugQueriesResult) -> dict[str, object]:
    """Convert the structured result to the documented JSON representation."""
    queries = {
        query_id: {
            key: value
            for key, value in asdict(query).items()
            if key != "target" or value is not None
        }
        for query_id, query in result.queries.items()
    }
    return {"queries": queries}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Debug submitted results for selected evaluation queries"
    )
    parser.add_argument("--bearer_token", required=True)
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument(
        "--query", required=True, nargs="+", dest="query_ids", metavar="QUERY_ID"
    )
    parser.add_argument(
        "--target",
        action="store_true",
        help="include the top 10 judged documents for each query",
    )
    args = parser.parse_args()

    try:
        results = read_results_csv(args.results)
        controller = EvalController(EvalDB())
        debug_result = controller.debug_queries(
            DebugQueriesTask(
                bearer_token=args.bearer_token,
                task_id=args.task_id,
                results=results,
                query_ids=args.query_ids,
                include_target=args.target,
            )
        )
    except (ValueError, psycopg2.Error) as error:
        parser.error(str(error))

    print(json.dumps(_debug_response(debug_result)))
