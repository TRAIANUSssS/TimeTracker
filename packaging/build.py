"""Build an offline Windows folder distribution and a portable ZIP from this checkout."""

import shutil
import subprocess
import sys
import zipfile
from importlib.metadata import distribution
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def make_version_file(work: Path) -> Path:
    from time_tracker import __version__

    numeric = [int(part) for part in __version__.split(".")]
    version = tuple((numeric + [0, 0, 0, 0])[:4])
    version_text = ".".join(map(str, version))
    path = work / "version-info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version},
    prodvers={version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'TimeTracker'),
        StringStruct('FileDescription', 'TimeTracker'),
        StringStruct('FileVersion', '{version_text}'),
        StringStruct('InternalName', 'TimeTracker'),
        StringStruct('OriginalFilename', 'TimeTracker.exe'),
        StringStruct('ProductName', 'TimeTracker'),
        StringStruct('ProductVersion', '{version_text}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""",
        encoding="utf-8",
    )
    return path


def make_icon():
    image = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 255, 255), radius=70, fill="#F16D9F")
    draw.ellipse((48, 48, 208, 208), outline="white", width=16)
    draw.line([(128, 80), (128, 132), (164, 156)], fill="white", width=16, joint="curve")
    for x, y in [(128, 80), (128, 132), (164, 156)]:
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill="white")
    image.save(
        ROOT / "packaging" / "timetracker.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def main():
    if sys.platform != "win32":
        raise SystemExit("Build the Windows distribution on Windows")
    npm = shutil.which("npm.cmd")
    if npm is None:
        raise SystemExit("Node.js 22.12+ is required to build the frontend")
    subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    make_icon()
    output, work = (ROOT / "dist").resolve(), (ROOT / "build").resolve()
    if output.parent != ROOT or work.parent != ROOT:
        raise RuntimeError("Build outputs must remain directly inside the project")
    version_file = make_version_file(work)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--windowed",
            "--name",
            "TimeTracker",
            "--distpath",
            str(output),
            "--workpath",
            str(work),
            "--specpath",
            str(work),
            "--paths",
            str(ROOT / "src"),
            "--icon",
            str(ROOT / "packaging" / "timetracker.ico"),
            "--version-file",
            str(version_file),
            "--add-data",
            f"{ROOT / 'frontend' / 'dist'};web",
            "--add-data",
            f"{ROOT / 'packaging' / 'timetracker.ico'};.",
            "--collect-all",
            "tzdata",
            "--collect-submodules",
            "uvicorn",
            "--hidden-import",
            "win32timezone",
            str(ROOT / "packaging" / "entrypoint.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    package = output / "TimeTracker"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--windowed",
            "--name",
            "TimeTrackerETW",
            "--distpath",
            str(package / "collector"),
            "--workpath",
            str(work / "etw-helper"),
            "--specpath",
            str(work),
            "--paths",
            str(ROOT / "src"),
            "--hidden-import",
            "win32timezone",
            str(ROOT / "packaging" / "etw_entrypoint.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    shutil.copyfile(ROOT / "packaging" / "README.txt", package / "README.txt")
    license_dir = package / "licenses"
    license_dir.mkdir(exist_ok=True)
    # Fonts are served locally, with their redistribution license alongside the app.
    shutil.copyfile(
        ROOT / "frontend/node_modules/@fontsource-variable/manrope/LICENSE",
        license_dir / "Manrope-OFL.txt",
    )
    for name in ("react", "react-dom", "scheduler"):
        shutil.copyfile(
            ROOT / "frontend/node_modules" / name / "LICENSE", license_dir / f"{name}-LICENSE.txt"
        )
    for name in (
        "fastapi",
        "starlette",
        "pydantic",
        "pydantic-core",
        "uvicorn",
        "psutil",
        "pywin32",
        "pillow",
        "tzdata",
        "anyio",
        "click",
        "h11",
        "idna",
        "typing-extensions",
        "annotated-types",
        "annotated-doc",
        "typing-inspection",
    ):
        package_info = distribution(name)
        for file in package_info.files or ():
            if any(
                part.lower().startswith(("license", "copying", "notice")) for part in file.parts
            ):
                source = Path(package_info.locate_file(file))
                if source.is_file():
                    target = license_dir / name / Path(*file.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, license_dir / "Python-LICENSE.txt")
    with zipfile.ZipFile(
        output / "TimeTracker-windows-x64.zip", "w", zipfile.ZIP_DEFLATED
    ) as archive:
        for file in package.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(output))
    print(f"Built: {package / 'TimeTracker.exe'}")
    print(f"Archive: {output / 'TimeTracker-windows-x64.zip'}")


if __name__ == "__main__":
    main()
