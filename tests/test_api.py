"""Behavioral tests for the HTTP API using the test PostgreSQL database."""

from collections.abc import Iterator
from contextlib import closing
import os

import psycopg2
from fastapi.testclient import TestClient
import pytest

from referee.api.app import create_app
from referee.eval.db import EvalDB


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
        wrong_owner_debug_response = client.post(
            f"/v1/tasks/{task_id}/debug",
            headers={"Authorization": f"Bearer {second_token}"},
            json={
                "query_ids": ["1"],
                "results": [
                    {"query_id": "1", "doc_id": "doc-1", "rank": 1, "score": 1}
                ],
            },
        )
        assert wrong_owner_debug_response.status_code == 404
        assert client.post(
            f"/v1/tasks/{task_id}/debug",
            json={"query_ids": ["1"], "results": []},
        ).status_code == 401
    finally:
        for session_id in session_ids:
            _delete_session(database_url, session_id)


def test_debug_queries_api_returns_partial_results_and_targets(
    client: TestClient,
) -> None:
    database_url = _test_database_url()
    session_response = client.post(
        "/v1/sessions",
        json={
            "dataset_name": "doug_blog",
            "eval_mode": "mrr",
            "num_queries": 3,
            "seed": 42,
            "splits": [1.0],
        },
    )
    assert session_response.status_code == 201
    token = session_response.json()["split_tokens"][0]
    session_id = _session_id(database_url, token)
    headers = {"Authorization": f"Bearer {token}"}

    try:
        task_response = client.post("/v1/tasks", headers=headers)
        assert task_response.status_code == 201
        task = task_response.json()
        task_id = task["task"]["id"]
        query_ids = [query["query_id"] for query in task["queries"]]
        judgments = EvalDB(database_url).get_judgments(
            [int(query_id) for query_id in query_ids]
        )

        all_results: list[dict[str, object]] = []
        for query_id in query_ids:
            query_judgments = judgments[int(query_id)]
            best_doc_id = min(
                query_judgments,
                key=lambda doc_id: (-query_judgments[doc_id], doc_id),
            )
            all_results.extend(
                [
                    {
                        "query_id": query_id,
                        "doc_id": best_doc_id,
                        "rank": 1,
                        "score": 0.9,
                    },
                    {
                        "query_id": query_id,
                        "doc_id": f"unjudged-{query_id}",
                        "rank": 2,
                        "score": 0.1,
                    },
                ]
            )

        requested_query_ids = query_ids[:2]
        requested_results = [
            row for row in all_results if row["query_id"] in requested_query_ids
        ]
        debug_response = client.post(
            f"/v1/tasks/{task_id}/debug",
            headers=headers,
            json={
                "query_ids": requested_query_ids,
                "results": requested_results,
                "include_target": True,
            },
        )
        assert debug_response.status_code == 200
        debug_body = debug_response.json()
        assert list(debug_body["queries"]) == requested_query_ids
        for query_id in requested_query_ids:
            query_debug = debug_body["queries"][query_id]
            query_judgments = judgments[int(query_id)]
            assert query_debug["results"][0]["relevance_grade"] == query_judgments[
                query_debug["results"][0]["doc_id"]
            ]
            assert query_debug["results"][1]["relevance_grade"] == 0
            expected_target = sorted(
                query_judgments.items(),
                key=lambda judgment: (-judgment[1], judgment[0]),
            )[:10]
            assert [
                (row["doc_id"], row["relevance_grade"])
                for row in query_debug["target"]
            ] == expected_target

        missing_row_response = client.post(
            f"/v1/tasks/{task_id}/debug",
            headers=headers,
            json={
                "query_ids": [query_ids[0]],
                "results": [
                    row for row in all_results if row["query_id"] != query_ids[0]
                ],
            },
        )
        assert missing_row_response.status_code == 422
        outside_split_response = client.post(
            f"/v1/tasks/{task_id}/debug",
            headers=headers,
            json={
                "query_ids": ["not-a-task-query"],
                "results": [],
            },
        )
        assert outside_split_response.status_code == 422

        complete_response = client.post(
            f"/v1/tasks/{task_id}/complete",
            headers=headers,
            json={"results": all_results},
        )
        assert complete_response.status_code == 200
        debug_after_completion = client.post(
            f"/v1/tasks/{task_id}/debug",
            headers=headers,
            json={
                "query_ids": [query_ids[0]],
                "results": [
                    row for row in all_results if row["query_id"] == query_ids[0]
                ],
            },
        )
        assert debug_after_completion.status_code == 200
        assert "target" not in debug_after_completion.json()["queries"][query_ids[0]]
    finally:
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


def test_openapi_is_an_agent_usable_workflow_guide(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    openapi = response.json()

    description = openapi["info"]["description"]
    assert "orchestrator" in description
    assert "Authorization: Bearer <split_token>" in description
    assert "single-use" in description
    assert "debug" in description.lower()

    tags = {tag["name"]: tag["description"] for tag in openapi["tags"]}
    assert "split tokens are ordered" in tags["sessions"]
    assert "complete query list" in tags["tasks"]

    session_operation = openapi["paths"]["/v1/sessions"]["post"]
    assert session_operation["summary"] == "Create a session and its query splits"
    session_model = openapi["components"]["schemas"]["CreateSessionRequest"]
    assert session_model["examples"][0]["splits"] == [0.6, 0.2, 0.2]
    assert "security" not in session_operation

    task_operation = openapi["paths"]["/v1/tasks"]["post"]
    assert task_operation["security"]
    security_schemes = openapi["components"]["securitySchemes"]
    assert "split token returned" in security_schemes["SplitBearerToken"]["description"]

    completion_model = openapi["components"]["schemas"]["CompleteTaskRequest"]
    assert completion_model["examples"][0]["results"][1]["rank"] == -1
    debug_operation = openapi["paths"]["/v1/tasks/{task_id}/debug"]["post"]
    assert debug_operation["security"]
    assert "read-only" in debug_operation["description"]
    debug_model = openapi["components"]["schemas"]["DebugQueriesRequest"]
    assert debug_model["examples"][0]["include_target"] is True
    assert debug_model["properties"]["query_ids"]["minItems"] == 1
    assert "/healthz" in openapi["paths"]
