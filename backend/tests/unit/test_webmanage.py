"""Web server management on a fake host: transactions, rollback, sites, logs, certificates."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from mbp.agent.docker import DockerClient
from mbp.agent.hostexec import DockerHostRunner, demux
from mbp.agent.webmanage import Jobs, WebError, WebManager, cert_info, sha256, split_files
from mbp.agent.webserver import scan
from tests.fakes.fake_host import FakeHost

NGINX_CONF = """
events {}
http {
    access_log /var/log/nginx/access.log;
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
"""
SHOP = """server {
    listen 80;
    server_name shop.example www.shop.example;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name shop.example www.shop.example;
    ssl_certificate /etc/ssl/shop.pem;
    ssl_certificate_key /etc/ssl/shop.key;
    access_log /var/log/nginx/shop.access.log;
    location / { proxy_pass http://127.0.0.1:3000; }
}
"""


@pytest.fixture
def host(tmp_path):
    fake = FakeHost(tmp_path / "host", tmp_path / "bin")
    fake.write("/etc/nginx/nginx.conf", NGINX_CONF)
    fake.write("/etc/nginx/sites-available/shop", SHOP)
    fake.link("/etc/nginx/sites-enabled/shop", "../sites-available/shop")
    fake.write("/etc/nginx/conf.d/api.conf", "server { server_name api.example; root /srv; }")
    fake.write("/var/log/nginx/shop.access.log", "\n".join(f"hit {i}" for i in range(50)))
    return fake


@pytest.fixture
def web(host):
    return WebManager(str(host.root), host.runner, Jobs(background=False))


def sites_by_file(host) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for server in scan(str(host.root))["servers"]:
        for site in server["sites"]:
            out.setdefault(site["file"], []).append(site)
    return out


def test_status(web):
    [nginx] = web.status()["servers"]
    assert nginx["kind"] == "nginx" and nginx["service"] == "nginx"
    assert nginx["state"] == "active" and nginx["systemd"] is True
    assert nginx["version"] == "1.24.0"
    assert nginx["pid"] == 1234
    assert nginx["since"] == "Mon 2026-10-26 08:00:00 UTC"
    assert nginx["last_reload"] == "2026-10-27T10:00:01+0000"


def test_reload_runs_the_test_first(web, host):
    assert web.control("nginx", "reload")["ok"] is True
    assert host.calls()[-2:] == ["nginx -t", "systemctl reload nginx"]
    host.write("/etc/nginx/conf.d/bad.conf", "BROKEN")
    result = web.control("nginx", "restart")
    assert (result["ok"], result["code"]) == (False, "config_test_failed")
    assert "unexpected BROKEN" in result["output"]
    assert "systemctl restart nginx" not in host.calls()


def test_edit_backs_up_tests_and_reloads(web, host):
    path = "/etc/nginx/sites-enabled/shop"  # the link: the real file is edited
    current = web.read_file("nginx", path)
    assert current["path"] == "/etc/nginx/sites-available/shop"
    new = SHOP.replace("3000", "4000")
    result = web.write_file("nginx", path, new, current["sha256"])
    assert result["ok"] is True, result
    assert host.read("/etc/nginx/sites-available/shop") == new
    assert "systemctl reload nginx" in host.calls()
    [backup] = web.backups("nginx", path)["backups"]
    assert web.read_backup("nginx", path, backup) == SHOP
    # Someone else changed the file since it was read.
    with pytest.raises(WebError) as exc:
        web.write_file("nginx", path, SHOP, current["sha256"])
    assert (exc.value.status, exc.value.code) == (409, "file_changed")
    # A restore is an edit too: backed up, tested, reloaded.
    assert web.restore("nginx", path, backup)["ok"] is True
    assert host.read("/etc/nginx/sites-available/shop") == SHOP
    assert len(web.backups("nginx", path)["backups"]) == 2


def test_a_broken_edit_is_rolled_back(web, host):
    path = "/etc/nginx/sites-available/shop"
    sha = web.read_file("nginx", path)["sha256"]
    host.calls()
    result = web.write_file("nginx", path, SHOP + "BROKEN", sha)
    assert (result["ok"], result["code"]) == (False, "config_test_failed")
    assert "unexpected BROKEN" in result["output"]
    assert host.read(path) == SHOP
    assert "systemctl reload nginx" not in host.calls()


def test_a_failed_reload_is_rolled_back_and_reloaded_again(web, host):
    path = "/etc/nginx/sites-available/shop"
    sha = web.read_file("nginx", path)["sha256"]
    (host.root / "fail-reload").touch()
    result = web.write_file("nginx", path, SHOP.replace("3000", "5000"), sha)
    assert (result["ok"], result["code"]) == (False, "reload_failed")
    assert host.read(path) == SHOP
    assert host.calls().count("systemctl reload nginx") == 2


def test_only_the_web_servers_files(web, host):
    host.write("/etc/passwd", "root:x:0:0")
    host.link("/etc/nginx/sites-available/evil", "/etc/passwd")
    for path in ("/etc/passwd", "/etc/nginx/../passwd", "/etc/nginx/sites-available/evil", "x"):
        with pytest.raises(WebError) as exc:
            web.read_file("nginx", path)
        assert exc.value.code == "path_not_allowed", path
    with pytest.raises(WebError) as exc:
        web.read_file("apache", "/etc/apache2/apache2.conf")
    assert exc.value.code == "webserver_not_found"


def test_disable_and_enable(web, host):
    assert web.set_enabled("nginx", "/etc/nginx/sites-available/shop", False)["ok"]
    assert not host.exists("/etc/nginx/sites-enabled/shop")
    assert all(not s["enabled"] for s in sites_by_file(host)["/etc/nginx/sites-available/shop"])
    assert web.set_enabled("nginx", "/etc/nginx/sites-available/shop", True)["ok"]
    assert host.exists("/etc/nginx/sites-enabled/shop")
    # conf.d files are renamed.
    assert web.set_enabled("nginx", "/etc/nginx/conf.d/api.conf", False)["ok"]
    assert host.exists("/etc/nginx/conf.d/api.conf.mbp-disabled")
    [api] = sites_by_file(host)["/etc/nginx/conf.d/api.conf.mbp-disabled"]
    assert api["enabled"] is False and api["names"] == ["api.example"]
    assert web.set_enabled("nginx", "/etc/nginx/conf.d/api.conf.mbp-disabled", True)["ok"]
    assert host.exists("/etc/nginx/conf.d/api.conf")


def test_disabling_is_undone_when_the_test_fails(web, host):
    host.write("/etc/nginx/sites-available/needs-shop", "")
    # Another site that only works while shop is loaded: modelled by a broken file appearing.
    host.write("/etc/nginx/conf.d/x.conf", "BROKEN")
    result = web.set_enabled("nginx", "/etc/nginx/sites-available/shop", False)
    assert result["code"] == "config_test_failed"
    assert host.exists("/etc/nginx/sites-enabled/shop")


def test_maintenance(web, host):
    path = "/etc/nginx/sites-available/shop"
    assert web.set_maintenance("nginx", path, True)["ok"]
    page = "/etc/nginx/sites-available/mbp-maintenance-shop"
    text = host.read(page)
    assert "return 503" in text and "listen 443 ssl;" in text
    assert "ssl_certificate_key /etc/ssl/shop.key;" in text
    assert "return 301 https://$host$request_uri;" in text  # the redirect block stays
    assert host.exists("/etc/nginx/sites-enabled/mbp-maintenance-shop")
    assert not host.exists("/etc/nginx/sites-enabled/shop")
    by_file = sites_by_file(host)
    assert all(s["maintenance"] and s["enabled"] for s in by_file[path])
    assert all(s["maintenance_page"] for s in by_file[page])
    # Again: nothing to do.
    assert web.set_maintenance("nginx", path, True)["ok"]
    assert web.set_maintenance("nginx", path, False)["ok"]
    assert not host.exists(page)
    assert not host.exists("/etc/nginx/sites-enabled/mbp-maintenance-shop")
    assert host.exists("/etc/nginx/sites-enabled/shop")
    assert not any(s["maintenance"] for s in sites_by_file(host)[path])


def test_maintenance_of_a_conf_d_file(web, host):
    path = "/etc/nginx/conf.d/api.conf"
    assert web.set_maintenance("nginx", path, True)["ok"]
    assert host.exists("/etc/nginx/conf.d/api.conf.mbp-disabled")
    assert host.exists("/etc/nginx/conf.d/mbp-maintenance-api.conf")
    assert web.set_maintenance("nginx", path, False)["ok"]
    assert host.exists(path) and not host.exists("/etc/nginx/conf.d/mbp-maintenance-api.conf")


def test_new_sites_from_templates(web, host):
    result = web.create_site(
        "nginx",
        {
            "template": "proxy",
            "domains": ["App.Example", "www.app.example"],
            "target": "http://127.0.0.1:8080",
        },
    )
    assert result["ok"] is True, result
    assert result["path"] == "/etc/nginx/sites-available/app-example"
    text = host.read(result["path"])
    assert "server_name app.example www.app.example;" in text
    assert "proxy_pass http://127.0.0.1:8080;" in text
    assert host.exists("/etc/nginx/sites-enabled/app-example")
    with pytest.raises(WebError) as exc:
        web.create_site(
            "nginx", {"template": "proxy", "domains": ["app.example"], "target": "http://x:1"}
        )
    assert exc.value.code == "site_name_taken"
    for spec, code in [
        ({"template": "proxy", "domains": ["a.example"], "target": "http://x;y"}, "invalid_target"),
        ({"template": "static", "domains": ["a.example"], "root": "/srv/../etc"}, "invalid_root"),
        (
            {"template": "php", "domains": ["a.example"], "root": "/srv", "php_fpm": "x"},
            "invalid_php_fpm",
        ),
        ({"template": "static", "domains": ["a b"], "root": "/srv"}, "invalid_domain"),
        ({"template": "shell", "domains": ["a.example"]}, "invalid_template"),
    ]:
        with pytest.raises(WebError) as exc:
            web.create_site("nginx", spec)
        assert exc.value.code == code, spec
    redirect = web.create_site(
        "nginx",
        {
            "template": "redirect",
            "domains": ["old.example"],
            "target": "https://new.example",
            "name": "old",
        },
    )
    assert "return 301 https://new.example$request_uri;" in host.read(redirect["path"])


def test_a_new_site_that_breaks_the_test_is_removed(web, host):
    host.write("/etc/nginx/conf.d/x.conf", "BROKEN")
    result = web.create_site(
        "nginx", {"template": "static", "domains": ["s.example"], "root": "/srv/s"}
    )
    assert result["code"] == "config_test_failed"
    assert not host.exists("/etc/nginx/sites-available/s-example")
    assert not host.exists("/etc/nginx/sites-enabled/s-example")


def test_apache_site_enables_its_modules(tmp_path):
    host = FakeHost(tmp_path / "host", tmp_path / "bin")
    host.write("/etc/apache2/apache2.conf", "IncludeOptional sites-enabled/*.conf\n")
    host.write("/etc/apache2/envvars", "export APACHE_LOG_DIR=/var/log/apache2$SUFFIX\n")
    (host.root / "etc/apache2/sites-enabled").mkdir()
    web = WebManager(str(host.root), host.runner, Jobs(background=False))
    result = web.create_site(
        "apache",
        {
            "template": "php",
            "domains": ["blog.example"],
            "root": "/var/www/blog",
            "php_fpm": "unix:/run/php/php8.2-fpm.sock",
        },
    )
    assert result["ok"] is True, result
    text = host.read("/etc/apache2/sites-available/blog-example.conf")
    assert 'SetHandler "proxy:unix:/run/php/php8.2-fpm.sock|fcgi://localhost"' in text
    assert host.exists("/etc/apache2/sites-enabled/blog-example.conf")
    assert "a2enmod -q proxy proxy_fcgi" in host.calls()
    [apache] = scan(str(host.root))["servers"]
    [site] = apache["sites"]
    assert site["logs"] == {
        "access": "/var/log/apache2/blog-example.access.log",
        "error": "/var/log/apache2/blog-example.error.log",
    }
    assert web.status()["servers"][0]["version"] == "2.4.62"


def test_logs_only_of_declared_files(web, host):
    result = web.logs("nginx", "/var/log/nginx/shop.access.log", 3)
    assert result["lines"] == ["hit 47", "hit 48", "hit 49"]
    host.write("/var/log/secret.log", "x")
    with pytest.raises(WebError) as exc:
        web.logs("nginx", "/var/log/secret.log", 3)
    assert exc.value.code == "log_not_found"


def make_cert(days: int, name: str = "shop.example") -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(x509.Name([x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Test CA")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_certificates(web, host):
    host.write("/etc/ssl/shop.pem", make_cert(10))
    info = web.certificates()["certificates"]["/etc/ssl/shop.pem"]
    assert info["error"] is None
    assert info["names"] == ["shop.example"] and info["issuer"] == "Test CA"
    left = datetime.fromisoformat(info["not_after"]) - datetime.now(UTC)
    assert 9 <= left.days <= 10
    assert cert_info("nope") == {"error": "certificate_invalid"}


def test_split_files():
    out = "==MBP-FILE== /p/a\nAAA\n==MBP-FILE== /p/b\n==MBP-UNREADABLE==\n==MBP-FILE== /p/c\nC\n"
    assert split_files(out, "/p") == {"/a": "AAA\n", "/b": None, "/c": "C\n"}


def test_certbot(web, host):
    status = web.certbot()
    assert status["installed"] is True and status["auto_renew"] == "certbot.timer"
    job = web.certbot_issue("nginx", ["shop.example", "www.shop.example"], "ops@shop.example", True)
    assert job.status == "success"
    assert (
        "certbot --nginx --non-interactive --agree-tos --keep-until-expiring --cert-name "
        "shop.example -m ops@shop.example --redirect -d shop.example -d www.shop.example"
    ) in host.calls()
    for domains, email, code in [
        (["*.shop.example"], None, "wildcard_not_supported"),
        (["-d evil"], None, "invalid_domain"),
        (["shop.example"], "not an email", "invalid_email"),
    ]:
        with pytest.raises(WebError) as exc:
            web.certbot_issue("nginx", domains, email, True)
        assert exc.value.code == code
    assert web.certbot_renew().status == "success"
    assert web.certbot_install("nginx").status == "success"
    assert "apt-get install -y certbot python3-certbot-nginx" in host.calls()


def test_sha256_matches_read(web):
    data = web.read_file("nginx", "/etc/nginx/sites-available/shop")
    assert data["sha256"] == sha256(SHOP)


# --- the helper container ---


def frame(stream: int, data: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data


def test_docker_host_runner():
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content))
        path = request.url.path
        if path == "/containers/json":
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": "a",
                        "State": "running",
                        "Labels": {"mbp.role": "agent"},
                        "ImageID": "sha256:abc",
                    }
                ],
            )
        if path == "/containers/create":
            return httpx.Response(201, json={"Id": "helper1"})
        if path.endswith("/wait"):
            return httpx.Response(200, json={"StatusCode": 3})
        if path.endswith("/logs"):
            return httpx.Response(200, content=frame(1, b"out\n") + frame(2, b"err\n"))
        return httpx.Response(204)

    docker = DockerClient("http://docker", transport=httpx.MockTransport(handle))
    result = DockerHostRunner(docker).run(["nginx", "-t"], env={"A": "1"})
    assert (result.code, result.stdout, result.stderr) == (3, "out\n", "err\n")
    create = json.loads(next(c[2] for c in calls if c[1] == "/containers/create"))
    assert create["Image"] == "sha256:abc"
    assert create["Entrypoint"][:2] == ["sh", "-c"]
    assert "nsenter --target 1 --mount" in create["Entrypoint"][2]
    assert create["HostConfig"]["Binds"] == ["/:/host"]
    assert create["Cmd"] == ["nginx", "-t"]
    assert "A=1" in create["Env"]
    assert create["HostConfig"]["Privileged"] is True
    assert create["HostConfig"]["PidMode"] == "host"
    assert create["Labels"] == {"mbp.role": "helper"}
    assert ("DELETE", "/containers/helper1") in [(m, p) for m, p, _ in calls]


def test_demux():
    assert demux(frame(1, b"a") + frame(2, b"b") + frame(1, b"c")) == ("ac", "b")
