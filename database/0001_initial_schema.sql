CREATE TABLE datasets (
    dataset_id BIGSERIAL PRIMARY KEY,
    dataset_name TEXT NOT NULL UNIQUE,
    min_grade INTEGER NOT NULL,
    max_grade INTEGER NOT NULL,
    metric TEXT NOT NULL,
    CHECK (min_grade <= max_grade)
);

CREATE TABLE sessions (
    session_id BIGSERIAL PRIMARY KEY,
    dataset_name TEXT NOT NULL REFERENCES datasets(dataset_name),
    eval_mode TEXT NOT NULL,
    num_queries INTEGER CHECK (num_queries IS NULL OR num_queries > 0),
    user_seed BIGINT NOT NULL,
    sort_salt TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMPTZ
);

CREATE TABLE session_splits (
    session_split_id BIGSERIAL PRIMARY KEY,
    bearer_token TEXT NOT NULL UNIQUE,
    session_id BIGINT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    proportion DOUBLE PRECISION NOT NULL CHECK (proportion > 0 AND proportion <= 1),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMPTZ,
    UNIQUE (session_id, ordinal)
);

CREATE INDEX session_splits_session_id_idx ON session_splits(session_id);

CREATE TABLE queries (
    query_id BIGSERIAL PRIMARY KEY,
    source_query_id TEXT NOT NULL,
    split TEXT,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    keywords TEXT NOT NULL,
    metadata JSONB,
    UNIQUE NULLS NOT DISTINCT (dataset_id, source_query_id, split)
);

CREATE INDEX queries_dataset_split_idx ON queries(dataset_id, split);

CREATE TABLE judgments (
    judgment_id BIGSERIAL PRIMARY KEY,
    query_id BIGINT NOT NULL REFERENCES queries(query_id) ON DELETE CASCADE,
    doc_id TEXT NOT NULL,
    grade INTEGER NOT NULL,
    UNIQUE (query_id, doc_id)
);

CREATE INDEX judgments_query_id_idx ON judgments(query_id);
