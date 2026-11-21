.PHONY: build db-bootstrap

build:
	docker compose build api

db-bootstrap:
	@test -f .env || { printf 'Missing .env; copy .env.example to .env first.\n' >&2; exit 1; }
	docker compose up -d --wait
	@set -a; . ./.env; set +a; \
		test -n "$$DATABASE_URL" || { printf 'DATABASE_URL must be set in .env.\n' >&2; exit 1; }; \
		database_name=$$(python3 -c 'import os; from urllib.parse import unquote, urlsplit; print(unquote(urlsplit(os.environ["DATABASE_URL"]).path.lstrip("/")))'); \
		maintenance_url=$$(python3 -c 'import os; from urllib.parse import urlsplit, urlunsplit; url = urlsplit(os.environ["DATABASE_URL"]); print(urlunsplit(url._replace(path="/postgres")))'); \
		test -n "$$database_name" || { printf 'DATABASE_URL must include a database name.\n' >&2; exit 1; }; \
		case "$$database_name" in ''|*[!A-Za-z0-9_-]*) printf 'Database name may contain only letters, digits, underscores, and hyphens.\n' >&2; exit 1 ;; esac; \
		printf 'This will permanently drop and recreate database "%s" and delete its data. Continue? [y/N] ' "$$database_name"; \
		IFS= read -r answer; \
		case "$$answer" in y|Y|yes|YES|Yes) ;; *) printf 'Aborted.\n'; exit 1 ;; esac; \
		psql "$$maintenance_url" \
			-c "DROP DATABASE IF EXISTS \"$$database_name\" WITH (FORCE)" \
			-c "CREATE DATABASE \"$$database_name\"" && \
		psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/0001_initial_schema.sql && \
		uv run --group judgments-loader --env-file .env load-judgments
