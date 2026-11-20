#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname "$script_dir")"
cd "$repo_root"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
: "${DATABASE_URL:?Set DATABASE_URL or configure it in .env}"

session_json="$(uv run create-session \
  --dataset_name doug_blog \
  --eval_mode ndcg \
  --num_queries 10 \
  --seed 42 \
  --splits 0.5 0.5)"
printf 'Created session:\n%s\n' "$session_json"

bearer_token="$(printf '%s' "$session_json" | uv run python -c '
import json
import sys

print(json.load(sys.stdin)["split_tokens"][0])
')"

task_json="$(uv run create-task --bearer_token "$bearer_token")"
printf 'Created task:\n%s\n' "$task_json"

task_id="$(printf '%s' "$task_json" | uv run python -c '
import json
import sys

print(json.load(sys.stdin)["task"]["id"])
')"

results_csv="$(mktemp)"
trap 'rm -f "$results_csv"' EXIT
printf '%s' "$task_json" | uv run python -c '
import csv
import json
import secrets
import sys

task = json.load(sys.stdin)
with open(sys.argv[1], "w", newline="", encoding="utf-8") as results_file:
    writer = csv.writer(results_file)
    writer.writerow(("query_id", "doc_id", "rank", "score"))
    for query in task["queries"]:
        documents = [f"random-{secrets.token_hex(6)}" for _ in range(5)]
        secrets.SystemRandom().shuffle(documents)
        for rank, doc_id in enumerate(documents, start=1):
            writer.writerow((query["query_id"], doc_id, rank, secrets.randbelow(1000) / 1000))
' "$results_csv"
printf 'Created random results CSV with %s rows.\n' \
  "$(($(wc -l < "$results_csv") - 1))"

uv run complete-task \
  --bearer_token "$bearer_token" \
  --task_id "$task_id" \
  --results "$results_csv"
