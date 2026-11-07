"""Public HTTPS-only, read-only page retrieval with DNS pinning and bounded results.

No cookies, proxies, user secrets, internal hosts, redirects to non-HTTPS, or JS.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, urldefrag

MAX_BODY = 400_000


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, **kwargs):
        super().__init__(host, **kwargs)
        self._pin = ip

    def connect(self):
        raw = socket.create_connection((self._pin, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def validate_public_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or len(url) > 1800:
        raise ValueError("Invalid URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Only public HTTPS URLs without credentials/fragments")
    if parsed.port not in (None, 443):
        raise ValueError("Only HTTPS port 443 is supported")
    host = parsed.hostname.lower().rstrip(".")
    if host in ("localhost", "metadata.google.internal") or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Internal host blocked")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?", host) or "." not in host:
            raise ValueError("Invalid public hostname")
    else:
        raise ValueError("IP-address targets are blocked")
    ips = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Hostname resolves to blocked or private IP")
    return host, sorted(ips)[0]


def _fetch(url: str, redirects: int = 0) -> tuple[str, str, bytes]:
    if redirects > 3:
        raise ValueError("Too many redirects")
    host, ip = validate_public_url(url)
    parts = urlsplit(url)
    target = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    conn = PinnedHTTPSConnection(host, ip, timeout=8, context=ssl.create_default_context())
    try:
        conn.request("GET", target, headers={"Host": host, "User-Agent": "SatoshiReadOnlyResearch/0.4", "Accept": "text/html,text/plain,application/json", "Accept-Encoding": "identity", "Connection": "close"})
        resp = conn.getresponse()
        if resp.status in (301, 302, 303, 307, 308):
            location = resp.getheader("Location")
            if not location:
                raise ValueError("Redirect missing Location")
            next_url, _ = urldefrag(urljoin(url, location))
            return _fetch(next_url, redirects + 1)
        if resp.status != 200:
            raise ValueError(f"Page HTTP status {resp.status}")
        content_type = (resp.getheader("Content-Type") or "").split(";", 1)[0].lower().strip()
        if content_type not in ("text/html", "text/plain", "application/json", "application/xhtml+xml"):
            raise ValueError("Unsupported content type")
        data = resp.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise ValueError("Page larger than 400 KB")
        return url, content_type, data
    finally:
        conn.close()


class PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.description = ""
        self.headings = []
        self.links = []
        self.chunks = []
        self.stack = []
        self.link_url = None
        self.link_text = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self.stack.append(tag)
        if tag == "meta" and attrs.get("name", "").lower() == "description":
            self.description = (attrs.get("content") or "")[:360]
        if tag == "a" and len(self.links) < 75:
            href = attrs.get("href", "")
            absolute, _ = urldefrag(urljoin(self.base_url, href))
            if absolute.startswith("https://"):
                self.link_url = absolute
                self.link_text = ""
        if tag in ("title", "h1", "h2", "h3"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "a" and self.link_url:
            self.links.append({"text": self.link_text[:90], "url": self.link_url})
            self.link_url = None
        if tag in ("script", "style", "noscript", "svg", "title", "h1", "h2", "h3"):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i] == tag:
                    self.stack.pop(i)
                    break

    def handle_data(self, data):
        if any(x in self.stack for x in ("script", "style", "noscript", "svg")):
            return
        clean = " ".join(data.split())
        if not clean:
            return
        if self.link_url:
            self.link_text += (" " + clean)
        if "title" in self.stack:
            self.title += clean + " "
        elif any(h in self.stack for h in ("h1", "h2", "h3")):
            self.headings.append(clean[:200])
        else:
            self.chunks.append(clean)


def fetch_public_page(url: str) -> dict:
    actual, kind, data = _fetch(url)
    decoded = data.decode("utf-8", errors="replace")
    if kind in ("text/html", "application/xhtml+xml"):
        doc = PageParser(actual)
        doc.feed(decoded)
        return {"url": actual, "content_type": kind, "title": doc.title.strip()[:200],
                "text": " ".join(doc.chunks)[:9000], "links": doc.links[:35]}
    return {"url": actual, "content_type": kind, "text": decoded[:9000]}


def scrape_public_page(url: str, fetcher=fetch_public_page) -> dict:
    page = fetcher(url)
    return {"url": page.get("url", url), "title": page.get("title", ""),
            "text": page.get("text", "")[:6000], "links": page.get("links", [])[:40]}


def github_public_repo(name: str, fetcher=fetch_public_page) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}", name):
        raise ValueError("Expected public GitHub owner/repo")
    page = fetcher("https://api.github.com/repos/" + name)
    raw = page.get("text", "")
    result = json.loads(raw)
    return {"name": result.get("full_name"), "description": result.get("description"),
            "language": result.get("language"), "html_url": result.get("html_url"),
            "default_branch": result.get("default_branch"), "private": result.get("private")}
