"""Tests for synthetic_service memory-probe fallbacks (no psutil)."""

import builtins

from src.services import synthetic_service as ss


def _block_psutil(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("psutil not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_system_free_gb_darwin_vm_stat(monkeypatch):
    _block_psutil(monkeypatch)
    monkeypatch.setattr(ss.platform, "system", lambda: "Darwin")

    vm_stat = (
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free:                               1000.\n"
        "Pages speculative:                         500.\n"
        "Pages inactive:                            500.\n"
    )

    class _Result:
        stdout = vm_stat

    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _Result())
    free = ss._system_free_gb()
    assert free > 0


def test_system_free_gb_proc_meminfo(monkeypatch):
    _block_psutil(monkeypatch)
    monkeypatch.setattr(ss.platform, "system", lambda: "Linux")

    class _FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(["MemTotal: 16000000 kB\n", "MemAvailable: 4000000 kB\n"])

    real_open = builtins.open
    monkeypatch.setattr(
        builtins, "open", lambda *a, **k: _FakeFile() if a and a[0] == "/proc/meminfo" else real_open(*a, **k)
    )
    free = ss._system_free_gb()
    assert free > 0
