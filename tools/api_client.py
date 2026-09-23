"""
NEO API Client

Universal REST API client with saved endpoints, multiple auth modes,
and approval gates.

Usage:
    from neo_code.tools.api_client import APIClient

    api = APIClient(confirm_fn=my_confirm)
    api.add_endpoint("github", "https://api.github.com")
    api.get("/user", endpoint="github", auth={"type": "bearer", "token": "..."})
    api.post("/repos", endpoint="github", json_data={"name": "test"})
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    requests = None
    REQUESTS_OK = False


# ============ Config paths ============

CONFIG_DIR = Path.home() / ".neo" / "connections"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
ENDPOINTS_FILE = CONFIG_DIR / "api_endpoints.json"


# ============ API Client ============

class APIClient:
    """Universal REST API client with saved endpoints."""

    def __init__(
        self,
        cprint_fn: Optional[Callable] = None,
        confirm_fn: Optional[Callable] = None,
    ):
        self.cprint = cprint_fn or print
        self.confirm = confirm_fn or (lambda *a, **k: True)
        self.endpoints: Dict[str, Dict] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self):
        try:
            if ENDPOINTS_FILE.exists():
                with open(ENDPOINTS_FILE, "r", encoding="utf-8") as f:
                    self.endpoints = json.load(f)
        except Exception:
            self.endpoints = {}

    def _save(self):
        try:
            with open(ENDPOINTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.endpoints, f, indent=2)
        except Exception as e:
            self.cprint(f"[!] Could not save endpoints: {e}")

    # -- headers ----------------------------------------------------------

    def _build_headers(
        self,
        headers: Optional[Dict] = None,
        auth: Optional[Dict] = None,
    ) -> Dict:
        h = {"User-Agent": "NEO-API/1.0", "Accept": "application/json"}
        if headers:
            h.update(headers)
        if auth:
            atype = auth.get("type", "").lower()
            if atype == "bearer":
                h["Authorization"] = f"Bearer {auth.get('token', '')}"
            elif atype == "basic":
                user = auth.get("username", "")
                pwd = auth.get("password", "")
                token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
                h["Authorization"] = f"Basic {token}"
            elif atype == "api_key":
                h[auth.get("header", "X-API-Key")] = auth.get("key", "")
        return h

    # -- endpoint management ----------------------------------------------

    def add_endpoint(
        self,
        name: str,
        base_url: str,
        headers: Optional[Dict] = None,
        auth: Optional[Dict] = None,
    ) -> str:
        self.endpoints[name] = {
            "base_url": base_url,
            "headers": headers or {},
            "auth": auth or {},
        }
        self._save()
        return f"Endpoint '{name}' saved: {base_url}"

    def list_endpoints(self) -> str:
        if not self.endpoints:
            return "No saved endpoints."
        lines = ["Saved API endpoints:"]
        for name, cfg in self.endpoints.items():
            lines.append(f"  {name:<20} {cfg.get('base_url', '?')}")
        return "\n".join(lines)

    def remove_endpoint(self, name: str) -> str:
        if name in self.endpoints:
            del self.endpoints[name]
            self._save()
            return f"Removed: {name}"
        return f"Not found: {name}"

    # -- requests ---------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
        json_data: Any = None,
        data: Any = None,
        auth: Optional[Dict] = None,
        timeout: int = 30,
        endpoint: Optional[str] = None,
    ) -> str:
        if not REQUESTS_OK:
            return "Error: requests not installed. Run: pip install requests"

        method = method.upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            return f"Unsupported method: {method}"

        # Resolve endpoint config
        if endpoint and endpoint in self.endpoints:
            cfg = self.endpoints[endpoint]
            base = cfg.get("base_url", "")
            if base and not url.startswith("http"):
                url = base.rstrip("/") + "/" + url.lstrip("/")
            h = dict(cfg.get("headers", {}))
            h.update(headers or {})
            headers = h
            a = dict(cfg.get("auth", {}))
            a.update(auth or {})
            auth = a

        if not url.startswith("http"):
            return f"Error: invalid URL: {url}"

        final_headers = self._build_headers(headers, auth)

        # Approval gate
        preview = f"{method} {url}"
        if params:
            preview += f"\nParams: {json.dumps(params)[:200]}"
        if json_data is not None:
            preview += f"\nBody: {json.dumps(json_data)[:300]}"

        approved = self.confirm(f"HTTP {method}", details=preview)
        if not approved:
            return "Cancelled by user."

        # Execute
        try:
            t0 = time.time()
            r = requests.request(
                method=method,
                url=url,
                headers=final_headers,
                params=params,
                json=json_data,
                data=data,
                timeout=timeout,
                allow_redirects=True,
            )
            elapsed = (time.time() - t0) * 1000

            parts = [f"HTTP {r.status_code} {r.reason}  ({elapsed:.0f}ms)"]
            parts.append(f"URL: {r.url}")
            parts.append(f"Content-Type: {r.headers.get('Content-Type', '?')}")

            ctype = r.headers.get("Content-Type", "")
            if "json" in ctype:
                try:
                    data_out = r.json()
                    pretty = json.dumps(data_out, indent=2, ensure_ascii=False)
                    if len(pretty) > 5000:
                        pretty = pretty[:5000] + "\n... (truncated)"
                    parts.append(f"\n--- JSON ---\n{pretty}")
                except Exception:
                    text = r.text[:3000]
                    parts.append(f"\n--- TEXT ---\n{text}")
            else:
                text = r.text
                if len(text) > 3000:
                    text = text[:3000] + "\n... (truncated)"
                parts.append(f"\n--- BODY ---\n{text}")

            return "\n".join(parts)

        except requests.exceptions.Timeout:
            return f"HTTP {method} {url}  TIMEOUT after {timeout}s"
        except requests.exceptions.ConnectionError as e:
            return f"HTTP {method} {url}  CONNECTION ERROR: {e}"
        except Exception as e:
            return f"HTTP {method} {url}  ERROR: {type(e).__name__}: {e}"

    # -- shortcuts --------------------------------------------------------

    def get(self, url: str, **kwargs) -> str:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> str:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> str:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs) -> str:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs) -> str:
        return self.request("DELETE", url, **kwargs)

    def ping(self, url: str) -> str:
        if not REQUESTS_OK:
            return "requests not installed"
        try:
            t0 = time.time()
            r = requests.head(url, timeout=10, allow_redirects=True)
            elapsed = (time.time() - t0) * 1000
            return f"{url}  {r.status_code} ({elapsed:.0f}ms)"
        except Exception as e:
            return f"{url}  ERROR: {e}"


# ============ NEO Tools (for agent integration) ============

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


# Shared client instance
_api = APIClient()


class APIAddEndpointTool(Tool):
    name = "api_add_endpoint"
    description = "Save a named REST API endpoint (base URL + optional auth). Reusable in api_get/api_post."
    permission = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Endpoint name (e.g. 'github')"},
            "base_url": {"type": "string", "description": "Base URL (e.g. 'https://api.github.com')"},
            "auth_type": {"type": "string", "description": "Auth type: bearer, basic, api_key, or none", "enum": ["bearer", "basic", "api_key", "none"]},
            "token": {"type": "string", "description": "Bearer token (if auth_type=bearer)"},
            "username": {"type": "string", "description": "Basic auth username"},
            "password": {"type": "string", "description": "Basic auth password"},
            "api_key": {"type": "string", "description": "API key value (if auth_type=api_key)"},
            "api_key_header": {"type": "string", "description": "Header name for API key (default X-API-Key)"},
        },
        "required": ["name", "base_url"],
    }

    def execute(self, args):
        auth_type = args.get("auth_type", "none")
        auth = {}
        if auth_type == "bearer":
            auth = {"type": "bearer", "token": args.get("token", "")}
        elif auth_type == "basic":
            auth = {"type": "basic", "username": args.get("username", ""), "password": args.get("password", "")}
        elif auth_type == "api_key":
            auth = {"type": "api_key", "key": args.get("api_key", ""), "header": args.get("api_key_header", "X-API-Key")}

        result = _api.add_endpoint(
            name=args["name"],
            base_url=args["base_url"],
            auth=auth,
        )
        return {"result": result}


class APIListEndpointsTool(Tool):
    name = "api_list_endpoints"
    description = "List saved REST API endpoints."
    permission = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, args):
        return {"endpoints": _api.list_endpoints()}


class APIRemoveEndpointTool(Tool):
    name = "api_remove_endpoint"
    description = "Remove a saved REST API endpoint."
    permission = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Endpoint name to remove"},
        },
        "required": ["name"],
    }

    def execute(self, args):
        return {"result": _api.remove_endpoint(args["name"])}


class APIGetTool(Tool):
    name = "api_get"
    description = "HTTP GET request. Use 'endpoint' to prepend a saved base URL. Requires approval."
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL or path (e.g. '/user' if endpoint set)"},
            "endpoint": {"type": "string", "description": "Saved endpoint name (optional)"},
            "params": {"type": "object", "description": "Query parameters"},
            "timeout": {"type": "integer", "description": "Timeout seconds (default 30)"},
        },
        "required": ["url"],
    }

    def execute(self, args):
        result = _api.get(
            args["url"],
            endpoint=args.get("endpoint"),
            params=args.get("params"),
            timeout=args.get("timeout", 30),
        )
        if result.startswith("Cancelled") or "ERROR" in result or "TIMEOUT" in result:
            raise RuntimeError(result)
        return {"response": result}


class APIPostTool(Tool):
    name = "api_post"
    description = "HTTP POST request with JSON body. Requires approval."
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL or path"},
            "endpoint": {"type": "string", "description": "Saved endpoint name (optional)"},
            "json_data": {"type": "object", "description": "JSON body"},
            "timeout": {"type": "integer", "description": "Timeout seconds (default 30)"},
        },
        "required": ["url"],
    }

    def execute(self, args):
        result = _api.post(
            args["url"],
            endpoint=args.get("endpoint"),
            json_data=args.get("json_data"),
            timeout=args.get("timeout", 30),
        )
        if result.startswith("Cancelled") or "ERROR" in result or "TIMEOUT" in result:
            raise RuntimeError(result)
        return {"response": result}


class APIRequestTool(Tool):
    name = "api_request"
    description = "Generic HTTP request (GET/POST/PUT/PATCH/DELETE). Use for non-GET/POST methods."
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "description": "HTTP method", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]},
            "url": {"type": "string", "description": "URL or path"},
            "endpoint": {"type": "string", "description": "Saved endpoint name (optional)"},
            "params": {"type": "object", "description": "Query parameters"},
            "json_data": {"type": "object", "description": "JSON body"},
            "timeout": {"type": "integer", "description": "Timeout seconds (default 30)"},
        },
        "required": ["method", "url"],
    }

    def execute(self, args):
        result = _api.request(
            args["method"],
            args["url"],
            endpoint=args.get("endpoint"),
            params=args.get("params"),
            json_data=args.get("json_data"),
            timeout=args.get("timeout", 30),
        )
        if result.startswith("Cancelled") or "ERROR" in result or "TIMEOUT" in result:
            raise RuntimeError(result)
        return {"response": result}


def build_api_tools() -> list[Tool]:
    """Instantiate all API client tools (shared client)."""
    return [
        APIAddEndpointTool(),
        APIListEndpointsTool(),
        APIRemoveEndpointTool(),
        APIGetTool(),
        APIPostTool(),
        APIRequestTool(),
    ]
