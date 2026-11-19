# Running and writing tests

## Test approach

The main behavioral tests exercise a subsystem through its controller using the
structured task dataclass, then verify the resulting behavior and persisted state.
For example, session tests call `CreateSessionController.create_session` with a
`CreateSessionTask`. They use a real PostgreSQL database; they do not mock
PostgreSQL.

Use unit tests for pure functions and validation where they clarify individual
behavior. CLI tests should stay focused on the thin frontend—for example, that
required arguments are enforced and parsed into the task. The CLI is not the
primary path for end-to-end subsystem tests.

Mock only costly external API boundaries when needed. Keep tests behavioral and
name them for the requirement they verify.

## Database setup

PostgreSQL tests require a database with the current schema and the judgment
datasets loaded. The tests connect using `TEST_DATABASE_URL`.

For local development, `.env.example` configures the local Docker PostgreSQL
service. Copy it to `.env`, then bootstrap the database when needed:

```sh
cp .env.example .env
make db-bootstrap
```

**`make db-bootstrap` permanently drops and recreates the database named by
`DATABASE_URL`, applies `database/0001_initial_schema.sql`, and loads the
datasets. Use it only for a disposable local database.** Make sure
`TEST_DATABASE_URL` points to the intended test database as well.

## Running checks

Use Python 3.15.2 via asdf and `uv`:

```sh
uv sync
uv run flake8 referee tests
uv run pyright
uv run --group judgments-loader --env-file .env pytest
```

To run just the session tests:

```sh
uv run --env-file .env pytest tests/test_session.py
```

The PostgreSQL tests require the database to be available and bootstrapped; they
create and clean up their test records. The judgment-loader dependency group is
needed for the full test suite because it includes a real small-dataset loading
test.

## Controller e2e test pattern

Pass the structured task directly to the controller and inject a `SessionDB`
connected to the test database:

```python
controller = CreateSessionController(SessionDB(test_database_url))
result = controller.create_session(
    CreateSessionTask(
        dataset_name="doug_blog",
        eval_mode="ndcg",
        splits=(0.6, 0.2, 0.2),
        num_queries=100,
        seed=42,
    )
)
```

Assert the returned split tokens and observe the session and split rows through
PostgreSQL. Include behavioral coverage for defaults as well as explicit inputs;
for session creation, omitting `num_queries` selects the full query set and
omitting `seed` uses `42`.
