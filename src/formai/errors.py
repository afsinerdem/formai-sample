class FormAIError(Exception):
    """Base exception for FormAI."""


class IntegrationUnavailable(FormAIError):
    """Raised when an optional dependency or external provider is unavailable."""


class VisionProviderError(FormAIError):
    """Raised when the configured vision provider cannot produce a response."""
