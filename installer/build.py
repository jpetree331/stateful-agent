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
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
ROOT = HERE.parent


def main() -> None:
    icon_path = HERE / "assets" / "icon.ico"
    main_script = HERE / "main.py"

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
