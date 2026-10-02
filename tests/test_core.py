import os
import socket
import sys
import unittest
from types import MappingProxyType

from environment_metadata_provider import (
    EnvironmentMetadataProvider,
    collect_environment_metadata,
    boot_time,
)


class TestCollectEnvironmentMetadata(unittest.TestCase):
    def test_returns_mappingproxy(self):
        meta = collect_environment_metadata()
        self.assertIsInstance(meta, MappingProxyType)

    def test_has_expected_keys(self):
        meta = collect_environment_metadata()
        self.assertEqual(
            set(meta.keys()),
            {"hostname", "pid", "python_version", "boot_time"},
        )

    def test_hostname_matches_socket(self):
        meta = collect_environment_metadata()
        expected = socket.gethostname()
        # Either the real hostname or our sentinel if the host is unnamed.
        self.assertTrue(meta["hostname"] == expected or meta["hostname"] == "<unknown-host>")

    def test_pid_matches_os(self):
        meta = collect_environment_metadata()
        self.assertEqual(meta["pid"], os.getpid())

    def test_python_version_matches_interpreter(self):
        meta = collect_environment_metadata()
        v = sys.version_info
        self.assertEqual(meta["python_version"], "{}.{}.{}".format(v.major, v.minor, v.micro))

    def test_boot_time_uses_now_fn(self):
        calls = {"count": 0}

        def fake_now():
            calls["count"] += 1
            return 1_000_000.0

        meta = collect_environment_metadata(now_fn=fake_now)
        # now_fn must be consulted exactly once for boot_time.
        self.assertEqual(calls["count"], 1)
        # boot_time == now - elapsed. We don't assert elapsed's exact value,
        # but it must be non-negative and the subtraction must be consistent.
        self.assertIsInstance(meta["boot_time"], float)
        self.assertLessEqual(meta["boot_time"], 1_000_000.0)

    def test_snapshot_is_immutable(self):
        meta = collect_environment_metadata()
        with self.assertRaises(TypeError):
            meta["hostname"] = "tampered"  # type: ignore[index]
        with self.assertRaises(TypeError):
            del meta["hostname"]  # type: ignore[misc]

    def test_two_calls_produce_independent_objects(self):
        a = collect_environment_metadata()
        b = collect_environment_metadata()
        self.assertIsNot(a, b)
        # PID and python_version are stable; hostname should be too.
        self.assertEqual(a["pid"], b["pid"])
        self.assertEqual(a["python_version"], b["python_version"])


class TestEnvironmentMetadataProvider(unittest.TestCase):
    def test_class_is_mapping(self):
        prov = EnvironmentMetadataProvider()
        # Mapping protocol
        self.assertEqual(len(prov), 4)
        self.assertIn("hostname", prov)
        self.assertEqual(set(prov.keys()), {"hostname", "pid", "python_version", "boot_time"})

    def test_getitem_and_get(self):
        prov = EnvironmentMetadataProvider()
        self.assertEqual(prov["pid"], os.getpid())
        self.assertEqual(prov.get("missing", "fallback"), "fallback")

    def test_as_dict_returns_immutable_mapping(self):
        prov = EnvironmentMetadataProvider()
        d = prov.as_dict()
        self.assertIsInstance(d, MappingProxyType)
        with self.assertRaises(TypeError):
            d["pid"] = 0  # type: ignore[index]

    def test_snapshot_fixed_at_init(self):
        # PID does not change between init and later access on the same instance.
        prov = EnvironmentMetadataProvider()
        first = prov["pid"]
        self.assertEqual(first, os.getpid())
        self.assertEqual(first, prov["pid"])

    def test_now_fn_used_at_init_only(self):
        calls = {"n": 0}

        def fake_now():
            calls["n"] += 1
            return 5_000.0

        prov = EnvironmentMetadataProvider(now_fn=fake_now)
        self.assertEqual(calls["n"], 1)
        # Accessing fields later must not re-invoke the clock.
        _ = prov["boot_time"]
        _ = prov["pid"]
        self.assertEqual(calls["n"], 1)


class TestHostnameFallback(unittest.TestCase):
    def test_sentinel_when_gethostname_returns_empty(self):
        import environment_metadata_provider.core as core

        original = core.socket.gethostname
        core.socket.gethostname = lambda: ""
        try:
            meta = collect_environment_metadata()
            self.assertEqual(meta["hostname"], "<unknown-host>")
        finally:
            core.socket.gethostname = original

    def test_sentinel_when_gethostname_raises(self):
        import environment_metadata_provider.core as core

        def _raise():
            raise OSError("no hostname")

        original = core.socket.gethostname
        core.socket.gethostname = _raise
        try:
            meta = collect_environment_metadata()
            self.assertEqual(meta["hostname"], "<unknown-host>")
        finally:
            core.socket.gethostname = original


class TestBootTimeFunction(unittest.TestCase):
    def test_boot_time_returns_float(self):
        # We do not assert on the actual value (wall-clock dependent); only
        # the type contract and the monotonic relationship with 'now'.
        b = boot_time()
        self.assertIsInstance(b, float)
        import time
        # boot_time must be at or before 'now'; allow generous slack.
        self.assertLessEqual(b, time.time() + 5.0)


class TestPythonVersionString(unittest.TestCase):
    def test_version_string_format(self):
        meta = collect_environment_metadata()
        v = sys.version_info
        self.assertEqual(
            meta["python_version"],
            "{}.{}.{}".format(v.major, v.minor, v.micro),
        )


if __name__ == "__main__":
    unittest.main()
