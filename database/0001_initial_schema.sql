CREATE TABLE session_keys (
    session_key_id BIGSERIAL PRIMARY KEY,
    key_type TEXT NOT NULL CHECK (key_type IN ('holdout', 'training')),
    key_value TEXT NOT NULL UNIQUE,
    dataset_name TEXT NOT NULL,
    eval_mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMPTZ,
    parent_key BIGINT REFERENCES session_keys(session_key_id) ON DELETE CASCADE,
    CHECK (
        (key_type = 'holdout' AND parent_key IS NULL)
        OR (key_type = 'training' AND parent_key IS NOT NULL)
    )
);

CREATE INDEX session_keys_parent_key_idx ON session_keys(parent_key);

CREATE TABLE datasets (
    dataset_id BIGSERIAL PRIMARY KEY,
    dataset_name TEXT NOT NULL UNIQUE,
    min_grade INTEGER NOT NULL,
    max_grade INTEGER NOT NULL,
    metric TEXT NOT NULL,
    CHECK (min_grade <= max_grade)
);

CREATE TABLE queries (
    query_id BIGSERIAL PRIMARY KEY,
    source_query_id TEXT NOT NULL,
    split TEXT,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    keywords TEXT NOT NULL,
    metadata JSONB,
    UNIQUE (dataset_id, source_query_id)
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
