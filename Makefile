.PHONY: db-bootstrap

db-bootstrap:
	@test -f .env || { printf 'Missing .env; copy .env.example to .env first.\n' >&2; exit 1; }
	docker compose up -d --wait
	@set -a; . ./.env; set +a; \
		test -n "$$DATABASE_URL" || { printf 'DATABASE_URL must be set in .env.\n' >&2; exit 1; }; \
		psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/0001_initial_schema.sql && \
		uv run --group judgments-loader --env-file .env load-judgments
