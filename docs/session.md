## Creating a session

In this subsystem, we're creating an evaluation session.

A session contains
- A holdout key: a secure token that allows access to holdout queries for evaluation
- One or more training keys: secure tokens that allow access to training queries for model development


## Flow

### Create session

An outer orchestrator agent calls this service to create a session. The orchestrator calls with

- A dataset name (a unique string like msmarco, wands, etc)
- eval mode: ie ndcg, etc (see below for eval modes)

In return, its assigned 

- A secure holdout token: intended to be used in future eval calls by orchestrator to access
  holdout queries to run.
- One or more training tokens: intended to give access to a subset of queries for training purposes

### Session keys table

A session keys table defines the sessions that exist, one row per key (holdout vs training).

| session_key_id | key_type | key_value | dataset_name | eval_mode | created_at | last_used_at | parent_key |
|----------------|----------|-----------|--------------|-----------|------------| -------------|-----------|
| 1              | holdout  | abc123    | msmarco      | ndcg      | 2024-01-01 | 2025-01-01   | NULL       |
| 2              | training | def456    | msmarco      | ndcg      | 2024-01-01 | 2025-01-01   | 1          |

Notice the schema

- session_key_id holds an auto-incremnting primary key for the table
- key_type is either holdout or training
- key_value is a secure token that is used to access the queries from the client and 
  to salt the random process that separates training and holdout queries
- dataset_name: the name of the dataset for which this session is created
- eval_mode: the evaluation mode for this session (e.g., ndcg)
- created_at: timestamp of when the session key was created
- last_used_at: timestamp of when the session key was last used
- parent_key: for training keys, this points to the holdout key that it is associated with. For holdout keys, this is NULL.


### REST API creation

Creating a session key is done through the following REST call:

```
POST /api/v1/sessions
{
  "dataset_name": "msmarco",
  "eval_mode": "ndcg"
}
```

And response is:

```
{
  "holdout_key": "abc123",
  "training_keys": ["def456"]
}
```

### CLI creation

The same process can be performed through the CLI:

```bash
uv run create-session --dataset_name msmarco --eval_mode ndcg
```

Which returns the same JSON as above.


### Session keys as hashes / salts

The session keys act as a hash into a random process that separates training and holdout queries. 

The keys are generated in a way that they are unique and secure, ensuring that the training and holdout
datasets remain distinct and protected.


## Allowed datasets

Currently allow `msmarco`, `esci`, and `doug_blog` datasets.

## Eval modes

Currently NDCG as defined in the cheat-at-search library
