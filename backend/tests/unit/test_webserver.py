"""Reading nginx and Apache configurations from the host's files (mbp.agent.webserver)."""

import os
from pathlib import Path

from mbp.agent.webserver import nginx_tokens, scan

NGINX_CONF = """
user www-data;
events { worker_connections 768; }
http {
    include /etc/nginx/mime.types;
    upstream app_backend { server 127.0.0.1:3000; server 127.0.0.1:3001 backup; }
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
stream { server { listen 3306; proxy_pass db:3306; } }
"""

SHOP = """
# certbot's layout: a redirect on port 80 and the site on 443
server {
    if ($host = www.shop.example) { return 301 https://$host$request_uri; }
    listen 80;
    listen [::]:80;
    server_name shop.example www.shop.example;
    return 404;
}
server {
    listen 443 ssl http2;
    listen [::]:443 ssl;
    server_name shop.example www.shop.example;
    ssl_certificate /etc/letsencrypt/live/shop.example/fullchain.pem;
    location / { proxy_pass http://app_backend; }
    location /static/ { root "/srv/shop/static"; }
}
"""

BLOG = r"""
server {
    listen 8080 default_server;
    server_name _;
    root /var/www/html;  # the catch-all
    location ~ \.php$ { fastcgi_pass unix:/run/php/php8.2-fpm.sock; }
}
"""

APACHE_CONF = """
ServerRoot "/etc/apache2"
Include ports.conf
IncludeOptional mods-enabled/*.load
IncludeOptional conf-enabled/*.conf
IncludeOptional sites-enabled/*.conf
"""

APACHE_SITE = """
<VirtualHost *:80>
    ServerName api.example:80
    ServerAlias api2.example \\
        api3.example
    DocumentRoot /var/www/api
    Redirect permanent / https://api.example/
</VirtualHost>
<IfModule mod_ssl.c>
  <VirtualHost _default_:443>
    ServerName api.example
    SSLEngine on
    SSLCertificateFile "/etc/ssl/certs/api.pem"
    ProxyPass /app http://127.0.0.1:9000/ retry=0
    <FilesMatch "\\.php$">
        SetHandler "proxy:unix:/run/php/php8.2-fpm.sock|fcgi://localhost"
    </FilesMatch>
  </VirtualHost>
</IfModule>
"""


def write(root: Path, path: str, text: str) -> Path:
    target = root / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def link(root: Path, path: str, target: str) -> None:
    where = root / path.lstrip("/")
    where.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, where)


def debian_nginx(root: Path) -> None:
    write(root, "/etc/nginx/nginx.conf", NGINX_CONF)
    write(root, "/etc/nginx/mime.types", "types { text/html html; }")
    write(root, "/etc/nginx/sites-available/shop", SHOP)
    write(root, "/etc/nginx/sites-available/blog", BLOG)
    write(root, "/etc/nginx/sites-available/old", "server { server_name old.example; }")
    # An absolute link means the host's path, never the agent's own /etc.
    link(root, "/etc/nginx/sites-enabled/shop", "/etc/nginx/sites-available/shop")
    link(root, "/etc/nginx/sites-enabled/blog", "../sites-available/blog")
    (root / "etc/nginx/conf.d").mkdir(parents=True)


def by_names(server: dict) -> dict:
    return {(tuple(s["names"]), tuple(s["ports"])): s for s in server["sites"]}


def test_nothing_mounted(tmp_path):
    assert scan(str(tmp_path / "missing")) == {"available": False, "servers": []}
    (tmp_path / "etc").mkdir()
    assert scan(str(tmp_path)) == {"available": True, "servers": []}


def test_nginx_sites_follow_includes_and_links(tmp_path):
    debian_nginx(tmp_path)
    result = scan(str(tmp_path))
    [nginx] = result["servers"]
    assert nginx["kind"] == "nginx" and nginx["error"] is None
    assert nginx["warnings"] == []
    sites = by_names(nginx)
    names = ("shop.example", "www.shop.example")
    redirect = sites[(names, (80,))]
    assert redirect["redirect"] == "https://$host$request_uri"
    assert redirect["ssl"] is False and redirect["enabled"] is True
    assert redirect["file"] == "/etc/nginx/sites-available/shop"
    assert redirect["line"] == 3
    secure = sites[(names, (443,))]
    assert secure["ssl"] is True
    assert secure["certificate"] == "/etc/letsencrypt/live/shop.example/fullchain.pem"
    assert secure["backends"] == [
        {
            "kind": "proxy",
            "target": "http://app_backend",
            "servers": ["127.0.0.1:3000", "127.0.0.1:3001"],
        }
    ]
    catch_all = sites[((), (8080,))]
    assert catch_all["default_server"] is True
    assert catch_all["root"] == "/var/www/html"
    assert catch_all["backends"][0]["kind"] == "fastcgi"
    # In sites-available but not enabled; stream {} servers are not web sites.
    old = sites[(("old.example",), (80,))]
    assert old["enabled"] is False
    assert len(nginx["sites"]) == 4


def test_nginx_problems_are_reported_not_raised(tmp_path):
    write(tmp_path, "/etc/nginx/nginx.conf", "http { include missing.conf; server { listen 80;")
    [nginx] = scan(str(tmp_path))["servers"]
    assert "unexpected end of file" in nginx["error"]
    write(tmp_path, "/etc/nginx/nginx.conf", "http { include missing.conf; }")
    [nginx] = scan(str(tmp_path))["servers"]
    assert nginx["error"] is None
    assert nginx["warnings"] == [
        "included file not found: /etc/nginx/missing.conf (/etc/nginx/nginx.conf:1)"
    ]


def test_include_loops_and_escaping_links_stay_inside(tmp_path):
    write(tmp_path, "/etc/nginx/nginx.conf", "http { include /etc/nginx/loop.conf; }")
    write(tmp_path, "/etc/nginx/loop.conf", "include /etc/nginx/loop.conf;")
    [nginx] = scan(str(tmp_path / ""))["servers"]
    assert any("nested too deeply" in w for w in nginx["warnings"])
    # A link to ../../../.. resolves to the host's root, never above the mount.
    outside = tmp_path.parent / "outside.conf"
    outside.write_text("server { server_name leaked.example; }")
    link(tmp_path, "/etc/nginx/sites-enabled/x", "../../../../../../outside.conf")
    write(tmp_path, "/etc/nginx/nginx.conf", "http { include sites-enabled/*; }")
    [nginx] = scan(str(tmp_path))["servers"]
    assert nginx["sites"] == []


def test_nginx_tokens_quotes_and_comments():
    tokens = [t for t, _, _ in nginx_tokens('a "b c;" # d;\n e${x}f {}')]
    assert tokens == ["a", "b c;", "e${x}f", "{", "}"]


def test_apache_debian(tmp_path):
    write(tmp_path, "/etc/apache2/apache2.conf", APACHE_CONF)
    write(tmp_path, "/etc/apache2/ports.conf", "Listen 80\n")
    write(tmp_path, "/etc/apache2/sites-available/api.conf", APACHE_SITE)
    write(
        tmp_path,
        "/etc/apache2/sites-available/000-default.conf",
        "<VirtualHost *:80>\n  DocumentRoot /var/www/html\n</VirtualHost>\n",
    )
    link(tmp_path, "/etc/apache2/sites-enabled/api.conf", "../sites-available/api.conf")
    [apache] = scan(str(tmp_path))["servers"]
    assert apache["kind"] == "apache" and apache["config"] == "/etc/apache2/apache2.conf"
    assert apache["error"] is None and apache["warnings"] == []
    plain, secure, default = apache["sites"]
    assert plain["names"] == ["api.example", "api2.example", "api3.example"]
    assert plain["ports"] == [80] and plain["ssl"] is False
    assert plain["redirect"] == "https://api.example/"
    assert plain["root"] == "/var/www/api" and plain["enabled"] is True
    assert secure["names"] == ["api.example"]
    assert secure["ports"] == [443] and secure["ssl"] is True
    assert secure["default_server"] is True
    assert secure["certificate"] == "/etc/ssl/certs/api.pem"
    assert [b["kind"] for b in secure["backends"]] == ["proxy", "fastcgi"]
    assert secure["backends"][0]["target"] == "http://127.0.0.1:9000/"
    assert default["enabled"] is False and default["names"] == []


def test_apache_rhel_with_a_directory_include(tmp_path):
    write(
        tmp_path,
        "/etc/httpd/conf/httpd.conf",
        'ServerRoot "/etc/httpd"\nInclude conf.d/\nIncludeOptional nothing/*.conf\n',
    )
    write(
        tmp_path,
        "/etc/httpd/conf.d/a/site.conf",
        "<VirtualHost 10.0.0.1:8443>\nServerName https://Site.Example:8443\n</VirtualHost>",
    )
    [apache] = scan(str(tmp_path))["servers"]
    assert apache["config"] == "/etc/httpd/conf/httpd.conf"
    [site] = apache["sites"]
    assert site["names"] == ["site.example"] and site["ports"] == [8443]
    assert site["file"] == "/etc/httpd/conf.d/a/site.conf"


def test_both_servers(tmp_path):
    debian_nginx(tmp_path)
    write(tmp_path, "/etc/apache2/apache2.conf", "")
    kinds = [s["kind"] for s in scan(str(tmp_path))["servers"]]
    assert kinds == ["nginx", "apache"]
