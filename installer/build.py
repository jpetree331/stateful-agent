"""
Build script: produces dist/AgentInstaller.exe using PyInstaller.

Usage (from the project root):
    cd installer
    pip install -r requirements.txt
    python build.py

Or from the project root:
    python installer/build.py

The output EXE is placed in installer/dist/AgentInstaller.exe.
Copy it to the project root before distributing.

Windows Defender / SmartScreen note:
    The EXE will trigger a SmartScreen "unknown publisher" warning until it
    accumulates enough download reputation OR is signed with a code-signing
    certificate. This is normal for any unsigned open-source installer.
    Users can click "More info → Run anyway" to proceed.
    The version-file metadata embedded by this script (product name, description,
    version) reduces false-positive AV detections from scanners that flag
    completely metadata-free EXEs.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
ROOT = HERE.parent

# ── EXE version metadata (embedded into the PE header) ───────────────────────
# This makes the EXE look legitimate to AV scanners and shows proper info in
# Windows Explorer → Properties → Details.
VERSION_FILE_CONTENT = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Stateful Agent Project'),
         StringStruct(u'FileDescription', u'Stateful Agent Installer'),
         StringStruct(u'FileVersion', u'1.0.0'),
         StringStruct(u'InternalName', u'AgentInstaller'),
         StringStruct(u'LegalCopyright', u'Open Source - MIT License'),
         StringStruct(u'OriginalFilename', u'AgentInstaller.exe'),
         StringStruct(u'ProductName', u'Stateful Agent'),
         StringStruct(u'ProductVersion', u'1.0.0')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    icon_path = HERE / "assets" / "icon.ico"
    main_script = HERE / "main.py"
    version_file = HERE / "build_tmp" / "version_info.txt"

    # Write version metadata file
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(VERSION_FILE_CONTENT, encoding="utf-8")

    # Build the --add-data arguments for bundled assets
    add_data: list[str] = []

    if (HERE / "assets").exists():
        add_data += ["--add-data", f"{HERE / 'assets'}{os.pathsep}assets"]

    # Collect hidden imports that PyInstaller might miss
    hidden_imports = [
        "customtkinter",
        "PIL",
        "PIL._tkinter_finder",
        "psycopg",
        "psycopg.binary",
        "packaging",
        "tkinter",
        "tkinter.filedialog",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "AgentInstaller",
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build_tmp"),
        "--specpath", str(HERE),
        "--version-file", str(version_file),
        "--clean",
        "--noconfirm",
    ]

    if icon_path.exists():
        cmd += ["--icon", str(icon_path)]

    for imp in hidden_imports:
        cmd += ["--hidden-import", imp]

    for item in add_data:
        cmd.append(item)

    # Add the installer/ directory to the path so `wizard` package is importable
    cmd += ["--paths", str(HERE)]

    cmd.append(str(main_script))

    print("Running PyInstaller...")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=str(HERE))

    if result.returncode == 0:
        exe_path = HERE / "dist" / "AgentInstaller.exe"
        print()
        print(f"Build successful!")
        print(f"EXE: {exe_path}")
        print()
        print("To distribute: copy AgentInstaller.exe to the project root folder.")
        print("Users double-click it to run the installer.")
    else:
        print()
        print("Build FAILED. Check the output above for errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
