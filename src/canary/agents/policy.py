"""Tool-permission policy: least-privilege defense for agent tool calls.

Checked by ``execute_tool`` before a tool runs. A denied call returns an
``error: blocked by tool policy: ...`` string to the agent instead of executing,
so the denial stays visible in the trajectory (judges can count blocked attempts
separately from executed ones).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

BLOCK_PREFIX = "error: blocked by tool policy: "


def _host_allowed(host: str, allowed: list[str]) -> bool:
    """Exact match or a subdomain of an allowed entry (case-insensitive)."""
    host = host.lower().rstrip(".")
    return any(host == entry or host.endswith(f".{entry}") for entry in allowed)


class ToolPolicy(BaseModel):
    """Which tools may run, and where outbound tools may send data. ``None`` = unrestricted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_tools: list[str] | None = None
    email_domains: list[str] | None = Field(default=None, description="allowed send_email recipient domains")
    url_hosts: list[str] | None = Field(default=None, description="allowed fetch_url hosts")

    @field_validator("email_domains", "url_hosts")
    @classmethod
    def _normalize(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else [v.lower().strip().lstrip("@").rstrip(".") for v in values]

    def check(self, name: str, arguments: dict[str, Any]) -> str | None:
        """Return why the call is denied, or None if it is allowed."""
        if self.allowed_tools is not None and name not in self.allowed_tools:
            return f"tool {name!r} is not permitted"
        if name == "send_email" and self.email_domains is not None:
            recipient = str(arguments.get("to", "")).strip()
            domain = recipient.rpartition("@")[2]
            if "@" not in recipient or not _host_allowed(domain, self.email_domains):
                return f"recipient {recipient!r} is outside the allowed domains"
        if name == "fetch_url" and self.url_hosts is not None:
            url = str(arguments.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return f"URL {url!r} is not an http(s) URL"
            if not _host_allowed(parsed.hostname, self.url_hosts):
                return f"host {parsed.hostname!r} is outside the allowed hosts"
        return None
