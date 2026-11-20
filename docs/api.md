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

## HTTP errors

Use a consistent JSON error body, for example `{"detail": "..."}`. Suggested
status mapping for the controller's existing validation outcomes:

| Status | Use |
|--------|-----|
| `401 Unauthorized` | Missing or invalid bearer token. |
| `404 Not Found` | Task ID is unknown or belongs to a different token; do not reveal which case applies. |
| `409 Conflict` | Attempt to complete an already-completed task. |
| `422 Unprocessable Entity` | Malformed JSON, invalid fields, unknown/unloaded dataset, unavailable query count, or invalid result rows / metric input. |
| `500 Internal Server Error` | Unexpected server error. Database connection failures should be logged and returned without exposing connection details. |

FastAPI request-model validation should reject malformed input before invoking
the controller. Controller `ValueError`s should be translated to the
appropriate client status rather than returned as server errors. Do not expose
database credentials, SQL, or other internal details in error responses.

## Out of scope for the initial API

Session/task browsing and general CRUD endpoints are reserved for the future
inspection UI. Judgment dataset loading is an administrative/bootstrap task
covered by [Judgments](judgments.md#loading-script), not a public request route.
The API routes above implement session creation and the eval task lifecycle;
they do not change the underlying controllers' ownership or completion rules.
