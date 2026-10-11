"""SC-002: every API route except the allow-list rejects requests without a session."""

import re

PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/login/2fa"),
}


def all_routes(app) -> set[tuple[str, str]]:
    # The OpenAPI schema is generated from every registered route (even though it is not served).
    paths = app.openapi()["paths"]
    return {(method.upper(), path) for path, ops in paths.items() for method in ops}


def test_route_inventory_is_complete(app):
    routes = all_routes(app)
    assert routes >= PUBLIC
    assert len(routes) >= 12


def test_only_allow_listed_routes_work_without_a_session(app, client):
    reachable_without_session = set()
    for method, path in all_routes(app):
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url, json={})
        if response.status_code == 401 and response.json() == {"code": "not_authenticated"}:
            continue
        reachable_without_session.add((method, path))
    assert reachable_without_session == PUBLIC
