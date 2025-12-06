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

    @classmethod
    def load(cls) -> "Settings":
        token = os.getenv("TOKEN")
        if not token:
            raise SettingsError("TOKEN is required but missing.")

        return cls(
            token=token,
            debug=parse_bool(os.getenv("DEBUG", "")),
        )

    def sensitive_values(self) -> List[str]:
        """Values that should be redacted from logs."""
        return [self.token]
