import os
from dataclasses import dataclass
from typing import List, Optional


class SettingsError(Exception):
    """Raised when required settings are missing or invalid."""


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    token: str
    debug: bool = False
    skyland_tokens: List[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.skyland_tokens is None:
            self.skyland_tokens = []

    @classmethod
    def load(cls) -> "Settings":
        token = os.getenv("TOKEN")
        if not token:
            raise SettingsError("TOKEN is required but missing.")

        skyland_raw = os.getenv("SKYLAND_TOKEN", "")
        skyland_tokens = [
            t.strip() for t in skyland_raw.split(",") if t.strip()
        ]

        return cls(
            token=token,
            debug=parse_bool(os.getenv("DEBUG", "")),
            skyland_tokens=skyland_tokens,
        )

    def sensitive_values(self) -> List[str]:
        """Values that should be redacted from logs."""
        return [self.token] + self.skyland_tokens
