# API

In addition to the CLI described so far, we also need to implement an
API for the same functionality. Following the same patterns of a thin frontend,
call to the controller, which manipulates the database to accomplish certain
tasks.

In the future, we will also have a CRUD UI to be able to inspect sessions, 
tasks, etc.

## Deployment

We'll wrap up the API app into a docker container in a way that can be executed
and deployed on Fly.

## Routes / functionality

We'll implement a FastAPI API with the following routes. The main documentation
is in the various documentation, as linked from here. Use a versioned `/v1`
prefix and JSON request and response bodies. The API layer should validate and
translate HTTP input into the existing structured controller tasks, then
serialize controller results; it should not duplicate session allocation or
metric business logic.

### `POST /v1/sessions` — create a session

Creates a session and its ordered query splits. No split bearer token is
required to call this route; the generated tokens are returned to the caller
only after the session and splits are successfully created. The request and
response match [Creating a session](session.md#rest-api-shape):

```json
{
  "dataset_name": "msmarco",
  "eval_mode": "ndcg",
  "num_queries": 1000,
  "seed": 42,
  "splits": [0.6, 0.2, 0.2]
}
```

`dataset_name`, `eval_mode`, and `splits` are required. `dataset_name` must be
one of `msmarco`, `esci`, or `doug_blog`; `eval_mode` must be `ndcg` or `mrr`.
`num_queries` is optional and, when supplied, must be a positive integer no
larger than the number of loaded queries in the dataset. If omitted, the full
dataset query pool is used. `seed` is an optional signed 64-bit integer,
defaulting to `42`. `splits` is a non-empty array of positive finite numbers
that sum to `1`; each array element creates one split, in that order.

On success, return `201 Created`:

```json
{
  "split_tokens": ["abc123", "def456", "hij456"]
}
```

The tokens are independent bearer credentials, returned in the same order as
the requested proportions. The creator is responsible for distributing each
token only to the caller assigned that split. The API does not return a session
ID or provide session inspection/update operations in this initial scope.

### `POST /v1/tasks` — create an evaluation task

Create a new task for the split identified by the bearer credential. Send the
token in the standard HTTP authorization header:

```http
Authorization: Bearer abc123
```

There is no request body. Each successful request creates a distinct task; it
is valid to create multiple tasks for the same split. Return `201 Created` with
the dataset, task identifier and metric, and every query assigned to that
split, following [Start an eval task](eval.md#start-an-eval-task):

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
    }
  ]
}
```

The query list is the complete split, in its session-defined order. Each query
contains its public `query_id`, text, and optional metadata. An empty split
cannot produce a task and is reported as a client error.

### `POST /v1/tasks/{task_id}/complete` — submit results and complete a task

Submit results for an existing task using the same split token that created
that task. The request is JSON rather than a file upload; it represents the
structured equivalent of the CLI's required CSV columns (`query_id`, `doc_id`,
`rank`, and `score`):

```http
Authorization: Bearer abc123
Content-Type: application/json
```

```json
{
  "results": [
    {"query_id": "q1", "doc_id": "doc123", "rank": 1, "score": 0.9},
    {"query_id": "q1", "doc_id": "doc456", "rank": 2, "score": 0.8},
    {"query_id": "q2", "doc_id": "-1", "rank": -1, "score": -1}
  ]
}
```

The `task_id` comes from task creation. Every query in that task must have at
least one result row, and every submitted `query_id` must belong to that task.
For queries with results, ranks must be positive, unique, contiguous integers
starting at `1`, and document IDs must not repeat within a query. A query with
no results must have exactly one sentinel row with `doc_id="-1"`, `rank=-1`,
and `score=-1`; it cannot also have result rows. Scores must be finite numbers.
Submitted rank determines result order; `score` is required for input
compatibility but is not used by NDCG or MRR. Metric definitions and additional
evaluation details are in [Evaluating tasks](eval.md#receive-results-of-eval-task).
Optional result-row fields such as `title`, `description`, or `image_url` are
accepted and ignored, matching the CLI's optional CSV metadata columns.

On success, return `200 OK`. The top-level metric name and each per-query metric
key are the session's `eval_mode` (`ndcg` or `mrr`):

```json
{
  "task_id": "abcd1234",
  "metrics": {"ndcg": 0.5667},
  "queries": [
    {
      "query_id": "q1",
      "query_text": "red sweater",
      "ndcg": 0.9
    },
    {
      "query_id": "q2",
      "query_text": "purple couch",
      "ndcg": 0.0
    }
  ]
}
```

The task is marked complete only after results validate and the metric can be
calculated. Invalid results (including an NDCG query with zero ideal DCG) leave
the task incomplete so corrected results can be submitted. A completed task
cannot be completed again.

### `POST /v1/tasks/{task_id}/debug` — inspect selected queries

Use this endpoint to diagnose submitted retrieval results without completing or
changing the task. It accepts incomplete result files and can inspect a task
whether it is still open or already completed. The caller must use the same
split bearer token that owns the task:

```http
Authorization: Bearer abc123
Content-Type: application/json
```

The request identifies one or more queries from the task and supplies the
result rows to inspect. Unlike completion, it does not require rows for every
query in the task. Every requested query must be in the task's split and must
have at least one row in `results`.

```json
{
  "query_ids": ["q1", "q2"],
  "results": [
    {"query_id": "q1", "doc_id": "doc123", "rank": 1, "score": 0.9},
    {"query_id": "q1", "doc_id": "doc456", "rank": 2, "score": 0.8},
    {"query_id": "q2", "doc_id": "-1", "rank": -1, "score": -1}
  ],
  "include_target": true
}
```

`include_target` is optional and defaults to `false`. When true, the response
includes up to 10 judged documents for each query, ordered by relevance grade
descending and then `doc_id` ascending. The target is the ideal judged result
set; it is not part of the caller's submitted results. The endpoint does not
compute an aggregate metric, validate completion requirements, or change task
state. Unjudged submitted documents are returned with relevance grade `0`.

The response is a `queries` object keyed by query ID. Each value contains the
query ID and text, the submitted rows in rank order with relevance grades, and
the optional target. If `include_target` is false, the `target` field is
omitted.

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
        },
        {
          "doc_id": "doc456",
          "rank": 2,
          "score": 0.8,
          "relevance_grade": 0
        }
      ],
      "target": [
        {"doc_id": "doc123", "relevance_grade": 4},
        {"doc_id": "doc789", "relevance_grade": 4}
      ]
    },
    "q2": {
      "query_id": "q2",
      "query_text": "purple couch",
      "results": [
        {
          "doc_id": "-1",
          "rank": -1,
          "score": -1,
          "relevance_grade": 0
        }
      ],
      "target": [
        {"doc_id": "doc999", "relevance_grade": 3}
      ]
    }
  }
}
```

Errors use the standard `{"detail": "..."}` body. `401` means the bearer
credential is missing; `404` means the task is unknown or does not belong to
that token; `422` means the request is malformed, a query is outside the
task's split, or a requested query has no result rows. Database failures use
`503` or `500` as described in [HTTP errors](#http-errors).

## Consumer workflow: orchestrator and subagents

The orchestrator creates a session once, maps each returned split token to the
subagent or run that should use it, and collects each subagent's completion
response. A subagent creates a task for its assigned token, runs retrieval for
all queries in that task, and submits the ranked results. The service allocates
queries and computes metrics; the orchestrator decides what a split means and
how to use the returned scores.

### 1. The orchestrator creates the session

Choose the dataset, metric, query-pool size, and proportions before delegating.
For example, this creates three disjoint splits from a repeatably selected pool
of 1,000 MS MARCO queries:

```sh
export API_BASE_URL="https://referee.example.com"

curl --fail-with-body --silent --show-error \
  -X POST "$API_BASE_URL/v1/sessions" \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_name": "msmarco",
    "eval_mode": "mrr",
    "num_queries": 1000,
    "seed": 42,
    "splits": [0.6, 0.2, 0.2]
  }'
```

The response contains `split_tokens` in request order. The orchestrator should
keep the mapping between each token and its assigned subagent/run; the API does
not return a session ID or expose an endpoint to recover lost tokens. For
example, `split_tokens[0]` identifies the 60% split and the next two tokens
identify the 20% splits. The server makes the query sets disjoint and the
integer sizes sum to the selected pool size. Split ordinals are positional only:
they do not imply training, validation, or holdout roles. Assign those roles
yourself when delegating.

### 2. The orchestrator delegates one token to each subagent

Give each subagent the API base URL and only the split token for its assignment.
The token is a bearer credential. The subagent starts its work by requesting a
task:

```sh
export SPLIT_TOKEN="<token assigned to this subagent>"

curl --fail-with-body --silent --show-error \
  -X POST "$API_BASE_URL/v1/tasks" \
  -H "Authorization: Bearer $SPLIT_TOKEN"
```

There is no request body. The response gives the `task.id`, `eval_mode`,
`dataset_name`, and the complete query list for that split. The subagent should
retain the task ID and use the exact `query_id` values from this response when
submitting results. There is no pagination or separate query-fetch request.

An orchestrator can use an assignment instruction like:

> Work only on the queries returned for your assigned split token. Create one
> task, run the assigned retrieval system for every query, and submit results
> for every query to that task. Preserve each returned `query_id`. Return the
> completion response, including the task ID and metric scores, to the
> orchestrator.

### 3. Each subagent runs retrieval and builds result rows

For every query in the task, run the assigned retriever and produce one row per
returned document. Ranks must start at `1` and be contiguous within each query;
keep document IDs as strings. The `score` is required and must be finite, but
the service orders results by rank and does not use the score to calculate MRR
or NDCG. The metrics evaluate at depth 10. If retrieval returns no documents
for a query, submit the single no-results sentinel row described above. Do not
omit a query, even when it has no results.

The request contains all rows together:

```json
{
  "results": [
    {"query_id": "<query id from task>", "doc_id": "doc-123", "rank": 1, "score": 12.4},
    {"query_id": "<query id from task>", "doc_id": "doc-456", "rank": 2, "score": 10.8},
    {"query_id": "<another query id>", "doc_id": "-1", "rank": -1, "score": -1}
  ]
}
```

### Debugging selected queries

Use the debug endpoint to inspect a subset of a task's retrieval output against
the service's judgments. Debugging uses the same task ID and split token from
task creation, and it can be called at any point: before completion while
investigating a run, after correcting results, or after the task has completed.
It is read-only, so it does not consume the task or prevent a later completion.

For example, save only the rows for the queries being investigated in
`debug.json`:

```json
{
  "query_ids": ["q1", "q2"],
  "results": [
    {"query_id": "q1", "doc_id": "doc123", "rank": 1, "score": 0.9},
    {"query_id": "q1", "doc_id": "doc456", "rank": 2, "score": 0.8},
    {"query_id": "q2", "doc_id": "-1", "rank": -1, "score": -1}
  ],
  "include_target": true
}
```

Call the endpoint with the task ID returned by `POST /v1/tasks` and the same
split token:

```sh
curl --fail-with-body --silent --show-error \
  -X POST "$API_BASE_URL/v1/tasks/$TASK_ID/debug" \
  -H "Authorization: Bearer $SPLIT_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @debug.json
```

Set `include_target` to `true` to compare submitted results with the top 10
judged documents for each query. Targets are ordered by grade descending and
then `doc_id` ascending; they are judgments, not documents retrieved by the
agent. Submitted rows are returned in rank order and annotated with their exact
judgment grade; an unjudged document has grade `0`. Only requested query IDs
are returned. Each requested ID must belong to the task and have at least one
row in the request. You may send only the selected queries' rows—unrelated task
queries are not required for debugging.

The response helps pinpoint whether a miss is due to the retrieval ranking
(compare `results` with `target`) or to a query/result mismatch. It does not
calculate NDCG or MRR and does not enforce the complete-task requirement that
every task query be represented. Use the normal completion endpoint only after
assembling and validating the full result set. The endpoint contract above
describes the response schema and error cases.

### 4. Each subagent submits once and reports the response

Submit the assembled rows with the same split token and the task ID returned
when the task was created:

```sh
export TASK_ID="<task.id returned by POST /v1/tasks>"

curl --fail-with-body --silent --show-error \
  -X POST "$API_BASE_URL/v1/tasks/$TASK_ID/complete" \
  -H "Authorization: Bearer $SPLIT_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @results.json
```

The successful response includes an overall score and a score for each query,
using the session metric name (`mrr` or `ndcg`). The subagent should save and
return this response to the orchestrator. If submission returns `422`, correct
the invalid or incomplete rows and resubmit them to the same task; the task
remains incomplete until a valid completion succeeds.

### 5. The orchestrator collects and interprets results

Collect each task's completion response and associate it with the subagent,
retrieval system, and split assignment. The API has no session-level aggregation
or task-result lookup endpoint, so the orchestrator must retain the responses
and perform any desired aggregation itself. Scores from different split tokens
are computed over different, disjoint queries. For repeated runs on the same
query set, the same split token can create multiple distinct tasks, each with
its own task ID and completion response.

For a direct comparison of multiple retrieval systems on identical queries,
create a session with one split (`"splits": [1.0]`) and give that split token to
each runner. Each runner creates a distinct task but receives the same query set.
For partitioned work, give each runner a different token instead.

### Retry and completion notes

- Each `POST /v1/tasks` creates a new task, even when called repeatedly with the
  same token. A retry after an ambiguous network timeout can therefore create
  an extra task for the same queries.
- Session creation also creates a new session on every request. If its response
  is lost, the generated tokens from that session cannot be recovered; retrying
  creates a different session with different tokens.
- Completion is single-use. Preserve the `200` response: the API does not have
  a route to fetch the saved metric response later. If the connection is lost
  after submission, a retry may receive `409 Conflict` because the first
  submission already completed the task.
- Store split tokens and task IDs in the orchestrator's run state so work can be
  correctly associated and resumed. Do not log tokens or give a subagent
  credentials for other splits.

## HTTP errors

Use a consistent JSON error body, for example `{"detail": "..."}`. Suggested
status mapping for the controller's existing validation outcomes:

| Status | Use |
|--------|-----|
| `401 Unauthorized` | Missing bearer token, or invalid token when creating a task. |
| `404 Not Found` | Task ID is unknown or the token does not own it (including an invalid token); do not reveal which case applies. |
| `409 Conflict` | Attempt to complete an already-completed task. |
| `422 Unprocessable Entity` | Malformed JSON, invalid fields, unknown/unloaded dataset, unavailable query count, or invalid result rows / metric input. |
| `503 Service Unavailable` | Database connection failure or database schema not ready. |
| `500 Internal Server Error` | Unexpected server or database operation error; do not expose connection details. |

FastAPI request-model validation should reject malformed input before invoking
the controller. Controller `ValueError`s should be translated to the
appropriate client status rather than returned as server errors. Do not expose
database credentials, SQL, or other internal details in error responses.

## Out of scope for the initial API

Session/task browsing and general CRUD endpoints are reserved for the future
inspection UI. Judgment dataset loading is an administrative/bootstrap task
covered by [Judgments](judgments.md#loading-script), not a public request route.
The API routes above implement session creation, the eval task lifecycle, and
read-only query debugging; they do not change the underlying controllers'
ownership or completion rules.

## Running and deploying

The FastAPI app is served by Uvicorn on port `8080`. For local Docker Compose
usage, see the [README](../README.md#run-the-api-locally); for Fly deployment,
see [Deploy to Fly](../README.md#deploy-to-fly).
The `/healthz` liveness route does not require PostgreSQL. `/readyz` checks that
PostgreSQL is reachable and the required schema tables exist; it does not load
datasets or create the schema.
