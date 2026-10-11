from mbp.models import DbSelection

VALID = {
    "name": "prod",
    "host": "db.internal",
    "port": 3306,
    "username": "backup",
    "password": "s3cret-pw",
    "notes": "main server",
}


def create(client, **overrides):
    return client.post("/api/instances", json={**VALID, **overrides})


def test_create_returns_instance_without_password(auth_client):
    response = create(auth_client)
    assert response.status_code == 201
    body = response.json()
    assert body["has_password"] is True
    assert "password" not in body
    assert "password_encrypted" not in body
    assert body["server_type"] is None
    assert {k: body[k] for k in ("name", "host", "port", "username", "notes")} == {
        k: VALID[k] for k in ("name", "host", "port", "username", "notes")
    }


def test_port_defaults_to_3306(auth_client):
    payload = {k: v for k, v in VALID.items() if k != "port"}
    assert auth_client.post("/api/instances", json=payload).json()["port"] == 3306


def test_duplicate_name_conflict(auth_client):
    create(auth_client)
    response = create(auth_client, name="PROD")
    assert response.status_code == 409
    assert response.json()["code"] == "name_taken"


def test_validation_error_lists_fields(auth_client):
    response = create(auth_client, port=70000, host="mysql://x", name="")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert {"port", "host", "name"} <= set(body["fields"])


def test_missing_password_on_create(auth_client):
    payload = {k: v for k, v in VALID.items() if k != "password"}
    response = auth_client.post("/api/instances", json=payload)
    assert response.status_code == 422
    assert "password" in response.json()["fields"]


def test_list_ordered_by_name(auth_client):
    for name in ("zeta", "Alpha", "mid"):
        create(auth_client, name=name)
    names = [i["name"] for i in auth_client.get("/api/instances").json()]
    assert names == ["Alpha", "mid", "zeta"]


def test_get_and_404(auth_client):
    created = create(auth_client).json()
    assert auth_client.get(f"/api/instances/{created['id']}").json()["name"] == "prod"
    response = auth_client.get("/api/instances/9999")
    assert response.status_code == 404
    assert response.json() == {"code": "instance_not_found"}


def test_patch_partial_and_password_handling(auth_client, db):
    from mbp.models import DbInstance

    created = create(auth_client).json()
    stored = db.get(DbInstance, created["id"]).password_encrypted

    response = auth_client.patch(
        f"/api/instances/{created['id']}", json={"notes": "updated", "password": ""}
    )
    assert response.status_code == 200
    assert response.json()["notes"] == "updated"
    db.expire_all()
    assert db.get(DbInstance, created["id"]).password_encrypted == stored

    auth_client.patch(f"/api/instances/{created['id']}", json={"password": "new-one"})
    db.expire_all()
    assert db.get(DbInstance, created["id"]).password_encrypted != stored


def test_patch_unknown_404(auth_client):
    assert auth_client.patch("/api/instances/9999", json={"notes": "x"}).status_code == 404


def test_delete_removes_instance_and_selections(auth_client, db):
    created = create(auth_client).json()
    db.add(DbSelection(instance_id=created["id"], database_name="shop"))
    db.commit()

    assert auth_client.delete(f"/api/instances/{created['id']}").status_code == 204
    assert auth_client.get(f"/api/instances/{created['id']}").status_code == 404
    db.expire_all()
    assert db.query(DbSelection).count() == 0
    assert auth_client.delete(f"/api/instances/{created['id']}").status_code == 404
