#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import contextlib
import datetime as dt
import email.utils
import fcntl
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


PROVIDERS = {
    "codex": {
        "id": "codex",
        "name": "Codex",
        "shortName": "Cx",
        "icon": "applications-engineering-symbolic",
        "color": "#49a3b0",
    },
    "claude": {
        "id": "claude",
        "name": "Claude",
        "shortName": "Cl",
        "icon": "applications-science-symbolic",
        "color": "#d97757",
    },
    "kimi": {
        "id": "kimi",
        "name": "Kimi",
        "shortName": "Ki",
        "icon": "applications-development-symbolic",
        "color": "#fe603c",
    },
    "glm": {
        "id": "glm",
        "name": "GLM",
        "shortName": "GLM",
        "icon": "applications-other-symbolic",
        "color": "#4f7cff",
    },
}

EXTENSION_DIR = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_DIR = EXTENSION_DIR / "schemas"
SETTINGS_SCHEMA = "org.gnome.shell.extensions.ai-usage-tracker"
CACHE_DIR = pathlib.Path.home() / ".cache" / "ai-usage-tracker"
STATE_PATH = CACHE_DIR / "state.json"
LOCK_PATH = CACHE_DIR / "refresh.lock"

CODEX_AUTH_PATH = pathlib.Path.home() / ".codex" / "auth.json"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CLAUDE_CREDENTIALS_PATH = pathlib.Path.home() / ".claude" / ".credentials.json"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_REFRESH_SCOPE = "user:profile user:inference user:sessions:claude_code"
KIMI_USAGE_URL = "https://api.kimi.com/coding/v1/usages"
KIMI_TOKEN_URL = "https://auth.kimi.com/api/oauth/token"
KIMI_CREDENTIALS_PATH = pathlib.Path.home() / ".kimi" / "credentials" / "kimi-code.json"
KIMI_DEVICE_ID_PATH = pathlib.Path.home() / ".kimi" / "device_id"
KIMI_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"

ZAI_API_BASE = "https://api.z.ai"
ZAI_QUOTA_URL = ZAI_API_BASE + "/api/monitor/usage/quota/limit"
ZAI_SUBSCRIPTION_URL = ZAI_API_BASE + "/api/biz/subscription/list"
CLAUDE_SETTINGS_PATH = pathlib.Path.home() / ".claude" / "settings.json"
# Shell-style env files that route Claude Code at z.ai (e.g. a `claude-glm` wrapper).
# The token in these only counts as a z.ai key when the base URL points at z.ai.
ZAI_ENV_FILE_PATHS = (
    pathlib.Path(os.environ.get("CLAUDE_GLM_ENV_FILE", "")) if os.environ.get("CLAUDE_GLM_ENV_FILE") else None,
    pathlib.Path.home() / ".config" / "claude-glm" / "env",
)

DEFAULT_ENABLED_PROVIDERS = ["codex", "claude", "kimi", "glm"]
DEFAULT_REFRESH_INTERVAL = 60
HTTP_TIMEOUT_SECONDS = 15

_stop = False


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        transient: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.transient = transient
        self.retry_after_seconds = retry_after_seconds


def utcnow() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_from_unix(seconds: Any) -> str | None:
    if seconds in (None, ""):
        return None
    try:
        return dt.datetime.fromtimestamp(float(seconds), dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def iso_from_unix_ms(milliseconds: Any) -> str | None:
    if milliseconds in (None, ""):
        return None
    try:
        return iso_from_unix(float(milliseconds) / 1000.0)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def iso_from_string(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clamp_percent(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if number > 100:
        return 100.0
    return number


def make_window(
    label: str,
    used_percent: Any,
    *,
    window_minutes: float | None = None,
    resets_at: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    used = clamp_percent(used_percent)
    return {
        "label": label,
        "usedPercent": used,
        "remainingPercent": max(0.0, 100.0 - used),
        "windowMinutes": window_minutes,
        "resetsAt": resets_at,
        "detail": detail,
    }


def classify_window_label(limit_window_seconds: Any) -> str:
    if not limit_window_seconds:
        return "Window"
    try:
        hours = float(limit_window_seconds) / 3600
    except (TypeError, ValueError):
        return "Window"
    if hours <= 6:
        return "Session"
    if hours <= 48:
        return "Daily"
    if hours <= 168:
        return "Weekly"
    return "Window"


def parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return max(0, int(float(value)))
    except ValueError:
        pass
    try:
        retry_at = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=dt.UTC)
    return max(0, int((retry_at.astimezone(dt.UTC) - dt.datetime.now(dt.UTC)).total_seconds()))


def format_duration(seconds: int | None) -> str:
    if seconds is None or seconds <= 0:
        return "soon"
    if seconds < 60:
        return f"{seconds}s"
    minutes = (seconds + 59) // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{(minutes + 59) // 60}h"


def parse_error_message(body: bytes | str | None) -> str | None:
    if body is None:
        return None
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body
    if not text:
        return None
    try:
        payload = json.loads(text)
        message = (
            payload.get("error", {}).get("message")
            if isinstance(payload.get("error"), dict)
            else None
        )
        message = message or payload.get("message") or payload.get("detail")
        if message:
            return str(message)[:160]
    except Exception:
        pass
    collapsed = " ".join(text.split())
    return collapsed[:160] if collapsed else None


def read_json_file(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Invalid JSON in {path}: {exc}", transient=False) from exc
    except OSError as exc:
        raise ProviderError(f"Cannot read {path}: {exc}", transient=True) from exc


def write_json_file(path: pathlib.Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        os.chmod(path, mode)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


def request_json(
    provider_name: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    data = None
    if json_body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode("utf-8")
    elif form_body is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form_body).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        retry_after = parse_retry_after(exc.headers.get("Retry-After"))
        detail = parse_error_message(body)
        retry_text = f"; retrying in {format_duration(retry_after or 60)}" if exc.code == 429 else ""
        detail_text = f": {detail}" if detail else ""
        raise ProviderError(
            f"{provider_name} HTTP {exc.code}{retry_text}{detail_text}",
            status=exc.code,
            transient=exc.code == 429 or exc.code >= 500,
            retry_after_seconds=(retry_after or 60) if exc.code == 429 else retry_after,
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderError(f"{provider_name} network error: {reason}", transient=True) from exc

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"{provider_name} returned invalid JSON: {exc}", transient=False) from exc


def map_codex_window(raw: dict[str, Any] | None, label_base: str | None = None) -> dict[str, Any] | None:
    if not raw or raw.get("used_percent") is None:
        return None
    window_seconds = raw.get("limit_window_seconds")
    return make_window(
        label_base or classify_window_label(window_seconds),
        raw.get("used_percent"),
        window_minutes=(float(window_seconds) / 60) if window_seconds else None,
        resets_at=iso_from_unix(raw.get("reset_at")),
    )


def map_codex_payload(payload: dict[str, Any]) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    rate_limit = payload.get("rate_limit") or {}
    windows.append(map_codex_window(rate_limit.get("primary_window"), "Session"))
    windows.append(map_codex_window(rate_limit.get("secondary_window"), "Weekly"))

    for extra in payload.get("additional_rate_limits") or []:
        extra_rate_limit = extra.get("rate_limit") or {}
        label = extra.get("limit_name") or "Extra"
        windows.append(map_codex_window(extra_rate_limit.get("primary_window"), f"{label} (Session)"))
        windows.append(map_codex_window(extra_rate_limit.get("secondary_window"), f"{label} (Weekly)"))

    credits = None
    payload_credits = payload.get("credits") or {}
    if payload_credits.get("has_credits"):
        credits = payload_credits.get("balance")

    return {
        "source": "codex-wham-api",
        "plan": payload.get("plan_type"),
        "credits": credits,
        "windows": [window for window in windows if window],
    }


def map_claude_window(label: str, window: dict[str, Any] | None, minutes: int) -> dict[str, Any] | None:
    if not window or window.get("utilization") is None:
        return None
    return make_window(
        label,
        window.get("utilization"),
        window_minutes=minutes,
        resets_at=iso_from_string(window.get("resets_at")),
    )


def map_claude_payload(payload: dict[str, Any], credentials: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "claude-oauth",
        "plan": credentials.get("rateLimitTier") or credentials.get("subscriptionType"),
        "credits": None,
        "windows": [
            window
            for window in [
                map_claude_window("Session", payload.get("five_hour"), 300),
                map_claude_window("Weekly", payload.get("seven_day"), 10080),
                map_claude_window("Sonnet weekly", payload.get("seven_day_sonnet"), 10080),
                map_claude_window("Opus weekly", payload.get("seven_day_opus"), 10080),
            ]
            if window
        ],
    }


def map_kimi_count_window(
    label: str,
    detail: dict[str, Any] | None,
    *,
    window_minutes: int | None = None,
) -> dict[str, Any] | None:
    if not detail:
        return None
    try:
        limit = int(detail.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return None

    try:
        used = int(detail.get("used"))
    except (TypeError, ValueError):
        used = None
    try:
        remaining = int(detail.get("remaining"))
    except (TypeError, ValueError):
        remaining = None

    if used is None and remaining is not None:
        used = max(0, limit - remaining)
    elif used is None:
        used = 0
    if remaining is None:
        remaining = max(0, limit - used)

    return make_window(
        label,
        (used / limit) * 100,
        window_minutes=window_minutes,
        resets_at=iso_from_string(detail.get("resetTime")),
        detail=f"{used} / {limit} used ({remaining} remaining)",
    )


def map_kimi_payload(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage") or {}
    windows: list[dict[str, Any] | None] = [map_kimi_count_window("Monthly", usage)]
    for limit in payload.get("limits") or []:
        window = limit.get("window") or {}
        time_unit = str((window.get("timeUnit") or "")).lower()
        label = "5-min" if "minute" in time_unit else "Window"
        windows.append(map_kimi_count_window(label, limit.get("detail")))

    membership = (((payload.get("user") or {}).get("membership") or {}).get("level") or "")
    plan = membership.replace("LEVEL_", "").lower() if membership else None
    return {
        "source": "kimi-api",
        "plan": plan,
        "credits": None,
        "windows": [window for window in windows if window],
    }


def _parse_shell_env_file(path: pathlib.Path) -> dict[str, str]:
    """Parse a simple `KEY=value` / `export KEY=value` shell env file.

    Only flat assignments are read; values are unquoted but not expanded. This is
    deliberately minimal — it must never execute the file.
    """
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if not name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[name] = value
    return result


def _is_zai_host(base_url: str) -> bool:
    """True only when the URL's host is z.ai or a subdomain of it.

    A substring check would misroute a credential: a non-z.ai endpoint whose URL
    merely contains "z.ai" (host `buzz.ai`, `z.ai.evil.com`, or `z.ai` in a query
    string) would otherwise have its Anthropic token sent to api.z.ai.
    """
    host = (urllib.parse.urlsplit(base_url).hostname or "").lower()
    return host == "z.ai" or host.endswith(".z.ai")


def _zai_token_from_env_map(env: dict[str, Any]) -> str | None:
    """Return an Anthropic auth token only when its base URL routes through z.ai."""
    if not _is_zai_host(str(env.get("ANTHROPIC_BASE_URL") or "")):
        return None
    token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ZAI_API_KEY") or env.get("GLM_API_KEY")
    return str(token).strip() if token else None


def resolve_zai_api_key() -> str | None:
    """Resolve a z.ai API key.

    Resolution order:
      1. ZAI_API_KEY / GLM_API_KEY from the environment (explicit, always wins).
      2. A `claude-glm`-style shell env file that points Claude Code at z.ai.
      3. ~/.claude/settings.json `env` when its base URL points at z.ai.
    """
    key = os.environ.get("ZAI_API_KEY") or os.environ.get("GLM_API_KEY")
    if key:
        return key.strip()

    for path in ZAI_ENV_FILE_PATHS:
        if path and path.is_file():
            token = _zai_token_from_env_map(_parse_shell_env_file(path))
            if token:
                return token

    settings = read_json_file(CLAUDE_SETTINGS_PATH)
    if isinstance(settings, dict):
        env = settings.get("env")
        if isinstance(env, dict):
            token = _zai_token_from_env_map(env)
            if token:
                return token
    return None


def _glm_used_percent(limit: dict[str, Any]) -> float:
    pct = limit.get("percentage")
    if pct is not None:
        return clamp_percent(pct)
    current = _to_int(limit.get("currentValue"))
    total = _to_int(limit.get("usage"))
    if current is not None and total:
        return clamp_percent((current / total) * 100)
    return 0.0


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _glm_token_window(label: str, limit: dict[str, Any], minutes: int | None) -> dict[str, Any]:
    detail = None
    current = _to_int(limit.get("currentValue"))
    total = _to_int(limit.get("usage"))
    if current is not None and total:
        detail = f"{current:,} / {total:,} tokens used"
    return make_window(
        label,
        _glm_used_percent(limit),
        window_minutes=minutes,
        resets_at=iso_from_unix_ms(limit.get("nextResetTime")),
        detail=detail,
    )


def _glm_time_window(limit: dict[str, Any]) -> dict[str, Any]:
    detail = None
    current = _to_int(limit.get("currentValue"))
    total = _to_int(limit.get("usage"))
    remaining = _to_int(limit.get("remaining"))
    if current is not None and total:
        rem_txt = f" ({remaining} remaining)" if remaining is not None else ""
        detail = f"{current} / {total} used{rem_txt}"
    return make_window(
        "Web Searches",
        _glm_used_percent(limit),
        window_minutes=43200,
        resets_at=iso_from_unix_ms(limit.get("nextResetTime")),
        detail=detail,
    )


def map_glm_payload(payload: dict[str, Any], plan: str | None) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = {}
    level = data.get("level")

    windows: dict[str, dict[str, Any]] = {}
    for limit in data.get("limits") or []:
        if not isinstance(limit, dict):
            continue
        ltype = str(limit.get("type") or "")
        unit = limit.get("unit")
        if ltype == "TOKENS_LIMIT":
            if unit == 3:
                windows.setdefault("session", _glm_token_window("Session", limit, 300))
            elif unit == 6:
                windows.setdefault("weekly", _glm_token_window("Weekly", limit, 10080))
            else:
                windows.setdefault(f"tokens-{unit}", _glm_token_window("Tokens", limit, None))
        elif ltype == "TIME_LIMIT":
            windows.setdefault("web", _glm_time_window(limit))

    ordered: list[dict[str, Any]] = []
    for key in ("session", "weekly", "web"):
        window = windows.pop(key, None)
        if window:
            ordered.append(window)
    ordered.extend(windows.values())

    resolved_plan = plan or (str(level).capitalize() if level else None)
    return {
        "source": "zai-quota-api",
        "plan": resolved_plan,
        "credits": None,
        "windows": ordered,
    }


class CodexProvider:
    def fetch(self) -> dict[str, Any]:
        auth = read_json_file(CODEX_AUTH_PATH) or {}
        tokens = auth.get("tokens") or {}
        token = tokens.get("access_token")
        if not token:
            raise ProviderError("No Codex auth found. Run `codex login`.", transient=False)
        headers = {
            "Authorization": f"Bearer {token}",
            "ChatGPT-Account-Id": tokens.get("account_id") or "",
        }
        return map_codex_payload(request_json("Codex", "GET", CODEX_USAGE_URL, headers=headers))


class ClaudeProvider:
    def fetch(self) -> dict[str, Any]:
        credentials_file = read_json_file(CLAUDE_CREDENTIALS_PATH) or {}
        credentials = self._ensure_fresh_credentials(credentials_file)
        token = credentials.get("accessToken")
        if not token:
            raise ProviderError("No Claude OAuth credentials found. Run `claude login` or `claude setup-token`.", transient=False)
        payload = request_json(
            "Claude",
            "GET",
            CLAUDE_USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-code/2.1.0",
            },
        )
        return map_claude_payload(payload, credentials)

    def _ensure_fresh_credentials(self, credentials_file: dict[str, Any]) -> dict[str, Any]:
        credentials = credentials_file.get("claudeAiOauth")
        if not credentials:
            raise ProviderError("No Claude OAuth credentials found. Run `claude login` or `claude setup-token`.", transient=False)
        if credentials.get("accessToken") and not self._is_token_expired(credentials):
            return credentials
        refresh_token = credentials.get("refreshToken")
        if not refresh_token:
            raise ProviderError("Claude OAuth access token is expired and no refresh token is available. Run `claude login`.", transient=False)

        refreshed = request_json(
            "Claude token refresh",
            "POST",
            CLAUDE_TOKEN_URL,
            json_body={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLAUDE_CLIENT_ID,
                "scope": CLAUDE_REFRESH_SCOPE,
            },
        )
        next_credentials = dict(credentials)
        next_credentials["accessToken"] = refreshed.get("access_token")
        next_credentials["refreshToken"] = refreshed.get("refresh_token") or refresh_token
        next_credentials["expiresAt"] = int(time.time() * 1000) + int(refreshed.get("expires_in") or 3600) * 1000
        if refreshed.get("scope"):
            next_credentials["scopes"] = [scope for scope in str(refreshed["scope"]).split(" ") if scope]

        write_json_file(
            CLAUDE_CREDENTIALS_PATH,
            {**credentials_file, "claudeAiOauth": next_credentials},
            mode=0o600,
        )
        return next_credentials

    def _is_token_expired(self, credentials: dict[str, Any]) -> bool:
        try:
            expires_at = int(credentials.get("expiresAt"))
        except (TypeError, ValueError):
            return True
        return expires_at - int(time.time() * 1000) < 300_000


class KimiProvider:
    def fetch(self) -> dict[str, Any]:
        self._ensure_fresh_token()
        credentials = read_json_file(KIMI_CREDENTIALS_PATH) or {}
        token = credentials.get("access_token")
        if not token:
            raise ProviderError("No Kimi credentials found. Run `kimi login`.", transient=False)
        return map_kimi_payload(
            request_json("Kimi", "GET", KIMI_USAGE_URL, headers={"Authorization": f"Bearer {token}"})
        )

    def _ensure_fresh_token(self) -> None:
        credentials = read_json_file(KIMI_CREDENTIALS_PATH) or {}
        refresh_token = credentials.get("refresh_token")
        if not refresh_token or not self._is_token_expired(credentials):
            return
        refreshed = request_json(
            "Kimi token refresh",
            "POST",
            KIMI_TOKEN_URL,
            headers={
                "X-Msh-Platform": "kimi_cli",
                "X-Msh-Device-Id": self._device_id(),
            },
            form_body={
                "client_id": KIMI_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        now = int(time.time())
        next_credentials = {
            "access_token": refreshed.get("access_token"),
            "refresh_token": refreshed.get("refresh_token"),
            "expires_at": now + int(refreshed.get("expires_in") or 900),
            "scope": refreshed.get("scope"),
            "token_type": refreshed.get("token_type"),
            "expires_in": int(refreshed.get("expires_in") or 900),
        }
        write_json_file(KIMI_CREDENTIALS_PATH, next_credentials, mode=0o600)

    def _is_token_expired(self, credentials: dict[str, Any]) -> bool:
        try:
            expires_at = int(credentials.get("expires_at"))
        except (TypeError, ValueError):
            return True
        return expires_at - int(time.time()) < 300

    def _device_id(self) -> str:
        try:
            return KIMI_DEVICE_ID_PATH.read_text(encoding="utf-8").strip() or "unknown"
        except OSError:
            return "unknown"


class GLMProvider:
    def fetch(self) -> dict[str, Any]:
        key = resolve_zai_api_key()
        if not key:
            raise ProviderError(
                "No z.ai/GLM API key found. Set ZAI_API_KEY (or GLM_API_KEY), "
                "or configure z.ai as your Claude Code base URL.",
                transient=False,
            )
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        quota = request_json("GLM", "GET", ZAI_QUOTA_URL, headers=headers)
        if isinstance(quota, dict) and quota.get("success") is False:
            raise ProviderError(f"GLM: {quota.get('msg') or 'quota request failed'}", transient=False)
        data = quota.get("data") if isinstance(quota, dict) else None
        if not isinstance(data, dict) or not data.get("limits"):
            raise ProviderError("GLM returned no usage data.", transient=False)
        plan = self._plan_name(headers)
        return map_glm_payload(quota, plan)

    def _plan_name(self, headers: dict[str, str]) -> str | None:
        try:
            payload = request_json("GLM", "GET", ZAI_SUBSCRIPTION_URL, headers=headers)
        except ProviderError:
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        for sub in data or []:
            if isinstance(sub, dict) and sub.get("status") == "VALID" and sub.get("productName"):
                return str(sub["productName"])
        return None


PROVIDER_CLIENTS = {
    "codex": CodexProvider,
    "claude": ClaudeProvider,
    "kimi": KimiProvider,
    "glm": GLMProvider,
}


def provider_ok_state(provider: dict[str, Any], snapshot: dict[str, Any], now: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "updatedAt": now,
        "source": snapshot.get("source"),
        "plan": snapshot.get("plan"),
        "credits": snapshot.get("credits"),
        "windows": [window for window in snapshot.get("windows", []) if window],
        "error": None,
        "retryAfterSeconds": None,
        "provider": provider,
    }


def provider_error_state(
    *,
    provider_id: str,
    provider: dict[str, Any],
    previous: dict[str, Any] | None,
    error: ProviderError,
    now: str,
) -> dict[str, Any]:
    has_previous_data = bool(previous and previous.get("windows"))
    base = dict(previous or {}) if error.transient and has_previous_data else {}
    base.update(
        {
            "status": "stale" if error.transient and has_previous_data else "error",
            "updatedAt": base.get("updatedAt") or now,
            "source": base.get("source"),
            "plan": base.get("plan"),
            "credits": base.get("credits"),
            "windows": base.get("windows") or [],
            "error": str(error),
            "retryAfterSeconds": error.retry_after_seconds,
            "provider": provider,
        }
    )
    return base


def load_state() -> dict[str, Any]:
    try:
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    providers = state.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    return {
        "schemaVersion": 1,
        "updatedAt": state.get("updatedAt"),
        "providers": providers,
    }


def write_state(state: dict[str, Any]) -> None:
    state["schemaVersion"] = 1
    state["updatedAt"] = utcnow()
    write_json_file(STATE_PATH, state, mode=0o600)


def parse_gsettings_array(output: str) -> list[str]:
    text = output.strip()
    if text in ("@as []", "[]", ""):
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _gsettings_get(key: str) -> str | None:
    try:
        result = subprocess.run(
            [
                "gsettings",
                "--schemadir",
                str(SCHEMA_DIR),
                "get",
                SETTINGS_SCHEMA,
                key,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip()


def read_settings() -> tuple[list[str], int]:
    enabled_raw = _gsettings_get("enabled-providers")
    enabled = parse_gsettings_array(enabled_raw or "") or DEFAULT_ENABLED_PROVIDERS
    enabled = [provider_id for provider_id in enabled if provider_id in PROVIDERS]

    interval_raw = _gsettings_get("refresh-interval")
    try:
        interval = int(interval_raw or DEFAULT_REFRESH_INTERVAL)
    except ValueError:
        interval = DEFAULT_REFRESH_INTERVAL
    return enabled, max(10, interval)


@contextlib.contextmanager
def refresh_lock() -> Any:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def refresh_provider(provider_id: str, state: dict[str, Any], now: str) -> None:
    provider = PROVIDERS[provider_id]
    previous = state["providers"].get(provider_id)
    try:
        snapshot = PROVIDER_CLIENTS[provider_id]().fetch()
        state["providers"][provider_id] = provider_ok_state(provider, snapshot, now)
        log(f"{provider['name']} usage refreshed")
    except ProviderError as exc:
        state["providers"][provider_id] = provider_error_state(
            provider_id=provider_id,
            provider=provider,
            previous=previous,
            error=exc,
            now=now,
        )
        log(f"{provider['name']} refresh failed: {exc}")
    except Exception as exc:
        wrapped = ProviderError(f"{provider['name']} unexpected error: {exc}", transient=False)
        state["providers"][provider_id] = provider_error_state(
            provider_id=provider_id,
            provider=provider,
            previous=previous,
            error=wrapped,
            now=now,
        )
        log(f"{provider['name']} unexpected refresh failure: {exc}")


def refresh(provider_ids: list[str]) -> None:
    with refresh_lock():
        now = utcnow()
        state = load_state()
        for provider_id in provider_ids:
            refresh_provider(provider_id, state, now)
            write_state(state)
        if not provider_ids:
            write_state(state)


def log(message: str) -> None:
    print(f"{utcnow()} {message}", flush=True)


def _handle_signal(signum: int, _frame: Any) -> None:
    global _stop
    _stop = True
    log(f"Received signal {signum}; stopping")


def run_loop(provider: str | None) -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log("AI usage tracker helper started")
    while not _stop:
        enabled, interval = read_settings()
        provider_ids = [provider] if provider else enabled
        refresh(provider_ids)
        for _ in range(interval):
            if _stop:
                break
            time.sleep(1)
    log("AI usage tracker helper stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh AI usage tracker cache")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), help="refresh one provider")
    args = parser.parse_args(argv)

    if args.loop:
        return run_loop(args.provider)

    enabled, _interval = read_settings()
    refresh([args.provider] if args.provider else enabled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
