"""Provider read outcomes shared without importing Windows APIs."""


class ProviderUnavailable(RuntimeError):
    """A provider cannot supply an observation."""


class ProviderNotReady(ProviderUnavailable):
    """A registered provider is still awaiting its first completed read."""
