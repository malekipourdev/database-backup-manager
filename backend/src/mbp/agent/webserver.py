"""The web servers installed on the host (nginx, Apache) and the sites they serve.

Read-only: the agent reads the host's configuration files, mounted read-only under
`host_root` (the host's /etc at <host_root>/etc), and follows their include directives the
way the servers do. It never changes a file or runs a command. Paths in its answers are the
host's paths; symbolic links are followed inside the mount, never outside it.
"""

import fnmatch
import os
import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

# Limits, so an unusual configuration cannot make the agent read without end.
MAX_FILES = 500
MAX_FILE_BYTES = 1024 * 1024
MAX_INCLUDE_DEPTH = 16
MAX_SYMLINKS = 40
MAX_WARNINGS = 20

NGINX_MAIN = "/etc/nginx/nginx.conf"
APACHE_MAINS = ("/etc/apache2/apache2.conf", "/etc/httpd/conf/httpd.conf")
REDIRECT_CODES = {"301", "302", "303", "307", "308"}
NGINX_BACKENDS = {
    "proxy_pass": "proxy",
    "fastcgi_pass": "fastcgi",
    "uwsgi_pass": "uwsgi",
    "grpc_pass": "grpc",
    "scgi_pass": "scgi",
}
_MAGIC = re.compile(r"[*?\[]")
# Files the panel writes: a site's maintenance page, and conf.d files it turned off.
MAINTENANCE_PREFIX = "mbp-maintenance-"
DISABLED_SUFFIX = ".mbp-disabled"
NGINX_LOGS = {"access": "/var/log/nginx/access.log", "error": "/var/log/nginx/error.log"}


class ConfigError(Exception):
    pass


@dataclass
class Directive:
    name: str
    args: list[str]
    file: str
    line: int
    block: list["Directive"] | None = None


@dataclass
class Reader:
    """Reads the host's files under `root`; tracks what was read and what went wrong."""

    root: str
    files: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def local(self, path: str) -> str:
        return self.root.rstrip("/") + path

    def resolve(self, path: str) -> str:
        """The host path with every symbolic link followed, as the host would."""
        pending = [p for p in path.split("/") if p]
        current = "/"
        hops = 0
        while pending:
            part = pending.pop(0)
            if part == ".":
                continue
            if part == "..":
                current = posixpath.dirname(current)
                continue
            candidate = posixpath.join(current, part)
            local = self.local(candidate)
            if os.path.islink(local):
                hops += 1
                if hops > MAX_SYMLINKS:
                    raise ConfigError(f"too many symbolic links: {path}")
                target = os.readlink(local)
                if target.startswith("/"):
                    current = "/"
                pending = [p for p in target.split("/") if p] + pending
            else:
                current = candidate
        return current

    def exists(self, path: str) -> bool:
        try:
            return os.path.exists(self.local(self.resolve(path)))
        except (OSError, ConfigError):
            return False

    def is_dir(self, path: str) -> bool:
        try:
            return os.path.isdir(self.local(self.resolve(path)))
        except (OSError, ConfigError):
            return False

    def listdir(self, path: str) -> list[str]:
        try:
            return sorted(os.listdir(self.local(self.resolve(path))))
        except (OSError, ConfigError):
            return []

    def glob(self, pattern: str) -> list[str]:
        """Host paths matching a glob(3) pattern, sorted (as nginx and Apache read them)."""
        if not _MAGIC.search(pattern):
            return [pattern] if self.exists(pattern) else []
        matches = ["/"]
        for part in [p for p in pattern.split("/") if p]:
            found: list[str] = []
            for base in matches:
                if not _MAGIC.search(part):
                    candidate = posixpath.join(base, part)
                    if self.exists(candidate):
                        found.append(candidate)
                    continue
                for name in self.listdir(base):
                    if name.startswith(".") and not part.startswith("."):
                        continue
                    if fnmatch.fnmatchcase(name, part):
                        found.append(posixpath.join(base, name))
            matches = found
        return sorted(matches)

    def read(self, path: str) -> tuple[str, str]:
        """(real host path, text) of a file; ConfigError if it cannot or may not be read."""
        if len(self.files) >= MAX_FILES:
            raise ConfigError("too many configuration files")
        real = self.resolve(path)
        local = self.local(real)
        try:
            if os.path.getsize(local) > MAX_FILE_BYTES:
                raise ConfigError(f"file too large: {path}")
            with open(local, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except PermissionError as exc:
            raise ConfigError(f"permission denied: {path}") from exc
        except OSError as exc:
            raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from exc
        self.files.add(real)
        return real, text

    def warn(self, message: str) -> None:
        if len(self.warnings) < MAX_WARNINGS and message not in self.warnings:
            self.warnings.append(message)


# --- nginx ---


def nginx_tokens(text: str) -> Iterator[tuple[str, int, bool]]:
    """(token, line, quoted): words, and the special tokens "{", "}" and ";"."""
    i, line, n = 0, 1, len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
        elif ch.isspace():
            i += 1
        elif ch == "#":
            while i < n and text[i] != "\n":
                i += 1
        elif ch in "{};":
            yield ch, line, False
            i += 1
        elif ch in "\"'":
            start_line, quote, buf = line, ch, []
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    i += 1
                if text[i] == "\n":
                    line += 1
                buf.append(text[i])
                i += 1
            i += 1
            yield "".join(buf), start_line, True
        else:
            buf = []
            while i < n and not text[i].isspace() and text[i] not in ";{}":
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i : i + 2])
                    i += 2
                elif text[i] == "$" and i + 1 < n and text[i + 1] == "{":
                    end = text.find("}", i)
                    end = n - 1 if end == -1 else end
                    buf.append(text[i : end + 1])
                    i = end + 1
                else:
                    buf.append(text[i])
                    i += 1
            yield "".join(buf), line, False


class NginxParser:
    def __init__(self, reader: Reader, prefix: str) -> None:
        self.reader = reader
        self.prefix = prefix  # relative includes are relative to the configuration prefix

    def parse_file(self, path: str, depth: int = 0) -> list[Directive]:
        real, text = self.reader.read(path)
        directives, _ = self._block(list(nginx_tokens(text)), 0, real, depth, top=True)
        return directives

    def _block(
        self, tokens: list[tuple[str, int, bool]], pos: int, path: str, depth: int, top: bool
    ) -> tuple[list[Directive], int]:
        out: list[Directive] = []
        words: list[str] = []
        line = 0
        while pos < len(tokens):
            word, word_line, quoted = tokens[pos]
            pos += 1
            special = None if quoted else word
            if special == ";":
                if words:
                    out.extend(self._directive(words, path, line, depth))
                words = []
            elif special == "{":
                block, pos = self._block(tokens, pos, path, depth, top=False)
                if words:
                    out.append(Directive(words[0], words[1:], path, line, block))
                words = []
            elif special == "}":
                if top:
                    raise ConfigError(f"unexpected }} in {path}:{word_line}")
                return out, pos
            else:
                if not words:
                    line = word_line
                words.append(word)
        if not top:
            raise ConfigError(f"unexpected end of file in {path}")
        return out, pos

    def _directive(self, words: list[str], path: str, line: int, depth: int) -> list[Directive]:
        if words[0] != "include" or len(words) != 2:
            return [Directive(words[0], words[1:], path, line)]
        if depth >= MAX_INCLUDE_DEPTH:
            self.reader.warn(f"includes nested too deeply in {path}:{line}")
            return []
        pattern = words[1]
        if not pattern.startswith("/"):
            pattern = posixpath.join(self.prefix, pattern)
        found = self.reader.glob(pattern)
        if not found and not _MAGIC.search(pattern):
            self.reader.warn(f"included file not found: {pattern} ({path}:{line})")
        out: list[Directive] = []
        for included in found:
            try:
                out.extend(self.parse_file(included, depth + 1))
            except ConfigError as exc:
                self.reader.warn(str(exc))
        return out


def _walk(directives: list[Directive], name: str) -> Iterator[Directive]:
    for d in directives:
        if d.name == name:
            yield d
        if d.block:
            yield from _walk(d.block, name)


def _nginx_port(arg: str) -> int | None:
    if arg.startswith("unix:"):
        return None
    tail = arg.rsplit("]", 1)[-1] if arg.startswith("[") else arg
    if tail.isdigit():
        return int(tail)
    if ":" in tail:
        port = tail.rsplit(":", 1)[1]
        return int(port) if port.isdigit() else None
    return 80


def _redirect(args: list[str]) -> str | None:
    if len(args) == 2 and args[0] in REDIRECT_CODES:
        return args[1]
    return None


def _nginx_log(args: list[str]) -> str | None:
    return args[0] if args and args[0].startswith("/") else None


def _nginx_logs(directives: list[Directive], inherited: dict) -> dict:
    """The access and error logs of a context, over the ones it inherits."""
    logs = dict(inherited)
    for d in directives:
        if d.name == "access_log" and d.args:
            logs["access"] = _nginx_log(d.args)
        elif d.name == "error_log" and d.args:
            logs["error"] = _nginx_log(d.args)
    return logs


def _nginx_site(
    server: Directive, upstreams: dict[str, list[str]], enabled: bool, logs: dict
) -> dict:
    body = server.block or []
    names: list[str] = []
    ports: set[int] = set()
    listen: list[str] = []
    ssl = default = False
    root = certificate = certificate_key = redirect = None
    backends: list[dict] = []
    has_listen = False
    for d in body:
        if d.name == "server_name":
            names.extend(a for a in d.args if a and a != "_" and a not in names)
        elif d.name == "listen" and d.args:
            has_listen = True
            listen.append(" ".join(d.args))
            port = _nginx_port(d.args[0])
            if port is not None:
                ports.add(port)
            flags = set(d.args[1:])
            ssl = ssl or bool(flags & {"ssl", "quic"})
            default = default or bool(flags & {"default_server", "default"})
        elif d.name == "ssl" and d.args == ["on"]:
            ssl = True
        elif d.name == "root" and d.args:
            root = d.args[0]
        elif d.name == "ssl_certificate" and d.args and certificate is None:
            certificate = d.args[0]
        elif d.name == "ssl_certificate_key" and d.args and certificate_key is None:
            certificate_key = d.args[0]
        elif d.name == "return" and redirect is None:
            redirect = _redirect(d.args)
        elif d.name == "if" and d.block and redirect is None:
            for inner in d.block:
                if inner.name == "return" and _redirect(inner.args):
                    redirect = _redirect(inner.args)
                    break
    if not has_listen:
        ports.add(80)
    for location in _walk(body, "location"):
        inner = location.block or []
        if location.args in (["/"], ["=", "/"]):
            for d in inner:
                if d.name == "root" and d.args and root is None:
                    root = d.args[0]
                if d.name == "return" and redirect is None:
                    redirect = _redirect(d.args)
    for directive, kind in NGINX_BACKENDS.items():
        for d in _walk(body, directive):
            if not d.args:
                continue
            target = d.args[0]
            host = re.sub(r"^[a-z]+://", "", target).split("/", 1)[0]
            entry = {"kind": kind, "target": target, "servers": upstreams.get(host, [])}
            if entry not in backends:
                backends.append(entry)
    return {
        "server": "nginx",
        "names": names,
        "ports": sorted(ports),
        "ssl": ssl,
        "default_server": default,
        "root": root,
        "redirect": redirect,
        "backends": backends,
        "certificate": certificate,
        "certificate_key": certificate_key,
        "listen": listen,
        "logs": _nginx_logs(body, logs),
        "file": server.file,
        "line": server.line,
        "enabled": enabled,
        "maintenance": False,
        "maintenance_page": _is_maintenance(server.file),
    }


def _is_maintenance(path: str) -> bool:
    return posixpath.basename(path).startswith(MAINTENANCE_PREFIX)


def maintenance_page(conf_dir: str, kind: str, real: str) -> str:
    """Where the panel writes the maintenance page that stands in for the file `real`."""
    name = posixpath.basename(real)
    for suffix in (DISABLED_SUFFIX, ".conf"):
        name = name.removesuffix(suffix)
    if real.startswith((f"{conf_dir}/sites-available/", f"{conf_dir}/sites-enabled/")):
        ext = ".conf" if kind == "apache" else ""
        return f"{conf_dir}/sites-available/{MAINTENANCE_PREFIX}{name}{ext}"
    return f"{conf_dir}/conf.d/{MAINTENANCE_PREFIX}{name}.conf"


def _mark_maintenance(reader: Reader, conf_dir: str, kind: str, sites: list[dict]) -> None:
    """A site under maintenance is served by its page: shown as active, in maintenance."""
    for site in sites:
        if site["maintenance_page"]:
            continue
        if reader.exists(maintenance_page(conf_dir, kind, site["file"])):
            site["maintenance"] = True
            site["enabled"] = True


def _nginx_sites(directives: list[Directive], enabled: bool, in_http: bool) -> list[dict]:
    """Every http server block; `in_http`: the directives are already inside http {}."""
    if in_http:
        blocks = directives
    else:
        blocks = [d for http in _walk(directives, "http") for d in http.block or []]
    upstreams = {
        u.args[0]: [s.args[0] for s in u.block or [] if s.name == "server" and s.args]
        for u in _walk(blocks, "upstream")
        if u.args
    }
    logs = _nginx_logs(blocks, NGINX_LOGS)
    return [
        _nginx_site(d, upstreams, enabled, logs)
        for d in blocks
        if d.name == "server" and d.block is not None
    ]


def scan_nginx(root: str) -> dict | None:
    reader = Reader(root)
    if not reader.is_dir("/etc/nginx"):
        return None
    sites: list[dict] = []
    error = None
    parser = NginxParser(reader, "/etc/nginx")
    if reader.exists(NGINX_MAIN):
        try:
            sites = _nginx_sites(parser.parse_file(NGINX_MAIN), True, in_http=False)
        except ConfigError as exc:
            error = str(exc)
    else:
        error = f"{NGINX_MAIN} not found"

    def parse(path: str) -> list[dict]:
        return _nginx_sites(parser.parse_file(path), False, in_http=True)

    sites += _disabled(reader, "/etc/nginx/sites-available", parse)
    sites += _switched_off(reader, "/etc/nginx/conf.d", parse)
    _mark_maintenance(reader, "/etc/nginx", "nginx", sites)
    return {
        "kind": "nginx",
        "config": NGINX_MAIN,
        "error": error,
        "warnings": reader.warnings,
        "files": len(reader.files),
        "sites": sites,
    }


def _switched_off(reader: Reader, directory: str, parse) -> list[dict]:
    """conf.d files the panel turned off (renamed with DISABLED_SUFFIX)."""
    out: list[dict] = []
    for name in reader.listdir(directory):
        if not name.endswith(DISABLED_SUFFIX):
            continue
        try:
            out.extend(parse(posixpath.join(directory, name)))
        except ConfigError as exc:
            reader.warn(str(exc))
    return out


def _disabled(reader: Reader, directory: str, parse) -> list[dict]:
    """Sites in a Debian-style sites-available directory that the server does not load."""
    out: list[dict] = []
    loaded = set(reader.files)
    for name in reader.listdir(directory):
        path = posixpath.join(directory, name)
        if name.startswith(".") or reader.is_dir(path):
            continue
        try:
            if reader.resolve(path) in loaded:
                continue
            out.extend(parse(path))
        except ConfigError as exc:
            reader.warn(str(exc))
    return out


# --- Apache ---


def apache_lines(text: str) -> Iterator[tuple[str, int]]:
    """Logical lines (continuations joined, comments and blank lines dropped)."""
    buf: list[str] = []
    start = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if not buf:
            start = number
        stripped = raw.strip()
        if stripped.endswith("\\"):
            buf.append(stripped[:-1])
            continue
        buf.append(stripped)
        joined = " ".join(part for part in buf if part).strip()
        buf = []
        if joined and not joined.startswith("#"):
            yield joined, start
    if buf:
        joined = " ".join(buf).strip()
        if joined and not joined.startswith("#"):
            yield joined, start


def apache_args(text: str) -> list[str]:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        if text[i] in "\"'":
            quote = text[i]
            end = i + 1
            buf = []
            while end < n and text[end] != quote:
                if text[end] == "\\" and end + 1 < n:
                    end += 1
                buf.append(text[end])
                end += 1
            out.append("".join(buf))
            i = end + 1
        else:
            end = i
            while end < n and not text[end].isspace():
                end += 1
            out.append(text[i:end])
            i = end
    return out


class ApacheParser:
    def __init__(self, reader: Reader, server_root: str) -> None:
        self.reader = reader
        self.server_root = server_root

    def parse_file(self, path: str, depth: int = 0) -> list[Directive]:
        root: list[Directive] = []
        stack: list[tuple[str, list[Directive]]] = [("", root)]
        path, source = self.reader.read(path)
        for text, line in apache_lines(source):
            if text.startswith("</"):
                name = text[2:].rstrip(">").strip().lower()
                if len(stack) > 1 and stack[-1][0] == name:
                    stack.pop()
                else:
                    self.reader.warn(f"unexpected </{name}> in {path}:{line}")
                continue
            if text.startswith("<"):
                inner = text[1:].rstrip()
                inner = inner[:-1] if inner.endswith(">") else inner
                words = apache_args(inner)
                if not words:
                    continue
                section = Directive(words[0].lower(), words[1:], path, line, [])
                stack[-1][1].append(section)
                stack.append((section.name, section.block))  # type: ignore[arg-type]
                continue
            words = apache_args(text)
            if not words:
                continue
            name = words[0].lower()
            if name == "serverroot" and len(words) > 1 and depth == 0:
                self.server_root = words[1].rstrip("/") or "/"
            if name in ("include", "includeoptional") and len(words) > 1:
                stack[-1][1].extend(self._include(words[1], name, path, line, depth))
                continue
            stack[-1][1].append(Directive(name, words[1:], path, line))
        if len(stack) > 1:
            self.reader.warn(f"<{stack[-1][0]}> not closed in {path}")
        return root

    def _include(
        self, pattern: str, name: str, path: str, line: int, depth: int
    ) -> list[Directive]:
        if depth >= MAX_INCLUDE_DEPTH:
            self.reader.warn(f"includes nested too deeply in {path}:{line}")
            return []
        if not pattern.startswith("/"):
            pattern = posixpath.join(self.server_root, pattern)
        found = self.reader.glob(pattern.rstrip("/") or "/")
        if not found and name == "include" and not _MAGIC.search(pattern):
            self.reader.warn(f"included file not found: {pattern} ({path}:{line})")
        out: list[Directive] = []
        for included in found:
            for file in self._files(included):
                try:
                    out.extend(self.parse_file(file, depth + 1))
                except ConfigError as exc:
                    self.reader.warn(str(exc))
        return out

    def _files(self, path: str) -> list[str]:
        """A file, or every file under a directory (Apache includes directories whole)."""
        if not self.reader.is_dir(path):
            return [path]
        out: list[str] = []
        for name in self.reader.listdir(path):
            if not name.startswith("."):
                out.extend(self._files(posixpath.join(path, name)))
        return out


def _apache_host(name: str) -> str:
    name = re.sub(r"^[a-z]+://", "", name.strip().lower())
    if name.startswith("["):
        return name
    return name.rsplit(":", 1)[0] if name.count(":") == 1 else name


class ApacheLogs:
    """Resolves Apache log paths: ${APACHE_LOG_DIR} and paths relative to ServerRoot."""

    def __init__(self, server_root: str, log_dir: str) -> None:
        self.server_root = server_root
        self.log_dir = log_dir
        self.defaults: dict = {"access": None, "error": None}

    def path(self, value: str) -> str | None:
        if not value or value.startswith("|") or value.startswith("syslog"):
            return None
        value = value.replace("${APACHE_LOG_DIR}", self.log_dir)
        if "$" in value:
            return None
        return value if value.startswith("/") else posixpath.join(self.server_root, value)

    def of(self, directives: list[Directive], inherited: dict) -> dict:
        logs = dict(inherited)
        for d in directives:
            if d.name in ("customlog", "transferlog") and d.args:
                logs["access"] = self.path(d.args[0])
            elif d.name == "errorlog" and d.args:
                logs["error"] = self.path(d.args[0])
        return logs


def _apache_site(vhost: Directive, enabled: bool, logs: dict, resolver: ApacheLogs) -> dict:
    body = vhost.block or []
    names: list[str] = []
    ports: set[int] = set()
    ssl = False
    root = certificate = certificate_key = certificate_chain = redirect = None
    backends: list[dict] = []
    for address in vhost.args:
        port = address.rsplit(":", 1)[1] if ":" in address.rsplit("]", 1)[-1] else ""
        if port.isdigit():
            ports.add(int(port))
    for d in body:
        if d.name in ("servername", "serveralias"):
            for arg in d.args:
                host = _apache_host(arg)
                if host and host not in names:
                    names.append(host)
        elif d.name == "documentroot" and d.args:
            root = d.args[0]
        elif d.name == "sslengine" and d.args and d.args[0].lower() == "on":
            ssl = True
        elif d.name == "sslcertificatefile" and d.args and certificate is None:
            certificate = d.args[0]
        elif d.name == "sslcertificatekeyfile" and d.args and certificate_key is None:
            certificate_key = d.args[0]
        elif d.name == "sslcertificatechainfile" and d.args and certificate_chain is None:
            certificate_chain = d.args[0]
        elif d.name in ("redirect", "redirectpermanent") and redirect is None:
            args = d.args if d.name == "redirect" else ["permanent", *d.args]
            if len(args) == 3 and args[1] == "/":
                redirect = args[2]
    for d in _walk(body, "proxypass"):
        for arg in d.args:
            if "://" in arg:
                entry = {"kind": "proxy", "target": arg, "servers": []}
                if entry not in backends:
                    backends.append(entry)
                break
    for d in _walk(body, "sethandler"):
        if d.args and d.args[0].lower().startswith("proxy:"):
            target = d.args[0][len("proxy:") :]
            kind = "fastcgi" if "fcgi://" in target else "proxy"
            entry = {"kind": kind, "target": target, "servers": []}
            if entry not in backends:
                backends.append(entry)
    return {
        "server": "apache",
        "names": names,
        "ports": sorted(ports),
        "ssl": ssl,
        "default_server": any(a.lower().startswith("_default_") for a in vhost.args),
        "root": root,
        "redirect": redirect,
        "backends": backends,
        "certificate": certificate,
        "certificate_key": certificate_key,
        "certificate_chain": certificate_chain,
        "addresses": list(vhost.args),
        "logs": resolver.of(body, logs),
        "file": vhost.file,
        "line": vhost.line,
        "enabled": enabled,
        "maintenance": False,
        "maintenance_page": _is_maintenance(vhost.file),
    }


def _apache_sites(
    directives: list[Directive], enabled: bool, resolver: ApacheLogs, top: bool
) -> list[dict]:
    if top:
        # The main configuration's logs apply to every virtual host, disabled ones too.
        resolver.defaults = resolver.of(directives, resolver.defaults)
    defaults = resolver.defaults
    return [_apache_site(d, enabled, defaults, resolver) for d in _walk(directives, "virtualhost")]


def _apache_log_dir(reader: Reader, server_root: str) -> str:
    """APACHE_LOG_DIR from Debian's envvars file."""
    default = "/var/log/apache2" if server_root == "/etc/apache2" else "/var/log/httpd"
    try:
        _, text = reader.read(posixpath.join(server_root, "envvars"))
    except ConfigError:
        return default
    match = re.search(r"^\s*export\s+APACHE_LOG_DIR=([^\s$#]+)", text, re.MULTILINE)
    return match.group(1) if match else default


def scan_apache(root: str) -> dict | None:
    reader = Reader(root)
    main = next((path for path in APACHE_MAINS if reader.exists(path)), None)
    if main is None:
        if reader.is_dir("/etc/apache2") or reader.is_dir("/etc/httpd"):
            main = APACHE_MAINS[0] if reader.is_dir("/etc/apache2") else APACHE_MAINS[1]
            return {
                "kind": "apache",
                "config": main,
                "error": f"{main} not found",
                "warnings": [],
                "files": 0,
                "sites": [],
            }
        return None
    server_root = "/etc/apache2" if main.startswith("/etc/apache2/") else "/etc/httpd"
    resolver = ApacheLogs(server_root, _apache_log_dir(reader, server_root))
    reader.files.clear()  # envvars is not configuration
    parser = ApacheParser(reader, server_root)
    sites: list[dict] = []
    error = None
    try:
        sites = _apache_sites(parser.parse_file(main), True, resolver, top=True)
    except ConfigError as exc:
        error = str(exc)
    resolver.server_root = parser.server_root

    def parse(path: str) -> list[dict]:
        return _apache_sites(parser.parse_file(path), False, resolver, top=False)

    sites += _disabled(reader, "/etc/apache2/sites-available", parse)
    sites += _switched_off(reader, posixpath.join(server_root, "conf.d"), parse)
    _mark_maintenance(reader, server_root, "apache", sites)
    return {
        "kind": "apache",
        "config": main,
        "error": error,
        "warnings": reader.warnings,
        "files": len(reader.files),
        "sites": sites,
    }


def scan(root: str) -> dict:
    """The web servers found under `root` (the host's / as mounted) and their sites."""
    if not os.path.isdir(os.path.join(root, "etc")):
        return {"available": False, "servers": []}
    servers = [found for found in (scan_nginx(root), scan_apache(root)) if found]
    return {"available": True, "servers": servers}
