"""Packaged ETW helper: fixed setup actions and a single owned collector session."""

import argparse
import hashlib
import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

import pywintypes
import win32api
import win32con
import win32file
import win32security
from win32com.shell import shell

from time_tracker.platform.windows.etw_collector import collect
from time_tracker.platform.windows.event_pipe import EventPipeServer, user_sid
from time_tracker.platform.windows.managed_etw import (
    CHANNEL,
    HELPER_NAME,
    com_apartment,
    find_task,
    install_directory,
    scheduler,
    task_name,
    validate_user_sid,
)

ADMIN_SIDS = {"S-1-5-18", "S-1-5-32-544"}
DIRECTORY_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;BU)"


def check_protected(path):
    """Refuse reparse points and objects writable/owned by unprivileged identities."""
    path = Path(path)
    if path.is_symlink() or path.is_junction():
        raise PermissionError("ETW installation path must not be a link")
    descriptor = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    owner = win32security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
    # Program Files itself can be owned by TrustedInstaller; only child objects use this check.
    if owner not in ADMIN_SIDS:
        raise PermissionError("ETW installation must be owned by Administrators or SYSTEM")
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        raise PermissionError("ETW installation has no access control")
    # Generic write/all, DELETE, WRITE_DAC/OWNER, write/append/EA/attributes.
    write_mask = 0x500D0156
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE:
            raise PermissionError("Unexpected ETW installation access rule")
        sid = win32security.ConvertSidToStringSid(ace[2])
        if sid not in ADMIN_SIDS and ace[1] & write_mask:
            raise PermissionError("ETW installation is writable by an unprivileged account")


def protected_directory(sid):
    path = install_directory(sid)
    if path.parent.is_symlink() or path.parent.is_junction():
        raise PermissionError("Program Files must not be redirected")
    if not path.exists():
        security = pywintypes.SECURITY_ATTRIBUTES()
        security.SECURITY_DESCRIPTOR = (
            win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                DIRECTORY_SDDL, win32security.SDDL_REVISION_1
            )
        )
        win32file.CreateDirectory(str(path), security)
        administrators = win32security.ConvertStringSidToSid("S-1-5-32-544")
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION,
            administrators,
            None,
            None,
            None,
        )
    check_protected(path)
    return path


def verify_owned_task(task, sid, directory, *, require_files=True):
    definition = task.Definition
    account = definition.Principal.UserId
    try:
        principal = win32security.ConvertStringSidToSid(account)
    except pywintypes.error:
        # Task Scheduler can return a localized name after registration even
        # when the principal was originally specified as S-1-5-18.
        principal = win32security.LookupAccountName(None, account)[0]
    if win32security.ConvertSidToStringSid(principal) != "S-1-5-18":
        raise PermissionError("Unexpected ETW task account")
    if definition.Actions.Count != 1:
        raise PermissionError("Unexpected ETW task actions")
    action = definition.Actions.Item(1)
    executable = Path(action.Path)
    if (
        executable.parent.parent != directory
        or not executable.parent.name.startswith("version-")
        or executable.name != HELPER_NAME
        or action.Arguments != f"--serve --owner-sid {sid}"
    ):
        raise PermissionError("Unexpected ETW task command")
    if require_files:
        check_protected(directory)
        check_protected(executable.parent)
        check_protected(executable)


def package_nodes(directory):
    """Bound a package tree without following junctions or symbolic links."""
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink() or entry.is_junction():
            raise PermissionError("Collector package must not contain links")
        yield entry
        if entry.is_dir():
            yield from package_nodes(entry)
        elif not entry.is_file():
            raise PermissionError("Unexpected collector package entry")


def package_digest(directory):
    digest = hashlib.sha256()
    for file in package_nodes(directory):
        if file.is_dir():
            continue
        digest.update(file.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def remove_version(path, directory):
    if path.parent != directory or not path.name.startswith("version-"):
        raise PermissionError("Not an owned collector version")
    check_protected(directory)
    check_protected(path)
    # Verify all nodes before a recursive removal, including empty directories.
    for node in package_nodes(path):
        check_protected(node)
    shutil.rmtree(path)


def register_task(service, folder, sid, executable):
    definition = service.NewTask(0)
    definition.RegistrationInfo.Description = "TimeTracker: process events for one local user"
    definition.Principal.UserId = "S-1-5-18"
    definition.Principal.LogonType = 5  # TASK_LOGON_SERVICE_ACCOUNT
    definition.Principal.RunLevel = 1
    settings = definition.Settings
    settings.Enabled = True
    settings.AllowDemandStart = True
    settings.DisallowStartIfOnBatteries = False
    settings.StopIfGoingOnBatteries = False
    settings.ExecutionTimeLimit = "PT0S"
    settings.MultipleInstances = 2  # IGNORE_NEW
    settings.WakeToRun = False
    settings.AllowHardTerminate = False
    action = definition.Actions.Create(0)
    action.Path = str(executable)
    action.Arguments = f"--serve --owner-sid {sid}"
    action.WorkingDirectory = str(executable.parent)
    # No logon trigger: the normal app (including its HKCU autostart) starts this
    # on-demand task only when ETW is selected. The user can read/run, never edit it.
    return folder.RegisterTaskDefinition(
        task_name(sid),
        definition,
        6,
        "S-1-5-18",
        None,
        5,
        f"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGX;;;{sid})",
    )


@com_apartment
def install(sid):
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Install the packaged TimeTrackerETW.exe, not a Python interpreter")
    directory = protected_directory(sid)
    with scheduler() as (service, folder):
        previous = find_task(folder, sid)
        if previous is not None:
            verify_owned_task(previous, sid, directory, require_files=False)
            if previous.State in (2, 4):
                raise RuntimeError("Закройте приложение с ETW и повторите установку компонента.")
        source = Path(sys.executable).parent
        if not (source / "_internal").is_dir() or Path(sys.executable).name != HELPER_NAME:
            raise RuntimeError("A complete collector folder package is required")
        digest = package_digest(source)
        version = directory / ("version-" + digest)
        executable = version / HELPER_NAME
        if version.exists():
            check_protected(version)
            if package_digest(version) != digest:
                remove_version(version, directory)
        if not version.exists():
            temporary = directory / ("version-staging-" + uuid4().hex)
            try:
                shutil.copytree(source, temporary, symlinks=True)
                nodes = list(package_nodes(temporary))
                administrators = win32security.ConvertStringSidToSid("S-1-5-32-544")
                for node in [temporary, *nodes]:
                    win32security.SetNamedSecurityInfo(
                        str(node),
                        win32security.SE_FILE_OBJECT,
                        win32security.OWNER_SECURITY_INFORMATION,
                        administrators,
                        None,
                        None,
                        None,
                    )
                if package_digest(temporary) != digest:
                    raise OSError("Collector package changed while copying")
                temporary.rename(version)
            finally:
                if temporary.exists():
                    remove_version(temporary, directory)
        check_protected(version)
        check_protected(executable)
        if package_digest(version) != digest:
            raise OSError("Installed collector does not match the package")
        register_task(service, folder, sid, executable)
        # Older immutable versions are harmless; remove only after registration succeeds.
        for old in directory.glob("version-*"):
            if old != version:
                try:
                    remove_version(old, directory)
                except OSError:
                    # A locked previous version must not report a failed installation
                    # after the replacement task has already been committed.
                    pass


@com_apartment
def remove(sid):
    directory = install_directory(sid)
    if directory.exists():
        check_protected(directory)
    with scheduler() as (_, folder):
        task = find_task(folder, sid)
        if task is not None:
            verify_owned_task(task, sid, directory, require_files=False)
            if task.State in (2, 4):
                raise RuntimeError("Закройте приложение с ETW и повторите удаление компонента.")
            folder.DeleteTask(task_name(sid), 0)
    if directory.exists():
        for path in directory.iterdir():
            if path.name in {"collector.log", "collector.log.1", "collector.log.2"}:
                check_protected(path)
                path.unlink()
            else:
                remove_version(path, directory)
        directory.rmdir()


def serve(sid):
    if user_sid() != "S-1-5-18":
        raise PermissionError("Managed collector must be started by its Windows task")
    directory = install_directory(sid)
    check_protected(directory)
    handler = RotatingFileHandler(
        directory / "collector.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("time_tracker.managed_collector")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        with EventPipeServer(CHANNEL, owner_sid=sid) as pipe:
            try:
                pipe.accept(60000)
            except TimeoutError:
                return  # No app: do not keep a privileged background process alive.
            logger.info("Reader connected; starting ETW")
            collect(pipe, None)  # Finish/disconnect, not an arbitrary 24-hour deadline.
            logger.info("ETW final delivery completed")
    except Exception:
        logger.exception("Managed ETW collector stopped")
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--remove", action="store_true")
    actions.add_argument("--serve", action="store_true")
    parser.add_argument("--owner-sid", required=True)
    args = parser.parse_args(argv)
    try:
        sid = validate_user_sid(args.owner_sid)
        if args.serve:
            serve(sid)
        else:
            if not shell.IsUserAnAdmin():
                raise PermissionError("Установка и удаление требуют подтверждения администратора.")
            (install if args.install else remove)(sid)
        return 0
    except Exception as error:
        if not args.serve:
            win32api.MessageBox(
                0, str(error), "TimeTracker — фоновый компонент", win32con.MB_ICONERROR
            )
        return 1
