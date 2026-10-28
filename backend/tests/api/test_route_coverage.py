"""SC-002: every API route except the allow-list rejects requests without a session.

The external API (/api/v1) rejects them without an API key instead.
"""

import re

PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/login/2fa"),
    ("GET", "/api/v1/health"),
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
    reachable = set()
    for method, path in all_routes(app):
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url, json={})
        expected = "api_key_missing" if path.startswith("/api/v1/") else "not_authenticated"
        if response.status_code == 401 and response.json() == {"code": expected}:
            continue
        reachable.add((method, path))
    assert reachable == PUBLIC


def test_every_dashboard_feature_is_in_the_external_api(app):
    routes = all_routes(app)
    dashboard_only = re.compile(r"^/api/(auth|api-access)(/|$)")
    for method, path in routes:
        if path.startswith("/api/v1/") or dashboard_only.match(path):
            continue
        assert (method, "/api/v1" + path[len("/api") :]) in routes, (method, path)
