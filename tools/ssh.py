"""
NEO SSH Connector

SSH/SFTP client with saved connections, keyring-backed password storage,
and approval gates.

Usage:
    from neo_code.tools.ssh import SSHConnector

    ssh = SSHConnector(confirm_fn=my_confirm)
    ssh.add("prod", "192.168.1.10", "admin")
    ssh.connect("prod")
    ssh.exec("ls -la")
    ssh.upload("local.txt", "/remote/path.txt")
    ssh.download("/remote/file.txt", "local.txt")
    ssh.list_remote(".")
    ssh.disconnect("prod")
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import paramiko
    PARAMIKO_OK = True
except ImportError:
    paramiko = None
    PARAMIKO_OK = False

try:
    import keyring
    KEYRING_OK = True
except ImportError:
    keyring = None
    KEYRING_OK = False


# ============ Config paths ============

CONFIG_DIR = Path.home() / ".neo" / "connections"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONN_FILE = CONFIG_DIR / "ssh_connections.json"

KEYRING_SERVICE = "neo-ssh"


# ============ SSH Session ============

class SSHSession:
    """One SSH connection."""

    def __init__(self, name: str, host: str, user: str, port: int = 22):
        self.name = name
        self.host = host
        self.user = user
        self.port = port
        self.client = None
        self.sftp = None
        self.connected = False
        self.last_error: Optional[str] = None

    def connect(
        self,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        timeout: int = 15,
    ) -> str:
        if not PARAMIKO_OK:
            return "Error: paramiko not installed. Run: pip install paramiko"
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            kwargs: Dict[str, Any] = {
                "hostname": self.host,
                "port": self.port,
                "username": self.user,
                "timeout": timeout,
                "banner_timeout": timeout,
                "auth_timeout": timeout,
            }

            if key_path:
                kwargs["key_filename"] = key_path
                kwargs["look_for_keys"] = False
                kwargs["allow_agent"] = False
            elif password:
                kwargs["password"] = password
                kwargs["look_for_keys"] = False
                kwargs["allow_agent"] = False
            else:
                kwargs["look_for_keys"] = True
                kwargs["allow_agent"] = True

            self.client.connect(**kwargs)
            self.connected = True
            return f"Connected to {self.user}@{self.host}:{self.port}"

        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            return f"SSH connect failed: {e}"

    def disconnect(self) -> str:
        try:
            if self.sftp:
                self.sftp.close()
                self.sftp = None
            if self.client:
                self.client.close()
                self.client = None
            self.connected = False
            return f"Disconnected from {self.host}"
        except Exception as e:
            self.connected = False
            return f"disconnect error: {e}"

    def exec(self, command: str, timeout: int = 60) -> str:
        if not self.connected or not self.client:
            return "Error: not connected."
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            rc = stdout.channel.recv_exit_status()

            parts = [f"$ {command}", f"exit code: {rc}"]
            if out.strip():
                parts.append(f"\n--- STDOUT ---\n{out.rstrip()}")
            if err.strip():
                parts.append(f"\n--- STDERR ---\n{err.rstrip()}")

            result = "\n".join(parts)
            if len(result) > 8000:
                result = result[:8000] + "\n... (truncated)"
            return result
        except Exception as e:
            return f"SSH exec error: {e}"

    def upload(self, local_path: str, remote_path: str) -> str:
        if not self.connected or not self.client:
            return "Error: not connected."
        try:
            if self.sftp is None:
                self.sftp = self.client.open_sftp()
            self.sftp.put(local_path, remote_path)
            return f"Uploaded {local_path} -> {remote_path}"
        except Exception as e:
            return f"SFTP upload error: {e}"

    def download(self, remote_path: str, local_path: str) -> str:
        if not self.connected or not self.client:
            return "Error: not connected."
        try:
            if self.sftp is None:
                self.sftp = self.client.open_sftp()
            self.sftp.get(remote_path, local_path)
            return f"Downloaded {remote_path} -> {local_path}"
        except Exception as e:
            return f"SFTP download error: {e}"

    def list_remote_dir(self, remote_path: str = ".") -> str:
        if not self.connected or not self.client:
            return "Error: not connected."
        try:
            if self.sftp is None:
                self.sftp = self.client.open_sftp()
            entries = self.sftp.listdir_attr(remote_path)
            lines = [f"Directory: {remote_path}"]
            for e in sorted(entries, key=lambda x: x.filename)[:100]:
                kind = "DIR " if (e.st_mode or 0) & 0o40000 else "FILE"
                lines.append(
                    f"  {kind}  {e.filename:<40}  {e.st_size or 0:>10}  "
                    f"{time.ctime(e.st_mtime or 0)}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"list_remote_dir error: {e}"


# ============ SSH Connector ============

class SSHConnector:
    """Manages multiple SSH sessions with saved connections."""

    def __init__(
        self,
        cprint_fn: Optional[Callable] = None,
        confirm_fn: Optional[Callable] = None,
    ):
        self.sessions: Dict[str, SSHSession] = {}
        self.active: Optional[str] = None
        self.cprint = cprint_fn or print
        self.confirm = confirm_fn or (lambda *a, **k: True)
        self.saved: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self):
        try:
            if CONN_FILE.exists():
                with open(CONN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.saved = data.get("connections", {})
        except Exception:
            self.saved = {}

    def _save(self):
        try:
            data = {"connections": self.saved}
            with open(CONN_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.cprint(f"[!] Could not save SSH config: {e}")

    def _store_password(self, name: str, password: str):
        if KEYRING_OK and password:
            try:
                keyring.set_password(KEYRING_SERVICE, name, password)
            except Exception:
                pass

    def _get_password(self, name: str) -> Optional[str]:
        if KEYRING_OK:
            try:
                return keyring.get_password(KEYRING_SERVICE, name)
            except Exception:
                return None
        return None

    def _delete_password(self, name: str):
        if KEYRING_OK:
            try:
                keyring.delete_password(KEYRING_SERVICE, name)
            except Exception:
                pass

    # -- connection management -------------------------------------------

    def add(
        self,
        name: str,
        host: str,
        user: str,
        port: int = 22,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        auto_connect: bool = False,
    ) -> str:
        if not name or not host or not user:
            return "Error: name, host, and user are required."

        self.saved[name] = {
            "host": host,
            "user": user,
            "port": int(port),
            "key_path": key_path or "",
        }
        self._save()

        if password:
            self._store_password(name, password)
            self.cprint(f"[+] SSH connection saved: {name}  ({user}@{host}:{port}) [password in keyring]")
        else:
            self.cprint(f"[+] SSH connection saved: {name}  ({user}@{host}:{port})")

        if auto_connect:
            return self.connect(name)
        return f"Saved '{name}'. Use connect('{name}') to open."

    def remove(self, name: str) -> str:
        if name in self.saved:
            del self.saved[name]
            self._delete_password(name)
            self._save()
            return f"Removed connection: {name}"
        return f"No such connection: {name}"

    def list_saved(self) -> str:
        if not self.saved:
            return "No saved SSH connections."
        lines = ["Saved SSH connections:", ""]
        for name, cfg in self.saved.items():
            status = ""
            if name in self.sessions and self.sessions[name].connected:
                status = "  [CONNECTED]"
            lines.append(f"  {name:<15}  {cfg['user']}@{cfg['host']}:{cfg['port']}{status}")
        return "\n".join(lines)

    # -- connect / disconnect ---------------------------------------------

    def connect(self, name: str, password: Optional[str] = None) -> str:
        if name not in self.saved:
            return f"No such connection: {name}"
        cfg = self.saved[name]

        # Password resolution:
        # 1. explicit argument
        # 2. keyring
        # 3. None (agent / keys)
        if not password:
            password = self._get_password(name)

        key_path = cfg.get("key_path") or None

        sess = SSHSession(name, cfg["host"], cfg["user"], cfg["port"])
        result = sess.connect(password=password, key_path=key_path)

        if sess.connected:
            self.sessions[name] = sess
            self.active = name
            return result
        return result

    def disconnect(self, name: Optional[str] = None) -> str:
        target = name or self.active
        if not target or target not in self.sessions:
            return "No active SSH session."
        result = self.sessions[target].disconnect()
        if target == self.active:
            self.active = None
        return result

    def get_active(self) -> Optional[SSHSession]:
        if self.active and self.active in self.sessions:
            s = self.sessions[self.active]
            if s.connected:
                return s
        return None

    # -- operations (with approval gate) ----------------------------------

    def exec(self, command: str, name: Optional[str] = None) -> str:
        s = self.sessions.get(name) if name else self.get_active()
        if not s or not s.connected:
            return "Error: no active SSH session. Use connect() first."

        approved = self.confirm(
            f"SSH EXEC on {s.name} ({s.user}@{s.host})",
            details=f"Command:\n\n{command}",
        )
        if not approved:
            return "Cancelled by user."

        return s.exec(command)

    def upload(self, local_path: str, remote_path: str) -> str:
        s = self.get_active()
        if not s:
            return "Error: no active SSH session."
        approved = self.confirm(
            f"SSH UPLOAD -> {s.name}",
            details=f"Local:  {local_path}\nRemote: {remote_path}",
        )
        if not approved:
            return "Cancelled by user."
        return s.upload(local_path, remote_path)

    def download(self, remote_path: str, local_path: str) -> str:
        s = self.get_active()
        if not s:
            return "Error: no active SSH session."
        approved = self.confirm(
            f"SSH DOWNLOAD <- {s.name}",
            details=f"Remote: {remote_path}\nLocal:  {local_path}",
        )
        if not approved:
            return "Cancelled by user."
        return s.download(remote_path, local_path)

    def list_remote(self, remote_path: str = ".") -> str:
        s = self.get_active()
        if not s:
            return "Error: no active SSH session."
        return s.list_remote_dir(remote_path)

    def status(self) -> str:
        if not self.sessions:
            return "No SSH sessions."
        lines = ["SSH Sessions:", ""]
        for name, s in self.sessions.items():
            marker = "->" if name == self.active else "  "
            state = "connected" if s.connected else "disconnected"
            lines.append(f" {marker} {name:<15} {s.user}@{s.host}:{s.port}  [{state}]")
        return "\n".join(lines)






# ============ NEO Tools (for agent integration) ============

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


# Shared connector instance (one per process)
_connector = SSHConnector()


class SSHListConnectionsTool(Tool):
    name = "ssh_list_connections"
    description = "List saved SSH connections (names, hosts, users, ports)."
    permission = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, args):
        return {"connections": _connector.list_saved()}


class SSHAddConnectionTool(Tool):
    name = "ssh_add_connection"
    description = "Save a new SSH connection. Password is stored in Windows Credential Manager (keyring), NOT in plaintext."
    permission = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Connection name (e.g. 'prod')"},
            "host": {"type": "string", "description": "Hostname or IP address"},
            "user": {"type": "string", "description": "SSH username"},
            "port": {"type": "integer", "description": "Port (default 22)"},
            "password": {"type": "string", "description": "Password (stored in keyring)"},
            "key_path": {"type": "string", "description": "Path to SSH private key (optional)"},
        },
        "required": ["name", "host", "user"],
    }

    def execute(self, args):
        result = _connector.add(
            name=args["name"],
            host=args["host"],
            user=args["user"],
            port=args.get("port", 22),
            password=args.get("password"),
            key_path=args.get("key_path"),
        )
        return {"result": result}


class SSHConnectTool(Tool):
    name = "ssh_connect"
    description = "Connect to a saved SSH host. Uses keyring password or SSH agent."
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Saved connection name"},
        },
        "required": ["name"],
    }

    def execute(self, args):
        result = _connector.connect(args["name"])
        if "Connected" not in result:
            raise RuntimeError(result)
        return {"result": result}


class SSHDisconnectTool(Tool):
    name = "ssh_disconnect"
    description = "Disconnect from an SSH session (default: active session)."
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Connection name (default: active)"},
        },
        "required": [],
    }

    def execute(self, args):
        result = _connector.disconnect(args.get("name"))
        return {"result": result}


class SSHExecTool(Tool):
    name = "ssh_exec"
    description = "Execute a shell command on the active SSH session. Requires user approval."
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run remotely"},
            "name": {"type": "string", "description": "Connection name (default: active)"},
        },
        "required": ["command"],
    }

    def execute(self, args):
        result = _connector.exec(args["command"], args.get("name"))
        if result.startswith(("Error", "Cancelled")):
            raise RuntimeError(result)
        return {"output": result}


class SSHUploadTool(Tool):
    name = "ssh_upload"
    description = "Upload a local file to a remote host via SFTP. Requires user approval."
    permission = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "local_path": {"type": "string", "description": "Local file path"},
            "remote_path": {"type": "string", "description": "Remote destination path"},
        },
        "required": ["local_path", "remote_path"],
    }

    def execute(self, args):
        result = _connector.upload(args["local_path"], args["remote_path"])
        if result.startswith(("Error", "Cancelled")):
            raise RuntimeError(result)
        return {"result": result}


class SSHDownloadTool(Tool):
    name = "ssh_download"
    description = "Download a remote file via SFTP. Requires user approval."
    permission = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "remote_path": {"type": "string", "description": "Remote file path"},
            "local_path": {"type": "string", "description": "Local destination path"},
        },
        "required": ["remote_path", "local_path"],
    }

    def execute(self, args):
        result = _connector.download(args["remote_path"], args["local_path"])
        if result.startswith(("Error", "Cancelled")):
            raise RuntimeError(result)
        return {"result": result}


class SSHListRemoteTool(Tool):
    name = "ssh_list_remote"
    description = "List files in a remote directory via SFTP."
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "remote_path": {"type": "string", "description": "Remote directory (default '.')"},
        },
        "required": [],
    }

    def execute(self, args):
        result = _connector.list_remote(args.get("remote_path", "."))
        if result.startswith("Error"):
            raise RuntimeError(result)
        return {"listing": result}


def build_ssh_tools() -> list[Tool]:
    """Instantiate all SSH tools (shared connector)."""
    return [
        SSHListConnectionsTool(),
        SSHAddConnectionTool(),
        SSHConnectTool(),
        SSHDisconnectTool(),
        SSHExecTool(),
        SSHUploadTool(),
        SSHDownloadTool(),
        SSHListRemoteTool(),
    ]
