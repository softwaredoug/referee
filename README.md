# Referee

A service that acts as a referee for search retrieval autoresearch tasks.

## Development setup

This project uses Python 3.15.2 via asdf and uv for environment and dependency
management.

```sh
uv sync
cp .env.example .env
make db-bootstrap
```

`make db-bootstrap` starts PostgreSQL, asks for confirmation, drops and
recreates the database named in `DATABASE_URL`, applies the schema, and loads
the judgment datasets. **All existing data in that database will be deleted.**
The PostgreSQL service is available on `localhost:5432`. The development
connection string is in `.env` as `DATABASE_URL`. Its credentials are for local
development only.

To reload the datasets after the schema is applied, run
`uv run --group judgments-loader --env-file .env load-judgments`. See
`docs/judgments.md` for details.

Run the configured quality checks with:

```sh
uv run flake8 referee tests
uv run pyright
uv run --group judgments-loader --env-file .env pytest
```

See [`docs/testing.md`](docs/testing.md) for the test approach, database setup,
and controller e2e test pattern.

Install the pre-commit hooks in this checkout with:

```sh
uv run pre-commit install
```

The hooks run flake8, pyright, and pytest before every commit. The tests require
`TEST_DATABASE_URL`; `.env.example` points it at the local Docker PostgreSQL service.
If the database is unavailable or the schema has not been applied, the commit is
blocked by the failing test hook.

Pytest is included for behavioral tests, which will live under `tests/` as the
service features are implemented.

Stop PostgreSQL with `docker compose down`. Its data remains in the named
`postgres_data` volume; use `docker compose down -v` to remove it.
