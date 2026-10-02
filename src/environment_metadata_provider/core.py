"""Collect environment metadata once at startup for log record enrichment."""

import os
import socket
import sys
import time
from types import MappingProxyType
from typing import Callable, Dict, Hashable, Iterator, Mapping

__all__ = [
    "EnvironmentMetadataProvider",
    "collect_environment_metadata",
    "boot_time",
]


def _python_version_string() -> str:
    """Return a stable 'major.minor.micro' string for the running interpreter.

    We use sys.version_info directly because platform.python_version() can
    append build-specific suffixes in rare CPython builds; the tuple form is
    the canonical source.
    """
    v = sys.version_info
    return "{}.{}.{}".format(v.major, v.minor, v.micro)


def boot_time() -> float:
    """Best-effort monotonic-ish 'boot time' as a wall-clock float.

    Interpretation chosen and locked here: 'boot time' means the epoch
    timestamp at which the *current process* started, not the host's OS boot.
    This is the value that is actually useful for log enrichment (you want
    to know when the long-running service under observation came up), and it
    is available portably via psutil's create_time — but psutil is third
    party, so we derive it from time.time() minus an elapsed measure.

    On CPython, time.process_time() does not include time before the
    interpreter started, so it is *not* suitable. Instead we use the
    monotonic elapsed since import of this module is unreliable across
    reloads. The pragmatic, portable choice is: clock_at_call - uptime,
    where uptime is taken from os.times().children_user+system is excluded;
    we use os.times().elapsed when available, else fall back to a best
    effort of time.process_time().

    The result is only as accurate as the underlying clocks; callers should
    treat it as approximate.
    """
    elapsed = _process_uptime_seconds()
    return time.time() - elapsed


def _process_uptime_seconds() -> float:
    """Elapsed seconds since this process started, best effort.

    os.times() returns a named tuple on POSIX whose 'elapsed' field is wall
    time since process start; on Windows it is 0 and we fall back to
    time.clock()/process_time(). We deliberately avoid time.monotonic()
    relative to a module-global, because re-import or fork() would make that
    value wrong.
    """
    try:
        t = os.times()
        elapsed = t.elapsed if hasattr(t, "elapsed") else 0.0
        if elapsed and elapsed > 0.0:
            return float(elapsed)
    except (AttributeError, OSError):
        pass
    return time.process_time()


def _hostname() -> str:
    """Return a non-empty hostname, falling back to a clear sentinel.

    socket.gethostname() can raise on stripped-down containers (e.g. a
    freshly unshared UTS namespace with no hostname set). Returning an
    empty string would silently corrupt log records, so we substitute a
    visible sentinel that operators can grep for.
    """
    try:
        name = socket.gethostname()
    except OSError:
        return "<unknown-host>"
    if not name:
        return "<unknown-host>"
    return name


def collect_environment_metadata(
    now_fn: Callable[[], float] = time.time,
) -> Mapping[str, Hashable]:
    """Collect a snapshot of environment metadata and return a frozen mapping.

    The mapping is frozen in two senses: it is a MappingProxyType (so callers
    cannot mutate it), and its contents are fixed at call time. Calling this
    again will produce a *new* snapshot with an updated boot_time estimate.

    now_fn is taken as an explicit parameter so tests can inject a fake
    clock; the library never compares floats with == and never reads the
    wall clock directly in a path that a test exercises.
    """
    host = _hostname()
    pid = os.getpid()
    pyver = _python_version_string()
    # boot_time() reads the wall clock itself; to keep now_fn as the single
    # source of truth in tests we reconstruct the same elapsed measure here.
    elapsed = _process_uptime_seconds()
    boot = now_fn() - elapsed
    snapshot: Dict[str, Hashable] = {
        "hostname": host,
        "pid": pid,
        "python_version": pyver,
        "boot_time": boot,
    }
    return MappingProxyType(snapshot)


class EnvironmentMetadataProvider:
    """Collect environment metadata once and expose it as a frozen mapping.

    The snapshot is taken in __init__ and never refreshed; this is deliberate.
    Log record enrichment wants a stable, cheap-to-read object per process,
    not a value that drifts between log lines. If you need a refresh, call
    collect_environment_metadata() directly.

    The instance is a Mapping, so it can be spread into a logging record's
    'extra' dict or merged into a JSON log schema directly.
    """

    __slots__ = ("_data",)

    def __init__(self, now_fn: Callable[[], float] = time.time) -> None:
        self._data = collect_environment_metadata(now_fn=now_fn)

    def as_dict(self) -> Mapping[str, Hashable]:
        """Return the frozen snapshot (a MappingProxyType).

        This is the same object returned by __getitem__; returning it directly
        is safe because MappingProxyType is already immutable.
        """
        return self._data

    def __getitem__(self, key: str) -> Hashable:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()

    def get(self, key: str, default=None):
        return self._data.get(key, default)
