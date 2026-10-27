"""Web servers: the panel's API over the agent."""

from mbp.api.errors import ApiError
from tests.unit.test_webserver import debian_nginx


def test_lists_the_sites_of_the_current_server(containers_client, agent_app, tmp_path):
    response = containers_client.get("/api/webservers")
    assert response.status_code == 200
    assert response.json() == {"available": False, "servers": []}
    debian_nginx(tmp_path / "host")
    body = containers_client.get("/api/webservers").json()
    assert body["available"] is True
    [nginx] = body["servers"]
    names = {name for site in nginx["sites"] for name in site["names"]}
    assert names == {"shop.example", "www.shop.example", "old.example"}


def test_unknown_server(containers_client):
    assert containers_client.get("/api/webservers", params={"server": 999}).status_code == 404


def test_an_outdated_agent_is_named(containers_client, app, monkeypatch):
    def old_agent(self, method, path, **kwargs):
        raise ApiError(404, "agent_error")

    monkeypatch.setattr(type(app.state.agent), "_call", old_agent)
    response = containers_client.get("/api/webservers")
    assert (response.status_code, response.json()["code"]) == (409, "agent_outdated")
