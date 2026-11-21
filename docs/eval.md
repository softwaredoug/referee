# Evaluating tasks flow

Refer to docs/session.md for context about how splits are created, and how they can be used
to access sets of queries.

In this document, we'll discuss eval flows. It'll involve several distinct API / CLI calls, but
all within one subsystem (ie controller + database module) called "eval".

The REST API exposes the same task lifecycle as `POST /v1/tasks` and
`POST /v1/tasks/{task_id}/complete`. For an end-to-end orchestrator and subagent
example, see [the API consumer workflow](api.md#consumer-workflow-orchestrator-and-subagents).

## Start an eval task

Starting an eval task assigns work to the caller, in the form of a set of queries for 
the caller to process, and return as search results.

A bearer token is provided and queries and their metadata 
are returned. A task is also returned.

### CLI

Assuming a session is created

```sh
uv run create-task \
  --bearer_token abc123
```

Response includes all queries in the split associated with the bearer token (using the salt based
sorting technique mentioned in session.md).

```json
{
  "dataset_name": "esci",
  "task": {
    "id": "abcd1234",
    "eval_mode": "ndcg"
  },
  "queries": [
    {
      "query_id": "q1",
      "query_text": "red sweater",
      "metadata": {"locale": "en-US"}
    },
    {
      "query_id": "q2",
      "query_text": "purple couch",
      "metadata": {"locale": "en-US"}
    },
    {
      "query_id": "q3",
      "query_text": "wireless mouse",
      "metadata": {"locale": "en-US"}
    }
  ]

}
```

A task is created. Repeat tasks can be created for the same bearer token, and many
can exist simultaneously.


### Task table

The creation of a task creates a row in the tasks table in the database:

| id | task_id  | session_split_id | created_at | last_modified_at | complete | 
|----|----------|------------------|------------|------------------| -----|
| 0  | abcd1234 | 1                | 2024-01-01 | 2024-01-01       | true | 
| 1  | efgh1234 | 2                | 2024-01-01 | 2024-01-01       | false|

Here:

- id is the primary key, auto incrementing
- task_id is a unique string identifier for the task
- session_split_id is a foreign key to the session_splits table.
- created_at is the timestamp of when the task was created
- last_modified_at is the timestamp of when the task was last modified
- complete is a boolean indicating whether the task has been completed

## Receive results of eval task

Now with a live task (completed=false) we will receive back from the caller the 
results of an eval task. Basically, search results.


```sh
uv run complete-task \
  --bearer_token abc123 \
  --task_id abcd1234 \
  --results results.csv
```

Both bearer token and task ID are required. The bearer token must belong to the
split associated with the task.

Where results.csv is a CSV file with the following format at a minimum

```
query_id,doc_id,rank,score
q1,doc123,1,0.9
q1,doc456,2,0.8
q2,doc789,1,0.95
...
```

Every query in the task must be represented by at least one row, and every
submitted query ID must belong to the task. For a query with results, ranks are
positive integers starting at 1, with no gaps or ties; duplicate documents for
the same query are invalid. A query with no results is represented by exactly
one sentinel row with `doc_id=-1`, `rank=-1`, and `score=-1`. It cannot have
other result rows. The sentinel is the only case where rank may be negative.

```
query_id,doc_id,rank,score
q1,doc123,1,0.9
q1,doc456,2,0.8
q2,doc789,1,0.95
q3,-1,-1,-1
...
```

Additional optional metadata columns can be appended, such as title, description,
or an image URL. They are accepted but are not used by NDCG or MRR. The `score`
column is required but is also not used by these metrics; submitted rank
determines result order.


```
query_id,doc_id,rank,score,title,description,image_url
q1,doc123,1,0.9,red shoe, this is a red shoe, https://example.com/red_shoe.jpg
q1,doc456,2,0.8,blue shoe, this is a blue shoe, https://example.com/blue_shoe.jpg
q2,doc789,1,0.95,purple dress, this is a purple dress, https://example.com/purple_dress.jpg
...
```

Completing the task returns the metric selected when the session was created.
For NDCG, a query with the no-results sentinel has an NDCG of zero, provided
that query has a non-zero ideal DCG. For MRR, a query with no retrieved relevant
results has an MRR of zero. The task metric is the arithmetic mean of the
per-query metrics across all queries in the task. If an NDCG task contains a
query with zero ideal DCG, NDCG cannot be computed and completion fails.

```json
{
  "task_id": "abcd1234",
  "metrics": {
    "ndcg": 0.5667
  },
  "queries": [
    {
      "query_id": "q1",
      "query_text": "red sweater",
      "ndcg": 0.9
    },
    {
      "query_id": "q2",
      "query_text": "purple couch",
      "ndcg": 0.8
    },
    {
      "query_id": "q3",
      "query_text": "wireless mouse",
      "ndcg": 0.0
    }
  ]
}
```

A valid CSV is accepted once and marks the task complete. If the CSV is invalid
or the selected metric cannot be computed, completion returns a failure and the
task remains incomplete so the caller can submit a corrected CSV. A completed
task cannot be completed again.

## Debug task

The `debug-queries` command shows the submitted results and relevance grades for
one or more queries in a task. It works before or after task completion. The
correct bearer token for the task is required to prevent data leakage.

```sh
uv run debug-queries \
  --bearer_token abc123 \
  --task_id abcd1234 \
  --results results.csv \
  --query q1
```

The response is a JSON object keyed by query ID. Unjudged documents have
`relevance_grade` 0. A requested query must belong to the task's split and have
at least one row in the results CSV.

```json
{
  "queries": {
    "q1": {
      "query_id": "q1",
      "query_text": "red sweater",
      "results": [
        {
          "doc_id": "doc123",
          "rank": 1,
          "score": 0.9,
          "relevance_grade": 1
        },
        {
          "doc_id": "doc456",
          "rank": 2,
          "score": 0.8,
          "relevance_grade": 0
        }
      ]
    }
  }
}
```

Pass multiple query IDs to inspect more than one query. The response includes
only those queries; it does not calculate an aggregate metric.

```sh
uv run debug-queries \
  --bearer_token abc123 \
  --task_id abcd1234 \
  --results results.csv \
  --query q1 q2
```

Add `--target` to include the ideal target for each query. For judgment-based
evaluation modes, this is up to 10 judged documents, sorted by relevance grade
descending and then by `doc_id` ascending.

```sh
uv run debug-queries \
  --bearer_token abc123 \
  --task_id abcd1234 \
  --results results.csv \
  --query q1 \
  --target
```

With `--target`, each query also contains a `target` list:

```json
{
  "queries": {
    "q1": {
      "query_id": "q1",
      "query_text": "red sweater",
      "results": [
        {
          "doc_id": "doc123",
          "rank": 1,
          "score": 0.9,
          "relevance_grade": 4
        }
      ],
      "target": [
        {"doc_id": "doc123", "relevance_grade": 4},
        {"doc_id": "doc789", "relevance_grade": 4}
      ]
    }
  }
}
```

## Eval modes

### NDCG + MRR (classic evals)

Sessions define eval modes when created (ie ndcg or mrr). We want to 
use the classic definition of these metrics as one might find in a BEIR dataset. 
With the following assumptions

- unlabeled results are considered irrelevant
- ideal DCG computed from the judgments for a query, sorted by grade, descending,
  then DCG computed from the submitted results of the query sorted by rank ascending
- NDCG is computed at a depth of 10, and MRR is computed at a depth of 10 as well.
- NDCG uses the BEIR/pytrec_eval `ndcg_cut.10` convention: the relevance grade is
  the gain, discounted by `log2(rank + 1)`; it does not use exponential gains.
- A positive judgment grade is relevant for MRR.
