# Creating a session and its query splits

A session defines a query pool for a dataset and partitions that pool into one or
more disjoint splits. Splits have no built-in holdout or training role. The
orchestrator receives a bearer token for each split and decides how to distribute
those tokens.

## Creating a session

The creator supplies:

- `dataset_name`: the dataset to use.
- `eval_mode`: the evaluation mode, either `ndcg` or `mrr`.
- `num_queries`: the number of queries to select. If omitted, use all queries in
  the dataset.
- `seed`: controls repeatable selection of the overall query pool. It defaults
  to `42`.
- `splits`: a required, ordered list of positive proportions that sum to `1`.
  Each proportion creates one split, in list order.

For example, `--splits 0.6 0.2 0.2` creates three splits; `--splits 0.5 0.5`
creates two. The ordinal is positional only and does not imply a split role.

The server creates a random per-session `sort_salt`. It selects the overall
query pool deterministically from stable query identities and the user seed,
then sorts that pool by a hash of the session salt and query identity. It
partitions the sorted queries according to the requested proportions. Integer
split sizes use the largest-remainder rule, with ties assigned to the earlier
ordinal, so the split sizes always sum to the pool size.

If `num_queries` exceeds the number of queries in the dataset, session creation
fails. If omitted, the database stores `NULL` and the full query set is used.

### Session table

One row stores the information needed to reproduce the session's overall query
pool and ordering.

| session_id | dataset_name | eval_mode | num_queries | user_seed | sort_salt | created_at | last_used_at |
|------------|--------------|-----------|-------------|-----------|-----------|------------|--------------|
| 1          | msmarco      | ndcg      | 1000        | 42        | …         | 2024-01-01 | NULL         |

`sort_salt` is generated independently for each session and is only used by the
service. No global allocation key is required.

### Session splits table

Each row associates a bearer token with one split of a session.

| session_split_id | bearer_token | session_id | proportion | ordinal | created_at | last_used_at |
|------------------|--------------|------------|------------|---------|------------|--------------|
| 1                | abc123       | 1          | 0.6        | 1       | 2024-01-01 | NULL         |
| 2                | def456       | 1          | 0.2        | 2       | 2024-01-01 | NULL         |
| 3                | hij456       | 1          | 0.2        | 3       | 2024-01-01 | NULL         |

The token identifies the split. `ordinal` determines the split's position in the
sorted query pool; proportions across a session must sum to `1`.

Session and split rows are inserted atomically. The creator receives tokens in
ordinal order:

```json
{
  "split_tokens": ["abc123", "def456", "hij456"]
}
```

## CLI

```sh
uv run create-session \
  --dataset_name msmarco \
  --eval_mode ndcg \
  --num_queries 1000 \
  --seed 42 \
  --splits 0.6 0.2 0.2
```

`--splits` is mandatory. The output is JSON with `split_tokens` in the same
order as the supplied proportions.

## REST API shape

The corresponding creation request is:

```json
{
  "dataset_name": "msmarco",
  "eval_mode": "ndcg",
  "num_queries": 1000,
  "seed": 42,
  "splits": [0.6, 0.2, 0.2]
}
```

The implemented `POST /v1/sessions` API returns the same `split_tokens`
response as the CLI. See [the API consumer workflow](api.md#consumer-workflow-orchestrator-and-subagents)
for how an orchestrator maps those tokens to subagents.

## Security scope

The orchestrator keeps tokens it does not intend to distribute and gives each
subagent only the token for its assigned split. Tokens are independent random
bearer credentials; they do not encode split ordinals or proportions. The
session salt is stored server-side to make the ordering difficult to predict
from the public seed alone. This design assumes subagents access splits through
the service rather than directly reading the database.
