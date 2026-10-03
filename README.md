# Environment Metadata Provider

Collects hostname, process ID, Python version, and an approximate process boot time once at startup, exposing them as an immutable mapping suitable for enriching log records.

## Usage

```python
from environment_metadata_provider import EnvironmentMetadataProvider

provider = EnvironmentMetadataProvider()
print(dict(provider))        # {'hostname': ..., 'pid': ..., 'python_version': ..., 'boot_time': ...}
print(provider["hostname"])  # direct field access

# Spread into a logging record's extra fields, or merge into a JSON schema.
record_extra = dict(provider)
```

`EnvironmentMetadataProvider(now_fn=...)` accepts a zero-argument callable returning a float, used as the clock for the boot-time estimate. This exists so tests can inject a fake clock; production code leaves it at the default `time.time`.

The module also exports `collect_environment_metadata(now_fn=time.time)` and `boot_time()`. The former builds and returns a fresh frozen snapshot (`types.MappingProxyType`); the latter returns a single float.

## Why this exists

Long-running services that emit structured logs want a small, fixed set of environment facts attached to every record: which host, which process, which interpreter, and roughly when this process came up. Doing that lookup per-log-line is wasteful and risks drift (a hostname change mid-run would split a log stream). This library takes the snapshot once, in `__init__`, and never refreshes it.

The trade-off is that the snapshot is stale by design: if the process re-exec()s or changes its hostname after startup, the provider will not reflect that. If you need a refresh, call `collect_environment_metadata()` directly.

## Edge cases

- `boot_time` is interpreted as the current *process's* start time (epoch seconds), not the OS boot time — because that is the value that is actually useful when correlating service logs. It is derived as `now - elapsed` from `os.times().elapsed` where available, falling back to `time.process_time()`. It is approximate; do not treat it as sub-second precise.
- `socket.gethostname()` can raise or return an empty string in stripped-down containers (e.g. a freshly unshared UTS namespace). In that case the hostname field becomes the sentinel string `<unknown-host>` rather than an empty value that would silently corrupt log records.
- The snapshot is a `MappingProxyType`: mutation attempts raise `TypeError` on assignment and `AttributeError` on deletion.
