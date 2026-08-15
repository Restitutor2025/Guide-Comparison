#!/bin/zsh
set -eu

SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h}"
PYTHON_BIN="${GUIDE_COMPARISON_PYTHON:-${PROJECT_ROOT}/.venv/bin/python}"
LIBREOFFICE_APP="${GUIDE_COMPARISON_LIBREOFFICE_APP:-/Applications/LibreOffice.app}"
OUTPUT_DIR="${PROJECT_ROOT}/executables"
APP_PATH="${OUTPUT_DIR}/Guide Comparison.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
    print -u2 "Guide Comparison.app must be built on macOS."
    exit 1
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
    print -u2 "Python environment not found: ${PYTHON_BIN}"
    exit 1
fi
if [[ ! -x "${LIBREOFFICE_APP}/Contents/MacOS/soffice" ]]; then
    print -u2 "LibreOffice is required for the self-contained app: ${LIBREOFFICE_APP}"
    exit 1
fi

mkdir -p "${OUTPUT_DIR}"
PYINSTALLER_CONFIG_DIR="/tmp/guide-comparison-pyinstaller" \
    "${PYTHON_BIN}" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "${OUTPUT_DIR}" \
    --workpath "${PROJECT_ROOT}/build/macos" \
    "${PROJECT_ROOT}/packaging/GuideComparison-macos.spec"

mkdir -p "${APP_PATH}/Contents/Resources"
/usr/bin/ditto "${LIBREOFFICE_APP}" "${APP_PATH}/Contents/Resources/LibreOffice.app"
/usr/bin/xattr -cr "${APP_PATH}"
/usr/bin/codesign --force --deep --sign - --timestamp=none "${APP_PATH}"
/usr/bin/codesign --verify --deep --strict "${APP_PATH}"

print "Created: ${APP_PATH}"
