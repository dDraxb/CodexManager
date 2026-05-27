from __future__ import annotations


DEFAULT_PROVIDER = "codex"
SUPPORTED_PROVIDERS = {"codex"}
KNOWN_PROVIDERS = {
    "codex": {
        "id": "codex",
        "label": "Codex",
        "status": "supported",
        "default": True,
        "sessionLaunch": True,
        "historyResume": True,
        "environmentManagement": True,
    },
    "claude": {
        "id": "claude",
        "label": "Claude Code",
        "status": "planned",
        "default": False,
        "sessionLaunch": False,
        "historyResume": False,
        "environmentManagement": False,
    },
}


class ProviderError(RuntimeError):
    pass


def normalize_provider(provider: str | None) -> str:
    normalized = str(provider or DEFAULT_PROVIDER).strip().lower()
    if not normalized:
        normalized = DEFAULT_PROVIDER
    if normalized not in KNOWN_PROVIDERS:
        raise ProviderError(f"unknown provider '{normalized}'")
    return normalized


def ensure_supported_provider(provider: str | None) -> str:
    normalized = normalize_provider(provider)
    if normalized not in SUPPORTED_PROVIDERS:
        label = KNOWN_PROVIDERS[normalized]["label"]
        raise ProviderError(f"{label} provider is registered but not implemented for managed sessions yet")
    return normalized


def list_providers() -> dict:
    providers = sorted(KNOWN_PROVIDERS.values(), key=lambda row: (row["status"] != "supported", row["id"]))
    return {
        "defaultProvider": DEFAULT_PROVIDER,
        "providers": providers,
    }
