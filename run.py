"""Bootstrap dependencies before importing the GUI application."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REQUIRED_MODULES = ("PySide6", "docx", "pymupdf")


def missing_dependencies() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def ensure_dependencies() -> bool:
    print("Guide Comparison\n")
    print("Checking dependencies...")
    missing = missing_dependencies()
    if not missing:
        print("Dependencies ready.")
        return True
    print("Installing required packages...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(Path(__file__).with_name("requirements.txt"))],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            "\nUnable to install required dependencies.\n\n"
            "Please check:\n- Internet connection\n- Python installation\n- pip availability\n\n"
            f"Details:\n{exc}"
        )
        return False
    remaining = missing_dependencies()
    if remaining:
        print(f"Installation completed, but modules are still unavailable: {', '.join(remaining)}")
        return False
    print("Dependencies ready.")
    return True


def main() -> int:
    if not ensure_dependencies():
        return 1
    print("Starting Guide Comparison...")
    from guide_comparison.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
