r"""
make-release.py - builds the zip you hand to somebody else.

Assumes host.exe has already been built:

    ..\.venv\Scripts\python.exe -m PyInstaller --name host --onedir --console \
        --noconfirm --paths .. --hidden-import download --collect-submodules yt_dlp host.py
    ..\.venv\Scripts\python.exe make-release.py

Produces Desktop\video-downloader.zip containing:

    video-downloader\
        INSTALL.md
        install.ps1
        uninstall.ps1
        extension\      <- loaded via chrome://extensions
        host\           <- host.exe and the runtime it needs
"""

import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
BUILT_HOST = HERE / "dist" / "host"
EXTENSION = PROJECT / "chrome-extension"

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


def main():
    check(BUILT_HOST.is_dir(), f"{BUILT_HOST} not found - build host.exe first (see the docstring)")
    check((BUILT_HOST / "host.exe").is_file(), "host.exe missing from the build output")
    check(EXTENSION.is_dir(), f"{EXTENSION} not found")

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
