"""Exception hierarchy. The CLI turns any ``RedBenchError`` into a clean exit code."""


class RedBenchError(Exception):
    """Base class for all expected RedBench failures."""


class ConfigError(RedBenchError):
    """The config file is missing, unparsable, or fails validation."""


class ComponentError(RedBenchError):
    """Unknown component type, bad registration, or invalid component params."""


class DatasetError(RedBenchError):
    """An attack dataset is missing, malformed, or fails its integrity check."""


class TargetError(RedBenchError):
    """A target could not produce a response (network, HTTP, or protocol error)."""


class CacheMissError(TargetError):
    """Strict replay (cache mode ``read_only``) found no cached response."""
