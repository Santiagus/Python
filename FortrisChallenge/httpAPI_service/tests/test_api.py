import pytest
from fastapi.testclient import TestClient
from fastapi.exceptions import HTTPException
from httpAPI_service.app import app
from unittest.mock import AsyncMock, patch


@pytest.fixture
def client_ready():
    redis_mock = AsyncMock()
    redis_mock.get.return_value = '[{"Rank": 1, "Symbol": "BTC", "Price": 42863.717593629444}, {"Rank": 2, "Symbol": "ETH", "Price": 2540.618971408493}, {"Rank": 3, "Symbol": "SOL", "Price": 91.67929509303363}]'
    app.state.redis = redis_mock
    client = TestClient(app)
    return client


def test_get_top_crypto_list(client_ready):
    # Test successful response with JSON format
    response = client_ready.get("/?limit=3")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert len(response.json()) == 3

    # Test successful response with CSV format
    response_csv = client_ready.get("/?limit=3&format=CSV")
    assert response_csv.status_code == 200
    assert response_csv.headers["content-type"] == "application/csv"
    assert "Rank,Symbol,Price\n1,BTC,42863.717593629444\n2,ETH,2540.618971408493\n3,SOL,91.67929509303363\n" in response_csv.text

    # Test 404 response
    response_404 = client_ready.get("/nonexistent-endpoint")
    assert response_404.status_code == 404

    # Test 422 response (Unprocessable Entity)
    response_422 = client_ready.get("/?limit=invalid")
    assert response_422.status_code == 422


def test_get_top_crypto_list_no_redis():
    # Test 500 response (Internal Server Error)
    with patch("httpAPI_service.app.app.state.redis", None):
        client = TestClient(app)
        response_500 = client.get("/?limit=7")
        assert response_500.status_code == 500
