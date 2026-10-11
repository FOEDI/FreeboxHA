"""Bounded, read-only aiohttp transport with verified local TLS."""

from __future__ import annotations

import asyncio
import json
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from yarl import URL

from .auth import challenge_password
from .const import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_TIMEOUT, MAX_RESPONSE_BYTES, NAME, VERSION, is_network_list


class FreeboxError(Exception):
    """Safe error with code only; never retain API error messages."""

    def __init__(self, code: str, status: int = 0) -> None:
        self.code = code
        self.status = status
        super().__init__(f"Freebox API: {code} (HTTP {status})")


class AuthenticationError(FreeboxError):
    """Application token revoked or rejected."""


class PermissionDenied(FreeboxError):
    """Endpoint requires an ungranted permission."""


class EndpointUnavailable(FreeboxError):
    """Endpoint not provided by this firmware/hardware."""


@dataclass(frozen=True, slots=True)
class ApiVersion:
    uid: str
    version: str
    base_path: str
    api_domain: str
    device_name: str
    device_type: str

    @classmethod
    def parse(cls, value: Any) -> ApiVersion:
        if not isinstance(value, dict):
            raise FreeboxError("invalid_api_version")
        version = str(value.get("api_version", ""))
        base = value.get("api_base_url", "/api/")
        domain = value.get("api_domain", "")
        if (
            not re.fullmatch(r"[1-9][0-9]*\.[0-9]+", version)
            or not isinstance(base, str)
            or not re.fullmatch(r"/[a-zA-Z0-9_/-]+/", base)
            or ".." in base
            or "//" in base
            or not isinstance(domain, str)
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", domain)
            or not isinstance(value.get("uid"), str)
            or not value["uid"]
        ):
            raise FreeboxError("invalid_api_version")
        if value.get("https_available") is False:
            raise FreeboxError("https_unavailable")
        return cls(
            value["uid"],
            version,
            f"{base}v{version.split('.')[0]}/",
            domain,
            str(value.get("device_name", NAME)),
            str(value.get("device_type", "Freebox")),
        )


def tls_context() -> ssl.SSLContext:
    """Trust official Freebox roots plus OS roots; keep hostname validation."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(Path(__file__).parent / "certs" / "freebox_ca.pem"))
    # Freebox chains omit AKI extensions required by Python 3.13+ strict RFC 5280 checks.
    # Retain chain/signature/expiry and hostname validation with the official roots.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def normalize_host(host: str) -> str:
    """Accept a hostname/IP or an HTTPS URL without credentials or a path."""
    host = host.strip()
    url = URL(host if "://" in host else f"https://{host}")
    if (
        url.scheme != "https"
        or url.user
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or not url.host
    ):
        raise FreeboxError("invalid_host")
    return str(url.host)


class FreeboxClient:
    """Only GET and authentication POST are supported by this client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        context: ssl.SSLContext,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        app_id: str = "",
        app_token: str = "",
        expected_uid: str | None = None,
    ) -> None:
        self.session = session
        self.context = context
        self.host = normalize_host(host)
        self.port = int(port)
        if not 1 <= self.port <= 65535:
            raise FreeboxError("invalid_port")
        self.app_id = app_id
        self._app_token = app_token
        self._session_token: str | None = None
        self.expected_uid = expected_uid
        self.version: ApiVersion | None = None
        self.permissions: dict[str, bool] = {}
        self._auth_lock = asyncio.Lock()
        self._limit = asyncio.Semaphore(4)

    @property
    def origin(self) -> URL:
        return URL.build(scheme="https", host=self.host, port=self.port)

    async def _json(
        self,
        method: str,
        url: URL,
        *,
        authenticated: bool = False,
        secure: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"X-Fbx-App-Auth": self._session_token} if authenticated and self._session_token else {}
        kwargs: dict[str, Any] = {
            "headers": headers,
            "allow_redirects": False,
            "timeout": aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            "json": payload,
        }
        if secure:
            kwargs["ssl"] = self.context
            if self.version:
                kwargs["server_hostname"] = self.version.api_domain
        try:
            async with self._limit, self.session.request(method, url, **kwargs) as response:
                data = b""
                while chunk := await response.content.read(min(65536, MAX_RESPONSE_BYTES + 1 - len(data))):
                    data += chunk
                    if len(data) > MAX_RESPONSE_BYTES:
                        break
                if len(data) > MAX_RESPONSE_BYTES:
                    raise FreeboxError("response_too_large", response.status)
                try:
                    decoded = json.loads(data)
                except (ValueError, UnicodeDecodeError) as err:
                    if response.status in (404, 405):
                        raise EndpointUnavailable("not_found", response.status) from err
                    raise FreeboxError("invalid_json", response.status) from err
                if response.status >= 400 or (isinstance(decoded, dict) and decoded.get("success") is False):
                    code = (
                        decoded.get("error_code", f"http_{response.status}")
                        if isinstance(decoded, dict)
                        else f"http_{response.status}"
                    )
                    # Never incorporate untrusted error strings into loggable exceptions.
                    code = code if isinstance(code, str) and re.fullmatch(r"[a-z_0-9]{1,64}", code) else "api_error"
                    if code in ("invalid_token", "pending_token", "apps_denied"):
                        raise AuthenticationError(code, response.status)
                    if code in ("insufficient_rights", "access_denied"):
                        raise PermissionDenied(code, response.status)
                    if response.status in (404, 405) or code in (
                        "unknown_api",
                        "not_found",
                        "nodev",
                        "noent",
                        "bad_port",
                        "op_not_supported",
                    ):
                        raise EndpointUnavailable(code, response.status)
                    raise FreeboxError(code, response.status)
                if not 200 <= response.status < 300:
                    raise FreeboxError("unexpected_status", response.status)
                return decoded
        except (aiohttp.ClientConnectorCertificateError, ssl.SSLCertVerificationError) as err:
            raise FreeboxError("tls_certificate_error") from err
        except (aiohttp.ClientSSLError, ssl.SSLError) as err:
            raise FreeboxError("tls_handshake_error") from err
        except TimeoutError as err:
            raise FreeboxError("connection_timeout") from err
        except aiohttp.ClientConnectorError as err:
            code = "connection_refused" if isinstance(err.os_error, ConnectionRefusedError) else "transport_error"
            raise FreeboxError(code) from err
        except (aiohttp.ClientError, OSError) as err:
            raise FreeboxError("transport_error") from err

    async def discover(self) -> ApiVersion:
        """Bootstrap only public metadata over HTTP, then verify again over TLS."""
        metadata = await self._json(
            "GET", URL.build(scheme="http", host=self.host, port=80, path="/api_version"), secure=False
        )
        self.version = ApiVersion.parse(metadata)
        verified = ApiVersion.parse(await self._json("GET", self.origin / "api_version"))
        if verified != self.version or (self.expected_uid and verified.uid != self.expected_uid):
            raise FreeboxError("wrong_freebox")
        self.version = verified
        return verified

    def _url(self, path: str) -> URL:
        if self.version is None:
            raise FreeboxError("not_discovered")
        if path.startswith("/") or ".." in path or "?" in path or "#" in path:
            raise FreeboxError("invalid_path")
        return self.origin.with_path(self.version.base_path + path)

    async def _call(self, method: str, path: str, *, auth: bool = False, payload: dict[str, Any] | None = None) -> Any:
        envelope = await self._json(method, self._url(path), authenticated=auth, payload=payload)
        if not isinstance(envelope, dict) or envelope.get("success") is not True:
            raise FreeboxError("invalid_envelope")
        if method == "GET" and "result" not in envelope:
            if is_network_list(path):
                return []
            raise FreeboxError("invalid_envelope")
        return envelope.get("result")

    async def authorize(self, app_id: str) -> tuple[str, int]:
        self.app_id = app_id
        result = await self._call(
            "POST",
            "login/authorize/",
            payload={"app_id": app_id, "app_name": NAME, "app_version": VERSION, "device_name": "Home Assistant"},
        )
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("app_token"), str)
            or not isinstance(result.get("track_id"), int)
        ):
            raise FreeboxError("invalid_authorization")
        self._app_token = result["app_token"]
        return self._app_token, result["track_id"]

    async def authorization_status(self, track_id: int) -> str:
        result = await self._call("GET", f"login/authorize/{int(track_id)}")
        if not isinstance(result, dict) or result.get("status") not in (
            "pending",
            "granted",
            "denied",
            "timeout",
            "unknown",
        ):
            raise FreeboxError("invalid_authorization_status")
        return str(result["status"])

    async def login(self, rejected_token: str | None = None) -> None:
        async with self._auth_lock:
            if rejected_token is None and self._session_token:
                return
            if rejected_token is not None and self._session_token and self._session_token != rejected_token:
                return
            self._session_token = None
            challenge = await self._call("GET", "login/")
            if not isinstance(challenge, dict) or not isinstance(challenge.get("challenge"), str):
                raise FreeboxError("invalid_challenge")
            result = await self._call(
                "POST",
                "login/session/",
                payload={
                    "app_id": self.app_id,
                    "app_version": VERSION,
                    "password": challenge_password(self._app_token, challenge["challenge"]),
                },
            )
            if not isinstance(result, dict) or not isinstance(result.get("session_token"), str):
                raise FreeboxError("invalid_session")
            self._session_token = result["session_token"]
            self.permissions = (
                {key: bool(value) for key, value in result.get("permissions", {}).items()}
                if isinstance(result.get("permissions", {}), dict)
                else {}
            )

    async def get(self, path: str) -> Any:
        if self._session_token is None:
            await self.login()
        token = self._session_token
        try:
            return await self._call("GET", path, auth=True)
        except FreeboxError as err:
            if err.code != "auth_required":
                raise
        await self.login(rejected_token=token)
        return await self._call("GET", path, auth=True)

    async def close(self) -> None:
        if self._session_token:
            try:
                await self._call("POST", "login/logout/", auth=True)
            except FreeboxError:
                pass
            finally:
                self._session_token = None

    async def open_websocket(self) -> aiohttp.ClientWebSocketResponse:
        """Reconnect with a renewed session when the handshake rejects an expired token."""
        if not self._session_token:
            await self.login()
        rejected = self._session_token
        for attempt in range(2):
            try:
                async with asyncio.timeout(DEFAULT_TIMEOUT):
                    return await self.session.ws_connect(
                        self._url("ws/event").with_scheme("wss"),
                        ssl=self.context,
                        server_hostname=self.version.api_domain if self.version else None,
                        headers={"X-Fbx-App-Auth": self._session_token or ""},
                        heartbeat=30,
                        max_msg_size=MAX_RESPONSE_BYTES,
                        timeout=aiohttp.ClientWSTimeout(ws_close=5),
                    )
            except aiohttp.WSServerHandshakeError as err:
                if err.status != 403 or attempt:
                    raise
                await self.login(rejected_token=rejected)
        raise FreeboxError("websocket_handshake_failed")
