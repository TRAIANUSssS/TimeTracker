from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
import pywintypes
import win32security

from time_tracker.platform.windows import etw_setup, managed_etw
from time_tracker.platform.windows.event_pipe import EventPipeClient, EventPipeServer, user_sid


def test_task_is_on_demand_system_bounded_to_user_and_protected_path(tmp_path):
    service = Mock()
    folder = Mock()
    definition = service.NewTask.return_value
    executable = tmp_path / "TimeTrackerETW.exe"
    sid = user_sid()
    etw_setup.register_task(service, folder, sid, executable)
    assert definition.Principal.UserId == "S-1-5-18"
    assert definition.Principal.LogonType == 5
    assert definition.Settings.ExecutionTimeLimit == "PT0S"
    assert not definition.Settings.WakeToRun
    assert not definition.Settings.StopIfGoingOnBatteries
    assert not definition.Settings.DisallowStartIfOnBatteries
    assert definition.Settings.MultipleInstances == 2
    assert not definition.Triggers.Create.called
    action = definition.Actions.Create.return_value
    assert action.Path == str(executable)
    assert action.Arguments == f"--serve --owner-sid {sid}"
    args = folder.RegisterTaskDefinition.call_args.args
    assert args[5] == 5 and args[4] is None
    assert f"(A;;GRGX;;;{sid})" in args[6]
    assert f"(A;;GA;;;{sid})" not in args[6]


def test_managed_pipe_preserves_current_user_delivery_and_acl():
    channel = uuid4().hex
    with (
        EventPipeServer(channel, owner_sid=user_sid()) as server,
        EventPipeClient(channel) as client,
    ):
        server.accept(500)
        server.send({"schema_version": 1})
        assert client.receive() == {"schema_version": 1}
        descriptor = win32security.GetSecurityInfo(
            server.handle, win32security.SE_KERNEL_OBJECT, win32security.DACL_SECURITY_INFORMATION
        )
        acl = descriptor.GetSecurityDescriptorDacl()
        assert {
            win32security.ConvertSidToStringSid(acl.GetAce(i)[2]) for i in range(acl.GetAceCount())
        } == {user_sid(), "S-1-5-18"}


@pytest.mark.parametrize("sid", ["S-1-5-18", "S-1-5-32-544", "../bad"])
def test_setup_rejects_non_user_identity(sid):
    with pytest.raises((ValueError, pywintypes.error)):
        managed_etw.validate_user_sid(sid)


def test_existing_task_with_arbitrary_action_is_not_modified(tmp_path):
    action = SimpleNamespace(Path=str(tmp_path / "bad.exe"), Arguments="--serve")
    task = SimpleNamespace(
        Definition=SimpleNamespace(
            Principal=SimpleNamespace(UserId="S-1-5-18"),
            Actions=SimpleNamespace(Count=1, Item=lambda _: action),
        )
    )
    with pytest.raises(PermissionError):
        etw_setup.verify_owned_task(task, user_sid(), tmp_path)


@pytest.mark.parametrize("account", ["S-1-5-18", "SYSTEM", "СИСТЕМА", "AUTORITE NT\\Système"])
def test_task_account_is_verified_by_sid_not_display_name(monkeypatch, tmp_path, account):
    sid = user_sid()
    action = SimpleNamespace(
        Path=str(tmp_path / "version-test" / "TimeTrackerETW.exe"),
        Arguments=f"--serve --owner-sid {sid}",
    )
    task = SimpleNamespace(
        Definition=SimpleNamespace(
            Principal=SimpleNamespace(UserId=account),
            Actions=SimpleNamespace(Count=1, Item=lambda _: action),
        )
    )
    lookup = Mock(return_value=(win32security.ConvertStringSidToSid("S-1-5-18"), "NT AUTHORITY", 5))
    monkeypatch.setattr(win32security, "LookupAccountName", lookup)
    etw_setup.verify_owned_task(task, sid, tmp_path, require_files=False)
    if account == "S-1-5-18":
        lookup.assert_not_called()
    else:
        lookup.assert_called_once_with(None, account)


def test_task_account_display_name_cannot_override_wrong_sid(monkeypatch, tmp_path):
    task = SimpleNamespace(
        Definition=SimpleNamespace(
            Principal=SimpleNamespace(UserId="SYSTEM"),
        )
    )
    monkeypatch.setattr(
        win32security,
        "LookupAccountName",
        lambda *_: (win32security.ConvertStringSidToSid(user_sid()), "", 1),
    )
    with pytest.raises(PermissionError, match="account"):
        etw_setup.verify_owned_task(task, user_sid(), tmp_path, require_files=False)


def test_acl_rejects_user_write_even_with_admin_owner(monkeypatch, tmp_path):
    sid = user_sid()
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"O:BAD:P(A;;FA;;;BA)(A;;FA;;;{sid})", 1
    )
    monkeypatch.setattr(win32security, "GetNamedSecurityInfo", lambda *_: descriptor)
    with pytest.raises(PermissionError, match="writable"):
        etw_setup.check_protected(tmp_path)
    readonly = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        "O:BAD:P(A;;FA;;;BA)(A;;FRFX;;;BU)", 1
    )
    monkeypatch.setattr(win32security, "GetNamedSecurityInfo", lambda *_: readonly)
    etw_setup.check_protected(tmp_path)


def test_package_digest_covers_dependencies_and_refuses_links(tmp_path, monkeypatch):
    (tmp_path / "_internal").mkdir()
    dependency = tmp_path / "_internal" / "python.dll"
    dependency.write_bytes(b"v1")
    before = etw_setup.package_digest(tmp_path)
    dependency.write_bytes(b"v2")
    assert etw_setup.package_digest(tmp_path) != before
    monkeypatch.setattr(Path, "is_junction", lambda p: p.name == "_internal")
    with pytest.raises(PermissionError, match="links"):
        etw_setup.package_digest(tmp_path)


def test_remove_refuses_paths_outside_owned_version(tmp_path):
    with pytest.raises(PermissionError):
        etw_setup.remove_version(tmp_path.parent, tmp_path)


def test_serve_has_no_fixed_lifetime(monkeypatch, tmp_path):
    monkeypatch.setattr(etw_setup, "user_sid", lambda: "S-1-5-18")
    factory = MagicMock()
    collect = Mock()
    monkeypatch.setattr(etw_setup, "EventPipeServer", factory)
    monkeypatch.setattr(etw_setup, "collect", collect)
    monkeypatch.setattr(etw_setup, "install_directory", lambda _: tmp_path)
    monkeypatch.setattr(etw_setup, "check_protected", lambda _: None)
    sid = user_sid()
    etw_setup.serve(sid)
    factory.assert_called_once_with("managed", owner_sid=sid)
    collect.assert_called_once_with(factory.return_value.__enter__.return_value, None)


def test_missing_task_dispatch_exception_is_absence_not_failure():
    folder = Mock()
    folder.GetTask.side_effect = pywintypes.com_error(
        -2147352567, "Dispatch exception", (0, None, None, None, 0, -2147024894), None
    )
    assert managed_etw.find_task(folder, user_sid()) is None
    folder.GetTask.side_effect = pywintypes.com_error(-2147024891, "Access denied", None, None)
    with pytest.raises(pywintypes.com_error):
        managed_etw.find_task(folder, user_sid())


def test_scheduler_failure_becomes_retryable_reader_error(monkeypatch):
    backend = managed_etw.ManagedEtw()

    def fail():
        raise pywintypes.com_error(-2147024891, "Access denied", None, None)

    monkeypatch.setattr(backend, "ensure_running", fail)
    with pytest.raises(OSError, match="installed ETW task"):
        backend.client("managed", control=True)


def test_uninstall_does_not_delete_running_task_or_files(tmp_path, monkeypatch):
    from contextlib import contextmanager

    task = SimpleNamespace(State=4)
    folder = Mock()

    @contextmanager
    def fake_scheduler():
        yield Mock(), folder

    monkeypatch.setattr(etw_setup, "scheduler", fake_scheduler)
    monkeypatch.setattr(etw_setup, "install_directory", lambda _: tmp_path)
    monkeypatch.setattr(etw_setup, "check_protected", lambda _: None)
    monkeypatch.setattr(etw_setup, "find_task", lambda *_: task)
    monkeypatch.setattr(etw_setup, "verify_owned_task", lambda *a, **kw: None)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("preserve")
    with pytest.raises(RuntimeError, match="Закройте"):
        etw_setup.remove(user_sid())
    assert sentinel.read_text() == "preserve"
    folder.DeleteTask.assert_not_called()


@pytest.mark.parametrize("cancel", [True, False])
def test_setup_shell_request_and_uac_cancellation(monkeypatch, tmp_path, cancel):
    helper = tmp_path / "TimeTrackerETW.exe"
    helper.write_bytes(b"test")
    monkeypatch.setattr(managed_etw, "bundled_helper", lambda: helper)
    execute = Mock(return_value={"hProcess": 123})
    if cancel:
        execute.side_effect = pywintypes.error(1223, "ShellExecuteEx", "Cancelled")
    monkeypatch.setattr(managed_etw.shell, "ShellExecuteEx", execute)
    wait = Mock(return_value=0)
    close = Mock()
    monkeypatch.setattr(managed_etw.win32event, "WaitForSingleObject", wait)
    monkeypatch.setattr(managed_etw.win32process, "GetExitCodeProcess", lambda _: 0)
    monkeypatch.setattr(managed_etw.win32api, "CloseHandle", close)
    backend = managed_etw.ManagedEtw()
    if cancel:
        with pytest.raises(PermissionError, match="отменено"):
            backend.configure("install")
        wait.assert_not_called()
        close.assert_not_called()
    else:
        backend.configure("install")
        close.assert_called_once_with(123)
    request = execute.call_args.kwargs
    assert request["lpVerb"] == "runas"
    assert request["lpFile"] == str(helper)
    assert request["lpParameters"] == f"--install --owner-sid {backend.sid}"


@pytest.fixture
def setup_package(tmp_path, monkeypatch):
    from contextlib import contextmanager

    source = tmp_path / "package"
    source.mkdir()
    (source / "TimeTrackerETW.exe").write_bytes(b"executable")
    (source / "_internal").mkdir()
    (source / "_internal" / "dependency.dll").write_bytes(b"dependency v1")
    target = tmp_path / "protected-install"
    target.mkdir()
    committed = []
    register = Mock(side_effect=lambda _s, _f, _sid, exe: committed.append(exe))

    @contextmanager
    def fake_scheduler():
        yield Mock(), Mock()

    monkeypatch.setattr(etw_setup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(etw_setup.sys, "executable", str(source / "TimeTrackerETW.exe"))
    monkeypatch.setattr(etw_setup, "protected_directory", lambda _: target)
    monkeypatch.setattr(etw_setup, "scheduler", fake_scheduler)
    monkeypatch.setattr(etw_setup, "find_task", lambda *_: None)
    monkeypatch.setattr(etw_setup, "check_protected", lambda _: None)
    monkeypatch.setattr(etw_setup.win32security, "SetNamedSecurityInfo", lambda *_: None)
    monkeypatch.setattr(etw_setup, "register_task", register)
    return source, target, committed, register


def test_install_copies_dependencies_and_repair_restores_missing_file(setup_package):
    source, target, committed, _ = setup_package
    etw_setup.install(user_sid())
    executable = committed[-1]
    assert executable.parent.parent == target
    dependency = executable.parent / "_internal" / "dependency.dll"
    assert dependency.read_bytes() == b"dependency v1"
    dependency.unlink()
    etw_setup.install(user_sid())
    assert committed[-1] == executable
    assert dependency.read_bytes() == b"dependency v1"
    (source / "_internal" / "dependency.dll").write_bytes(b"dependency v2")
    etw_setup.install(user_sid())
    assert committed[-1] != executable
    assert not executable.parent.exists()
    assert not list(target.glob("version-staging-*"))


def test_failed_task_registration_preserves_previous_version(setup_package):
    source, _, committed, register = setup_package
    etw_setup.install(user_sid())
    previous = committed[-1]
    (source / "_internal" / "dependency.dll").write_bytes(b"new version")
    register.side_effect = OSError("Registration failed")
    with pytest.raises(OSError, match="Registration failed"):
        etw_setup.install(user_sid())
    assert committed[-1] == previous
    assert previous.is_file()
