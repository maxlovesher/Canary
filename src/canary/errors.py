"""Exception hierarchy. The CLI turns any ``CanaryError`` into a clean exit code."""


class CanaryError(Exception):
    """Base class for all expected Canary failures."""


class ConfigError(CanaryError):
    """The config file is missing, unparsable, or fails validation."""


class ComponentError(CanaryError):
    """Unknown component type, bad registration, or invalid component params."""


class DatasetError(CanaryError):
    """An attack dataset is missing, malformed, or fails its integrity check."""


class TargetError(CanaryError):
    """A target could not produce a response (network, HTTP, or protocol error)."""


class CacheMissError(TargetError):
    """Strict replay (cache mode ``read_only``) found no cached response."""
