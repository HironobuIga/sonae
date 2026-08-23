"""Runtime configuration for Sonae.

Model provider resolution order:
1. SONAE_MODEL_PROVIDER=bedrock (default) — Amazon Bedrock via strands BedrockModel
2. SONAE_MODEL_PROVIDER=anthropic — direct Anthropic API (needs ANTHROPIC_API_KEY)

Everything else is filesystem layout and data endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings:
    def __init__(self) -> None:
        self.model_provider: str = os.getenv("SONAE_MODEL_PROVIDER", "bedrock")
        self.bedrock_model_id: str = os.getenv(
            "SONAE_BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )
        self.anthropic_model_id: str = os.getenv("SONAE_ANTHROPIC_MODEL_ID", "claude-sonnet-4-5")
        self.aws_region: str = os.getenv("AWS_REGION", "us-west-2")

        self.data_dir: Path = Path(os.getenv("SONAE_DATA_DIR", REPO_ROOT / "data"))
        self.cache_dir: Path = Path(os.getenv("SONAE_CACHE_DIR", self.data_dir / "cache"))
        self.store_dir: Path = Path(os.getenv("SONAE_STORE_DIR", self.data_dir / "store"))
        self.resources_dir: Path = Path(__file__).resolve().parent / "resources"

        # Offline mode: serve all government data from bundled samples/caches.
        # Used for tests and for demo resilience (venue Wi-Fi is a demo killer).
        self.offline: bool = os.getenv("SONAE_OFFLINE", "0") == "1"


settings = Settings()


def make_model():
    """Build the strands model object for the configured provider."""
    if settings.model_provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(model_id=settings.anthropic_model_id, max_tokens=4096)

    from strands.models.bedrock import BedrockModel

    return BedrockModel(model_id=settings.bedrock_model_id, region_name=settings.aws_region)
