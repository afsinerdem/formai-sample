from __future__ import annotations

from abc import ABC

from formai.config import FormAIConfig


class BaseAgent(ABC):
    def __init__(self, config: FormAIConfig):
        self.config = config
