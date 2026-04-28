from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from formai.config import FormAIConfig
from formai.llm.base import VisionLLMClient


@dataclass
class NodeContext:
    config: FormAIConfig
    working_dir: Path
    intake_client: Optional[VisionLLMClient] = None
    template_client: Optional[VisionLLMClient] = None
    perception_client: Optional[VisionLLMClient] = None
    resolver_client: Optional[VisionLLMClient] = None
    adjudicator_client: Optional[VisionLLMClient] = None
    verification_client: Optional[VisionLLMClient] = None
