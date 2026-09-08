import sys
from types import SimpleNamespace

import pytest

psutil = pytest.importorskip("psutil")

from time_tracker.platform.windows.processes import ProcessCollector  # noqa: E402
from time_tracker.platform.windows.provider import WindowsProvider  # noqa: E402


class FakeProcess:
    def __init__(self, pid=42, creation=1.0, path="C:/Apps/editor.exe"):
        self.pid = pid
        self.creation = creation
        self.path = path

    def create_time(self):
        if isinstance(self.creation, Exception):
            raise self.creation
        return self.creation

    def exe(self):
        if isinstance(self.path, Exception):
            raise self.path
        return self.path


class FakeProcessAPI:
    def __init__(self, monkeypatch):
        self.items = {}
        self.clears = 0
        self.fail = False

        def iterate():
            yield from self.items.values()
            if self.fail:
                raise OSError("enumeration failed")

        def clear():
            self.clears += 1

        iterate.cache_clear = clear
        monkeypatch.setattr(psutil, "process_iter", iterate)
        monkeypatch.setattr(psutil, "Process", self.get)

    def get(self, pid):
        if pid not in self.items:
            raise psutil.NoSuchProcess(pid)
        return self.items[pid]


@pytest.fixture
def processes(monkeypatch):
    api = FakeProcessAPI(monkeypatch)
    collector = ProcessCollector(lambda _: ("Editor", "Product"))
    return api, collector


def test_fresh_identity_after_pid_reuse(processes):
    api, collector = processes
    api.items[42] = FakeProcess()
    first = collector.snapshot()[0]
    api.items[42] = FakeProcess(creation=2.0)
    second = collector.snapshot()[0]
    assert first.identity != second.identity
    assert api.clears == 2


def test_access_denied_path_is_unknown_and_does_not_remove_process(processes):
    api, collector = processes
    api.items[42] = FakeProcess(path=psutil.AccessDenied(42))
    observed = collector.snapshot()
    assert len(observed) == 1
    assert observed[0].executable_path is None
    assert observed[0].identity.creation_time == 1000


def test_unknown_creation_token_shared_with_foreground_and_reset_after_gap(processes):
    api, collector = processes
    api.items[42] = FakeProcess(creation=psutil.AccessDenied(42))
    first = collector.by_pid(42)
    assert collector.snapshot()[0].identity == first.identity
    api.items.clear()
    assert collector.snapshot() == ()
    api.items[42] = FakeProcess(creation=psutil.AccessDenied(42))
    assert collector.by_pid(42).identity != first.identity


def test_disappeared_process_is_omitted_without_breaking_other_processes(processes):
    api, collector = processes
    api.items[42] = FakeProcess(creation=psutil.NoSuchProcess(42))
    api.items[43] = FakeProcess(pid=43)
    assert [p.identity.pid for p in collector.snapshot()] == [43]


def test_partial_enumeration_failure_raises_instead_of_returning_incomplete_snapshot(processes):
    api, collector = processes
    api.items[42] = FakeProcess()
    api.fail = True
    with pytest.raises(OSError, match="enumeration failed"):
        collector.snapshot()


def test_process_reused_during_metadata_read_is_discarded(processes):
    api, collector = processes
    original = FakeProcess()
    api.items[42] = FakeProcess(creation=2)
    assert collector.observe(original) is None


def test_native_device_path_is_treated_as_unresolved(processes):
    api, collector = processes
    api.items[42] = FakeProcess(path="System")
    assert collector.snapshot()[0].executable_path is None


class FakeDesktop:
    def __init__(self):
        self.window = (10, 42, "Document")
        self.locked = False
        self.metadata_calls = 0

    def foreground(self):
        return self.window

    def is_locked(self):
        return self.locked

    def idle_ms(self):
        return 300001

    def file_metadata(self, path):
        self.metadata_calls += 1
        return "Editor", "Product"


def test_provider_reuses_metadata_and_keeps_real_idle_at_startup(processes):
    api, _ = processes
    api.items[42] = FakeProcess()
    desktop = FakeDesktop()
    provider = WindowsProvider(desktop, SimpleNamespace(now_ms=lambda: 400000))
    first = provider.snapshot()
    second = provider.snapshot()
    assert desktop.metadata_calls == 1
    assert first.last_input_at == 99999
    assert first.processes[0].identity == second.foreground.process.identity
    desktop.locked = True
    assert provider.snapshot().foreground is None


def test_foreground_owner_change_during_resolution_clears_observation(processes, monkeypatch):
    api, _ = processes
    api.items[42] = FakeProcess()
    desktop = FakeDesktop()
    windows = iter([(10, 42, "Old"), (10, 43, "New")])
    monkeypatch.setattr(desktop, "foreground", lambda: next(windows))
    provider = WindowsProvider(desktop, SimpleNamespace(now_ms=lambda: 1000))
    assert provider.foreground() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 bindings")
def test_idle_tick_wrap():
    from time_tracker.platform.windows.native import idle_duration

    assert idle_duration(0x100000064, 0xFFFFFF9C) == 200
    assert idle_duration(0x200000064, 0x00000032) == 50


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 bindings")
def test_win32_foreground_error_is_recoverable(processes, monkeypatch):
    import win32gui

    from time_tracker.platform.windows.native import WindowsAPI

    def failed():
        raise win32gui.error(5, "GetForegroundWindow", "Access denied")

    monkeypatch.setattr(win32gui, "GetForegroundWindow", failed)
    provider = WindowsProvider(WindowsAPI(), SimpleNamespace(now_ms=lambda: 1000))
    assert provider.foreground() is None


def test_icon_cache_does_not_repeat_extraction_and_survives_failure(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image

    from time_tracker.platform.windows import icons

    calls = []

    def extract(path):
        calls.append(path)
        if path == "bad":
            raise OSError("unreadable resource")
        return Image.new("RGBA", (32, 32), "red")

    monkeypatch.setattr(icons, "extract_icon", extract)
    cache = icons.IconCache(tmp_path)
    path = cache.ensure("good")
    assert path.exists()
    assert cache.ensure("good") == path
    assert icons.IconCache(tmp_path).ensure("good") == path
    assert cache.ensure("bad") is None
    assert cache.ensure("bad") is None
    assert calls == ["good", "bad"]


def test_legacy_icon_cache_is_regenerated(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image

    from time_tracker.platform.windows import icons

    destination = tmp_path / f"{icons.icon_key('example')}.png"
    Image.new("RGBA", (32, 32), "blue").save(destination)
    monkeypatch.setattr(icons, "extract_icon", lambda _: Image.new("RGBA", (32, 32), "red"))
    assert icons.IconCache(tmp_path).ensure("example") == destination
    with Image.open(destination) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)
        assert image.info["time_tracker_render_version"] == icons.ICON_RENDER_VERSION


@pytest.mark.skipif(sys.platform != "win32", reason="Native bitmap row order")
def test_native_icon_top_and_bottom_are_not_inverted(monkeypatch):
    import win32gui
    import win32ui

    from time_tracker.platform.windows.icons import extract_icon

    def draw_pattern(dc, *args):
        target = win32ui.CreateDCFromHandle(dc)
        target.FillSolidRect((0, 0, 32, 16), 0x0000FF)  # Win32 COLORREF red
        target.FillSolidRect((0, 16, 32, 32), 0xFF0000)  # blue

    monkeypatch.setattr(win32gui, "DrawIconEx", draw_pattern)
    result = extract_icon(sys.executable)
    assert result.getpixel((16, 4)) == (255, 0, 0, 255)
    assert result.getpixel((16, 28)) == (0, 0, 255, 255)
