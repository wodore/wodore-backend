import pytest


def test_version_endpoint(client):
    response = client.get("/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "hash" in data


@pytest.mark.django_db
def test_health_endpoint(client):
    response = client.get("/health/")
    assert response.status_code == 200
