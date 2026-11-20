"""Behavioral tests for the HTTP API using the test PostgreSQL database."""

from collections.abc import Iterator
from contextlib import closing
import os

import psycopg2
from fastapi.testclient import TestClient
import pytest

from referee.api.app import create_app


def _test_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL is required for the API tests")
    return database_url


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", _test_database_url())
    with TestClient(create_app()) as test_client:
        yield test_client


def _session_id(database_url: str, token: str) -> int:
    with closing(psycopg2.connect(database_url)) as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT session_id
                    FROM session_splits
                    WHERE bearer_token = %s
                    """,
                    (token,),
                )
                row = cursor.fetchone()
    assert row is not None
    return row[0]


def _delete_session(database_url: str, session_id: int) -> None:
    with closing(psycopg2.connect(database_url)) as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sessions WHERE session_id = %s", (session_id,)
                )


def _complete_payload(query_ids: list[str]) -> dict[str, object]:
    return {
        "results": [
            {
                "query_id": query_id,
                "doc_id": "-1",
                "rank": -1,
                "score": -1,
                "title": "optional ignored metadata",
            }
            for query_id in query_ids
        ]
    }


@pytest.mark.parametrize("eval_mode", ["ndcg", "mrr"])
def test_session_task_completion_api_lifecycle(
    client: TestClient, eval_mode: str
) -> None:
    database_url = _test_database_url()
    session_response = client.post(
        "/v1/sessions",
        json={
            "dataset_name": "doug_blog",
            "eval_mode": eval_mode,
            "num_queries": 2,
            "seed": 42,
            "splits": [1.0],
        },
    )
    assert session_response.status_code == 201
    split_tokens = session_response.json()["split_tokens"]
    assert len(split_tokens) == 1
    token = split_tokens[0]
    session_id = _session_id(database_url, token)

    try:
        task_response = client.post(
            "/v1/tasks", headers={"Authorization": f"Bearer {token}"}
        )
        assert task_response.status_code == 201
        task = task_response.json()
        assert task["dataset_name"] == "doug_blog"
        assert task["task"]["eval_mode"] == eval_mode
        query_ids = [query["query_id"] for query in task["queries"]]
        assert len(query_ids) == 2

        task_id = task["task"]["id"]
        complete_url = f"/v1/tasks/{task_id}/complete"
        headers = {"Authorization": f"Bearer {token}"}
        invalid_response = client.post(
            complete_url,
            headers=headers,
            json={"results": []},
        )
        assert invalid_response.status_code == 422

        incomplete_result = _read_task_complete(database_url, task_id)
        assert incomplete_result is False

        complete_response = client.post(
            complete_url,
            headers=headers,
            json=_complete_payload(query_ids),
        )
        assert complete_response.status_code == 200
        body = complete_response.json()
        assert body["task_id"] == task_id
        assert body["metrics"][eval_mode] == 0.0
        assert all(eval_mode in query for query in body["queries"])

        repeated_response = client.post(
            complete_url,
            headers=headers,
            json=_complete_payload(query_ids),
        )
        assert repeated_response.status_code == 409
    finally:
        _delete_session(database_url, session_id)


def _read_task_complete(database_url: str, task_id: str) -> bool | None:
    with closing(psycopg2.connect(database_url)) as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT complete FROM tasks WHERE task_id = %s", (task_id,)
                )
                row = cursor.fetchone()
    return None if row is None else row[0]


def test_task_routes_require_bearer_and_hide_task_ownership(
    client: TestClient,
) -> None:
    database_url = _test_database_url()
    first_response = client.post(
        "/v1/sessions",
        json={
            "dataset_name": "doug_blog",
            "eval_mode": "mrr",
            "splits": [1.0],
        },
    )
    second_response = client.post(
        "/v1/sessions",
        json={
            "dataset_name": "doug_blog",
            "eval_mode": "mrr",
            "splits": [1.0],
        },
    )
    assert first_response.status_code == second_response.status_code == 201
    first_token = first_response.json()["split_tokens"][0]
    second_token = second_response.json()["split_tokens"][0]
    session_ids = [
        _session_id(database_url, first_token),
        _session_id(database_url, second_token),
    ]

    try:
        assert client.post("/v1/tasks").status_code == 401
        assert client.post(
            "/v1/tasks", headers={"Authorization": "Bearer invalid"}
        ).status_code == 401

        task_response = client.post(
            "/v1/tasks", headers={"Authorization": f"Bearer {first_token}"}
        )
        assert task_response.status_code == 201
        task_id = task_response.json()["task"]["id"]
        wrong_owner_response = client.post(
            f"/v1/tasks/{task_id}/complete",
            headers={"Authorization": f"Bearer {second_token}"},
            json={"results": []},
        )
        assert wrong_owner_response.status_code == 404
    finally:
        for session_id in session_ids:
            _delete_session(database_url, session_id)


def test_session_api_validates_request_and_health_endpoints(
    client: TestClient,
) -> None:
    invalid_session = client.post(
        "/v1/sessions",
        json={
            "dataset_name": "doug_blog",
            "eval_mode": "mrr",
            "splits": [0.7, 0.2],
        },
    )
    assert invalid_session.status_code == 422

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ok"}
