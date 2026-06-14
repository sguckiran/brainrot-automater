"""Mistral provider profile.

Minimal ProviderProfile for Mistral. Users should set `MISTRAL_API_KEY`
or `MISTRAL_BASE_URL` in their environment or `~/.hermes/.env`.
"""

from providers import register_provider
from providers.base import ProviderProfile


mistral = ProviderProfile(
    name="mistral",
    aliases=("mistral-ai", "mistralai"),
    display_name="Mistral",
    description="Mistral AI — direct API provider profile",
    env_vars=("MISTRAL_API_KEY", "MISTRAL_BASE_URL"),
    base_url="https://api.mistral.ai/v1",
    auth_type="api_key",
)

register_provider(mistral)
