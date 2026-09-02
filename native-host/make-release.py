r"""
make-release.py - builds the zip you hand to somebody else.

One command, from this folder:

    ..\.venv\Scripts\python.exe make-release.py

It freezes host.exe from host.spec and then packages it. Pass --no-build to
skip the freeze and reuse whatever is already in dist\host.

Produces Desktop\video-downloader.zip containing:

    video-downloader\
        INSTALL.md
        install.ps1
        uninstall.ps1
        extension\      <- loaded via chrome://extensions
        host\           <- host.exe and the runtime it needs
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
BUILT_HOST = HERE / "dist" / "host"
EXTENSION = PROJECT / "chrome-extension"
SPEC = HERE / "host.spec"

STAGING = HERE / "release" / "video-downloader"
ZIP_PATH = Path.home() / "Desktop" / "video-downloader.zip"

# Anything matching these never goes in the zip. The private key would let
# someone else publish under this extension's identity; the .json and .log are
# specific to whichever machine built it.
NEVER_SHIP = {
    "extension-private-key.pem",
    "com.mediadownload.host.json",
    "host.log",
}


def check(condition, message):
    if not condition:
        print(f"ERROR: {message}")
        sys.exit(1)


def build():
    """
    Freeze host.exe from host.spec.

    The spec is the part that matters: it names the modules PyInstaller can't
    find by reading the code, which is most of them here. Building from the
    spec rather than a command line means the shared build can never quietly
    miss an extractor that the source version has.
    """
    print("Freezing host.exe (a couple of minutes)...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=HERE,
    )
    check(result.returncode == 0, "PyInstaller failed - see the output above")


def smoke_test():
    """
    Prove the frozen build can actually import what it needs.

    A missing hidden import doesn't show up until the exe runs, and by then it
    is in somebody else's hands. Running it with a closed pipe makes it start
    up, import everything, find nothing to do and exit - which is exactly the
    part that breaks.
    """
    exe = BUILT_HOST / "host.exe"
    result = subprocess.run([str(exe)], input=b"", capture_output=True, timeout=120)
    log = HERE / "host.log"
    problem = ""
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        problem = " | ".join(line for line in tail if "crash" in line.lower())
    check(result.returncode == 0 and not problem,
          f"the frozen host.exe won't start: {problem or result.stderr[:300]}")
    print("host.exe starts and imports cleanly")


def main():
    if "--no-build" not in sys.argv:
        build()

    check(BUILT_HOST.is_dir(), f"{BUILT_HOST} not found - build host.exe first (see the docstring)")
    check((BUILT_HOST / "host.exe").is_file(), "host.exe missing from the build output")
    check(EXTENSION.is_dir(), f"{EXTENSION} not found")

    smoke_test()

    # The extension must carry its "key", or every friend gets a different
    # extension ID and the ID baked into install.ps1 stops matching.
    manifest_text = (EXTENSION / "manifest.json").read_text(encoding="utf-8")
    check('"key"' in manifest_text, "chrome-extension/manifest.json has no \"key\" - run make-key.py")

    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)

    def ignored(_directory, names):
        return [n for n in names if n in NEVER_SHIP or n.endswith(".pem")]

    shutil.copytree(EXTENSION, STAGING / "extension", ignore=ignored)
    shutil.copytree(BUILT_HOST, STAGING / "host", ignore=ignored)
    shutil.copy2(HERE / "install.ps1", STAGING / "install.ps1")
    shutil.copy2(HERE / "uninstall.ps1", STAGING / "uninstall.ps1")
    shutil.copy2(PROJECT / "INSTALL.md", STAGING / "INSTALL.md")

    # Belt and braces: the ignore filter above should have caught these, but a
    # leaked private key is not a mistake worth risking on one code path.
    for path in STAGING.rglob("*"):
        check(
            path.name not in NEVER_SHIP and path.suffix != ".pem",
            f"{path} should never be shipped",
        )

    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING.parent))

    size_mb = ZIP_PATH.stat().st_size / 1_000_000
    files = sum(1 for p in STAGING.rglob("*") if p.is_file())
    print(f"{ZIP_PATH}")
    print(f"  {files} files, {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
