import pytest

from time_tracker.domain.process_catalog import ProcessCategory, classify_executable
from time_tracker.storage.process_catalog import refresh_process_catalog
from time_tracker.storage.repositories import Repositories


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Windows\System32\svchost.exe",
        r"C:\Windows\SysWOW64\dllhost.exe",
        r"C:\Windows\System32\wbem\WmiPrvSE.exe",
        r"C:\Windows\Servicing\TrustedInstaller.exe",
    ],
)
def test_catalog_recognizes_exact_windows_system_locations(path):
    assert classify_executable(path, windows_root=r"C:\Windows") is ProcessCategory.SYSTEM


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Apps\svchost.exe", ProcessCategory.USER),
        (r"C:\Windows\Temp\svchost.exe", ProcessCategory.UNKNOWN),
        (r"C:\Windows\System32\cmd.exe", ProcessCategory.UNKNOWN),
        (r"C:\Windows\explorer.exe", ProcessCategory.UNKNOWN),
        (r"D:\Tools\editor.exe", ProcessCategory.USER),
    ],
)
def test_catalog_does_not_hide_name_matches_or_interactive_windows_tools(path, expected):
    assert classify_executable(path, windows_root=r"C:\Windows") is expected


def test_catalog_refresh_classifies_existing_apps_without_changing_visibility(database):
    with database.transaction() as connection:
        repo = Repositories(connection)
        system = repo.applications.create("Service Host", at=100, ignored=False)
        repo.executables.create(system.id, r"C:\Windows\System32\svchost.exe", at=100)
        user = repo.applications.create("Editor", at=100, ignored=True)
        repo.executables.create(user.id, r"C:\Apps\Editor.exe", at=100)
        assert refresh_process_catalog(connection, windows_root=r"C:\Windows") == 2

    with database.reader() as connection:
        repo = Repositories(connection)
        refreshed_system = repo.applications.get(system.id)
        refreshed_user = repo.applications.get(user.id)
        assert refreshed_system.category == "system"
        assert refreshed_system.ignored is False
        assert refreshed_user.category == "user"
        assert refreshed_user.ignored is True
