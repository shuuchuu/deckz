from pathlib import Path

from fastapi.testclient import TestClient
from studioz.app import create_app

ORIGIN = {"Origin": "http://localhost:8421"}


def test_a_page_answers_on_localhost(client: TestClient) -> None:
    assert client.get("/").status_code == 200


def test_another_host_is_refused(client: TestClient) -> None:
    # DNS rebinding: a website's own domain, resolved to 127.0.0.1.
    response = client.get("/", headers={"Host": "attacker.example:8421"})

    assert response.status_code == 403


def test_a_change_needs_studioz_s_own_origin(client: TestClient) -> None:
    form = {"name": "demo"}

    assert client.post("/espaces", data=form).status_code == 403
    assert (
        client.post(
            "/espaces", data=form, headers={"Origin": "http://attacker.example"}
        ).status_code
        == 403
    )
    assert client.post("/espaces/demo/fermer", headers=ORIGIN).status_code == 404


def test_127_0_0_1_works_too(repository: Path) -> None:
    client = TestClient(create_app(repository), base_url="http://127.0.0.1:8421")

    response = client.post(
        "/espaces/demo/fermer", headers={"Origin": "http://127.0.0.1:8421"}
    )

    assert response.status_code == 404
