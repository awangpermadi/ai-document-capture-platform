import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


ALLOWED_ORIGIN = "http://localhost:5173"
UNKNOWN_ORIGIN = "http://untrusted.example"


def test_allowed_origin_preflight_succeeds() -> None:
    client = TestClient(app)

    response = client.options(
        "/documents/example-id/receipt",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,x-reviewed-by",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "PUT" in response.headers["access-control-allow-methods"]
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "content-type" in allowed_headers
    assert "x-reviewed-by" in allowed_headers
    assert response.headers.get("access-control-allow-credentials") != "true"


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "http://127.0.0.1:5173"],
)
def test_allowed_origin_receives_cors_header(origin: str) -> None:
    response = TestClient(app).get(
        "/health",
        headers={"Origin": origin},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_unknown_origin_does_not_receive_cors_header() -> None:
    response = TestClient(app).get(
        "/health",
        headers={"Origin": UNKNOWN_ORIGIN},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_existing_api_routes_remain_registered() -> None:
    paths = app.openapi()["paths"]
    expected_methods = {
        "/documents": {"get"},
        "/documents/{document_id}": {"get", "delete"},
        "/documents/{document_id}/receipt": {"put"},
        "/documents/{document_id}/approve": {"post"},
        "/documents/upload": {"post"},
        "/documents/analyze": {"post"},
        "/documents/debug-analysis": {"post"},
        "/documents/process": {"post"},
    }

    for path, methods in expected_methods.items():
        assert path in paths
        assert methods <= paths[path].keys()


def test_cors_origins_are_parsed_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173, https://review.example.test ,",
    )
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_endpoint="",
        azure_document_intelligence_key="",
    )

    assert settings.cors_allowed_origins_list == [
        "http://localhost:5173",
        "https://review.example.test",
    ]


def test_cors_origins_reject_wildcard() -> None:
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_endpoint="",
        azure_document_intelligence_key="",
        cors_allowed_origins="*, http://localhost:5173",
    )

    with pytest.raises(ValueError, match="cannot contain a wildcard"):
        settings.cors_allowed_origins_list
