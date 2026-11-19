# Referee

A service that acts as a referee for search retrieval autoresearch tasks.

## Development setup

This project uses Python 3.15.2 via asdf and uv for environment and dependency
management.

```sh
uv sync
cp .env.example .env
docker compose up -d --wait
```

The PostgreSQL service is available on `localhost:5432`. The development
connection string is in `.env` as `DATABASE_URL`. Its credentials are for local
development only.

Run the configured quality checks with:

```sh
uv run flake8 referee
uv run pyright
```

Install the post-commit checks in this checkout with:

```sh
cp .githooks/post-commit .git/hooks/post-commit
chmod +x .git/hooks/post-commit
```

The hook runs flake8, pyright, and pytest after each commit. Set `TEST_DATABASE_URL`
to run the PostgreSQL-backed session tests; otherwise those tests are skipped.

Pytest is included for behavioral tests, which will live under `tests/` as the
service features are implemented.

Stop PostgreSQL with `docker compose down`. Its data remains in the named
`postgres_data` volume; use `docker compose down -v` to remove it.
