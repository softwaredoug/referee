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
