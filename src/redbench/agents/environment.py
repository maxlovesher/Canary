"""In-memory mock world for agent targets. Nothing here touches the real network or disk."""

from __future__ import annotations

from dataclasses import dataclass

from redbench.scenario import EnvironmentSpec


@dataclass(frozen=True)
class SentEmail:
    """An email the agent "sent" (recorded, never delivered)."""

    to: str
    subject: str
    body: str


class MockEnvironment:
    """Mutable per-case state behind the mock tools. Create a fresh one for every case."""

    def __init__(self, spec: EnvironmentSpec) -> None:
        self.files: dict[str, str] = dict(spec.files)
        self.web: dict[str, str] = dict(spec.web)
        self.inbox = list(spec.inbox)
        self.outbox: list[SentEmail] = []
        self.fetched_urls: list[str] = []

    def read_file(self, path: str) -> str:
        """Content of ``path``, or an error string the agent can read."""
        if path not in self.files:
            return f"error: file not found: {path}"
        return self.files[path]

    def list_files(self) -> str:
        """Newline-separated file paths."""
        return "\n".join(sorted(self.files)) or "(no files)"

    def fetch_url(self, url: str) -> str:
        """Page content for ``url``; every fetch is recorded (URLs are an exfiltration channel)."""
        self.fetched_urls.append(url)
        if url not in self.web:
            return f"error: 404 not found: {url}"
        return self.web[url]

    def send_email(self, to: str, subject: str, body: str) -> str:
        """Record an outgoing email."""
        self.outbox.append(SentEmail(to=to, subject=subject, body=body))
        return f"email sent to {to}"

    def list_inbox(self) -> str:
        """One line per email: ``id | from | subject``."""
        if not self.inbox:
            return "(inbox empty)"
        return "\n".join(f"{email.id} | {email.sender} | {email.subject}" for email in self.inbox)

    def read_email(self, email_id: str) -> str:
        """Full text of one inbox email."""
        for email in self.inbox:
            if email.id == email_id:
                return f"From: {email.sender}\nSubject: {email.subject}\n\n{email.body}"
        return f"error: no email with id {email_id}"
