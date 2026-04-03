"""Canonical secret tracking and argument redaction for updater logs."""

from __future__ import annotations


class UpdateSecretRedactor:
    """Track secrets and redact them from free-form text or command arguments."""

    __slots__ = ("_redact_secrets",)

    def __init__(self) -> None:
        self._redact_secrets: set[str] = set()

    def track(self, secret: str) -> None:
        self._redact_secrets = {secret} if secret else set()

    def clear(self) -> None:
        self._redact_secrets.clear()

    def redact(self, text: str) -> str:
        redacted = text
        for secret in self._redact_secrets:
            if secret:
                redacted = redacted.replace(secret, "***")
        return redacted

    def redacted_args(self, args: list[str], sensitive_keys: set[str]) -> list[str]:
        redacted: list[str] = []
        hide_next = False
        for raw_arg in args:
            arg = str(raw_arg)
            if hide_next:
                redacted.append("***")
                hide_next = False
                continue
            if arg.lower() in sensitive_keys:
                redacted.append(arg)
                hide_next = True
                continue
            if self._redact_secrets and arg in self._redact_secrets:
                redacted.append("***")
                continue
            redacted.append(arg)
        return redacted
