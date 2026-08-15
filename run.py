"""Bootstrap a project virtual environment before importing the GUI app."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
REQUIRED_MODULES = ("PySide6", "docx", "pymupdf")


def missing_dependencies() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def running_in_project_venv() -> bool:
    """Return whether the active interpreter belongs to this project's venv."""
    return Path(sys.prefix).resolve() == VENV_DIR.resolve()


def python_is_usable(python_path: Path) -> bool:
    """Return whether an interpreter launcher can actually start Python."""
    if not python_path.is_file():
        return False
    try:
        completed = subprocess.run(
            [str(python_path), "-c", "import sys; raise SystemExit(0)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def relaunch_in_project_venv() -> int | None:
    """Create the project venv when needed and relaunch this script inside it."""
    if running_in_project_venv():
        return None

    try:
        if not python_is_usable(VENV_PYTHON):
            rebuilding = VENV_DIR.exists()
            action = "Repairing" if rebuilding else "Creating"
            print(f"{action} virtual environment at {VENV_DIR}...")
            command = [sys.executable, "-m", "venv"]
            if rebuilding:
                command.append("--clear")
            command.append(str(VENV_DIR))
            subprocess.run(command, check=True)

        if not python_is_usable(VENV_PYTHON):
            raise OSError(f"A usable virtual environment Python was not created: {VENV_PYTHON}")

        print("Restarting with the project virtual environment...")
        completed = subprocess.run(
            [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
            check=False,
        )
        return completed.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            "\nUnable to prepare the project virtual environment.\n\n"
            "Please check:\n- Python venv availability\n- Project folder permissions\n\n"
            f"Details:\n{exc}"
        )
        return 1


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
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
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
    relaunched = relaunch_in_project_venv()
    if relaunched is not None:
        return relaunched

    if not ensure_dependencies():
        return 1
    print("Starting Guide Comparison...")
    from guide_comparison.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
