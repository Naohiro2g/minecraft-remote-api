"""Local TCP policy; none of these settings changes JSON-RPC wire data."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import math


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a finite positive number')


@dataclass(frozen=True)
class LivenessOptions:
    enabled: bool = True
    idle: int = 60
    interval: int = 30
    probes: int = 10

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise TypeError('enabled must be bool')
        for name in ('idle', 'interval', 'probes'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f'{name} must be a positive integer')


@dataclass(frozen=True)
class ReconnectOptions:
    enabled: bool = True
    initial_delay: float = 0.5
    max_delay: float = 30.0
    budget: float = 300.0

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise TypeError('enabled must be bool')
        for name in ('initial_delay', 'max_delay', 'budget'):
            _positive(getattr(self, name), name)
        if self.max_delay < self.initial_delay:
            raise ValueError('max_delay must be at least initial_delay')


@dataclass(frozen=True)
class ConnectionOptions:
    response_idle_timeout: float = 900.0
    connect_timeout: float = 10.0
    liveness: LivenessOptions = field(default_factory=LivenessOptions)
    reconnect: ReconnectOptions = field(default_factory=ReconnectOptions)

    def __post_init__(self):
        _positive(self.response_idle_timeout, 'response_idle_timeout')
        _positive(self.connect_timeout, 'connect_timeout')
        if not isinstance(self.liveness, LivenessOptions) or not isinstance(self.reconnect, ReconnectOptions):
            raise TypeError('liveness/reconnect must be their corresponding option types')


@dataclass(frozen=True)
class ReconnectInfo:
    previous_epoch: int
    epoch: int
    previous_hello: dict
    hello: dict
    server_changed: bool
    session_changed: bool
    catalog_changed: bool
    events_lost: bool = True
    previous_fast_completion_unknown: bool = False


@dataclass(frozen=True)
class FlushInfo:
    epoch: int
    previous_flush_epoch: int | None
    reconnected_since_previous_flush: bool
    excludes_previous_epochs: bool = True


_response_budget = ContextVar('mcremote_response_budget', default=None)


@contextmanager
def call_options(*, response_idle_timeout):
    """Extend the response idle budget for calls made in this context/thread."""
    _positive(response_idle_timeout, 'response_idle_timeout')
    token = _response_budget.set(response_idle_timeout)
    try:
        yield
    finally:
        _response_budget.reset(token)
