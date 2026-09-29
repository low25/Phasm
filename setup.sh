#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

VENV_DIR="${PHASM_VENV_DIR:-$SCRIPT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_DEPS=1
DOWNLOAD_EMULATORS=0
RUN_CHECK=1
BUILD_APPIMAGE=1
INTERACTIVE=1

if [[ ! -t 0 || ! -t 1 ]]; then
    INTERACTIVE=0
fi

if [[ -t 1 ]]; then
    RESET=$'\033[0m'
    CYAN=$'\033[36m'
    PURPLE=$'\033[35m'
    GREEN=$'\033[32m'
    YELLOW=$'\033[33m'
    RED=$'\033[31m'
    DIM=$'\033[2m'
else
    RESET=''; CYAN=''; PURPLE=''; GREEN=''; YELLOW=''; RED=''; DIM=''
fi

usage() {
    cat <<'EOF'
Phasm setup wizard

Usage:
  ./setup.sh [options]

Options:
  --help                 Show this help text.
  --non-interactive      Use defaults and never ask questions.
  --no-deps              Skip virtualenv creation and Python dependencies.
  --no-check             Skip the initialization check.
  --no-appimage          Prepare the checkout but skip the final AppImage build.
  --download-emulators   Ask for trusted emulator URLs and download them.

Environment variables:
  PYTHON_BIN             Python executable (default: python3).
  PHASM_VENV_DIR         Virtualenv path (default: .venv).
  PHASM_PS2_URL          Trusted PCSX2 AppImage URL.
  PHASM_PS3_URL          Trusted RPCS3 AppImage URL.
  PHASM_PS4_URL          Trusted ShadPS4 AppImage URL.
  APPIMAGETOOL           Path to appimagetool, if it is not on PATH.
  APPIMAGETOOL_URL       Override the official appimagetool download URL.
  APPIMAGE_RUNTIME       Optional AppImage runtime file.
  APPIMAGE_RUNTIME_URL   Override the AppImage runtime download URL.

The wizard never downloads games, BIOS files, firmware, keys, or emulator
files unless emulator downloads are explicitly selected.
EOF
}

logo() {
    printf '%s\n' "${PURPLE}"
    cat <<'EOF'
      ██████╗ ██╗  ██╗ █████╗ ███████╗███╗   ███╗
      ██╔══██╗██║  ██║██╔══██╗██╔════╝████╗ ████║
      ██████╔╝███████║███████║███████╗██╔████╔██║
      ██╔═══╝ ██╔══██║██╔══██║╚════██║██║╚██╔╝██║
      ██║     ██║  ██║██║  ██║███████║██║ ╚═╝ ██║
      ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝
EOF
    printf '%s\n' "${RESET}"
    printf '%s\n' "${CYAN}                 SETUP WIZARD${RESET}"
    printf '%s\n\n' "${DIM}        Prepare • Configure • Package • Play${RESET}"
}

step() {
    printf '\n%s[%s]%s %s\n' "$CYAN" "$1" "$RESET" "$2"
}

info() { printf '%s  •%s %s\n' "$DIM" "$RESET" "$*"; }
success() { printf '%s  ✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s  !%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die() { printf '%s  ✗%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

ask_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
    local answer
    if (( ! INTERACTIVE )); then
        [[ "$default" == "y" ]]
        return
    fi
    if [[ "$default" == "y" ]]; then
        read -r -p "  $prompt [Y/n] " answer
        answer="${answer:-y}"
    else
        read -r -p "  $prompt [y/N] " answer
        answer="${answer:-n}"
    fi
    [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

pause_for_user() {
    if (( INTERACTIVE )); then
        read -r -p "  Press Enter to continue... " _
    fi
}

create_config_from_example() {
    local filename="$1"
    if [[ ! -f "$SCRIPT_DIR/config/$filename" && -f "$SCRIPT_DIR/config/$filename.example" ]]; then
        cp "$SCRIPT_DIR/config/$filename.example" "$SCRIPT_DIR/config/$filename"
        success "Created local config/$filename"
    fi
}

download_emulator() {
    local platform="$1"
    local filename="$2"
    local url="${3:-}"
    local destination="$SCRIPT_DIR/emulators/$filename"

    if [[ -z "$url" && $INTERACTIVE -eq 1 ]]; then
        read -r -p "  $platform official download URL (leave blank to skip): " url
    fi
    if [[ -z "$url" ]]; then
        warn "$platform skipped; configure its emulator later in Phasm Settings"
        return 0
    fi
    command -v curl >/dev/null 2>&1 || die "curl is required for emulator downloads"
    if [[ -f "$destination" ]]; then
        success "$platform already exists locally"
        return 0
    fi
    info "Downloading $platform"
    curl --fail --location --retry 3 --output "$destination.part" "$url"
    mv "$destination.part" "$destination"
    chmod +x "$destination"
    success "Installed $filename"
}

build_appimage() {
    step "6/6" "Building the Phasm AppImage"
    if ! command -v rsvg-convert >/dev/null 2>&1; then
        die "rsvg-convert is required. Install librsvg, then rerun ./setup.sh --no-deps"
    fi
    ensure_appimage_tools
    bash "$SCRIPT_DIR/packaging/build-appimage.sh"
    [[ -x "$SCRIPT_DIR/Phasm-x86_64.AppImage" ]] || die "AppImage build did not produce Phasm-x86_64.AppImage"
    success "Created $SCRIPT_DIR/Phasm-x86_64.AppImage"
}

download_tool() {
    local label="$1"
    local url="$2"
    local destination="$3"
    command -v curl >/dev/null 2>&1 || die "curl is required to download $label"
    mkdir -p "$(dirname "$destination")"
    info "Downloading $label"
    curl --fail --location --retry 3 --output "$destination.part" "$url"
    mv "$destination.part" "$destination"
    chmod +x "$destination"
    success "Installed $label"
}

ensure_appimage_tools() {
    [[ "$(uname -m)" == "x86_64" ]] || die "The bundled AppImage setup currently supports x86_64 only"

    if [[ -n "${APPIMAGETOOL:-}" && -x "$APPIMAGETOOL" ]]; then
        success "Using appimagetool from APPIMAGETOOL"
    elif command -v appimagetool >/dev/null 2>&1; then
        export APPIMAGETOOL="$(command -v appimagetool)"
        success "Using system appimagetool"
    elif [[ -x "$SCRIPT_DIR/.tools/appimagetool-x86_64.AppImage" ]]; then
        export APPIMAGETOOL="$SCRIPT_DIR/.tools/appimagetool-x86_64.AppImage"
        success "Using cached appimagetool"
    else
        download_tool "official appimagetool" \
            "${APPIMAGETOOL_URL:-https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage}" \
            "$SCRIPT_DIR/.tools/appimagetool-x86_64.AppImage"
        export APPIMAGETOOL="$SCRIPT_DIR/.tools/appimagetool-x86_64.AppImage"
    fi

    if [[ -n "${APPIMAGE_RUNTIME:-}" && -f "$APPIMAGE_RUNTIME" ]]; then
        success "Using AppImage runtime from APPIMAGE_RUNTIME"
    elif [[ -f "$SCRIPT_DIR/.tools/runtime-x86_64" ]]; then
        export APPIMAGE_RUNTIME="$SCRIPT_DIR/.tools/runtime-x86_64"
        success "Using cached AppImage runtime"
    else
        download_tool "official AppImage runtime" \
            "${APPIMAGE_RUNTIME_URL:-https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64}" \
            "$SCRIPT_DIR/.tools/runtime-x86_64"
        export APPIMAGE_RUNTIME="$SCRIPT_DIR/.tools/runtime-x86_64"
    fi
}

while (($#)); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --non-interactive) INTERACTIVE=0 ;;
        --no-deps) INSTALL_DEPS=0 ;;
        --no-check) RUN_CHECK=0 ;;
        --no-appimage) BUILD_APPIMAGE=0 ;;
        --download-emulators) DOWNLOAD_EMULATORS=1 ;;
        *) die "Unknown option: $1 (use --help for usage)" ;;
    esac
    shift
done

logo
step "1/6" "Checking your system"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python executable not found: $PYTHON_BIN"
PYTHON_VERSION="$($PYTHON_BIN -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PYTHON_MAJOR="${PYTHON_VERSION%%.*}"
PYTHON_MINOR="${PYTHON_VERSION##*.}"
if (( PYTHON_MAJOR < 3 || (PYTHON_MAJOR == 3 && PYTHON_MINOR < 10) )); then
    die "Python 3.10 or newer is required (found $PYTHON_VERSION)"
fi
success "Python $PYTHON_VERSION detected"
info "Linux desktop environment detected; AppImage output will be standalone"
pause_for_user

step "2/6" "Preparing Phasm folders and local configuration"
mkdir -p \
    "$SCRIPT_DIR/cache/metadata" \
    "$SCRIPT_DIR/cache/artwork/covers" \
    "$SCRIPT_DIR/cache/artwork/heroes" \
    "$SCRIPT_DIR/cache/artwork/logos" \
    "$SCRIPT_DIR/cache/artwork/icons" \
    "$SCRIPT_DIR/cache/artwork/screenshots" \
    "$SCRIPT_DIR/emulators" "$SCRIPT_DIR/config"
create_config_from_example "settings.json"
create_config_from_example "library.json"
create_config_from_example "userdata.json"
create_config_from_example "emulators.json"
success "Runtime folders are ready"
pause_for_user

step "3/6" "Installing the Python runtime"
if (( INSTALL_DEPS )); then
    if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        "$PYTHON_BIN" -m venv "$VENV_DIR"
        success "Created virtual environment at $VENV_DIR"
    else
        success "Using existing virtual environment at $VENV_DIR"
    fi
    VENV_PYTHON="$VENV_DIR/bin/python"
    info "Installing PySide6 and requests"
    "$VENV_PYTHON" -m pip install --upgrade pip
    "$VENV_PYTHON" -m pip install PySide6 requests
    info "Installing optional controller support"
    if "$VENV_PYTHON" -m pip install evdev; then
        success "Controller support installed"
    else
        warn "Controller support was skipped because evdev needs a local C compiler"
        info "Install gcc/base-devel later, then run: $VENV_PYTHON -m pip install evdev"
    fi
    success "Python dependencies installed"
else
    VENV_PYTHON="$PYTHON_BIN"
    warn "Python dependency installation skipped"
fi
pause_for_user

step "4/6" "Setting up optional emulators"
if (( DOWNLOAD_EMULATORS == 0 && INTERACTIVE == 1 )); then
    if ask_yes_no "Download emulator AppImages from URLs you provide?" n; then
        DOWNLOAD_EMULATORS=1
    fi
fi
if (( DOWNLOAD_EMULATORS )); then
    download_emulator "PS2" "pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage" "${PHASM_PS2_URL:-}"
    download_emulator "PS3" "rpcs3-v0.0.42-20067-dad97b9a_linux64.AppImage" "${PHASM_PS3_URL:-}"
    download_emulator "PS4" "Shadps4-qt.AppImage" "${PHASM_PS4_URL:-}"
    info "Switch is configured for the Ryujinx Flatpak and is installed separately"
else
    info "Emulator downloads skipped; configure installed emulators in Phasm Settings"
fi
pause_for_user

step "5/6" "Verifying the installation"
chmod +x "$SCRIPT_DIR/Phasm.sh"
if (( RUN_CHECK )); then
    "$VENV_PYTHON" "$SCRIPT_DIR/main.py" --check
    success "Phasm initialization check passed"
else
    warn "Initialization check skipped"
fi
pause_for_user

if (( BUILD_APPIMAGE )); then
    build_appimage
else
    step "6/6" "Skipping AppImage build"
    info "Run ./setup.sh again without --no-appimage when packaging is available"
fi

printf '\n%s╭──────────────────────────────────────────────╮%s\n' "$GREEN" "$RESET"
printf '%s│  Phasm is ready.                             │%s\n' "$GREEN" "$RESET"
printf '%s╰──────────────────────────────────────────────╯%s\n\n' "$GREEN" "$RESET"
printf 'Launch from source:  %s./Phasm.sh%s\n' "$CYAN" "$RESET"
if [[ -x "$SCRIPT_DIR/Phasm-x86_64.AppImage" ]]; then
    printf 'Launch AppImage:     %s./Phasm-x86_64.AppImage%s\n' "$CYAN" "$RESET"
fi
printf '\nNext inside Phasm:\n'
printf '  1. Add your game folders in Game Library.\n'
printf '  2. Configure emulator paths in Settings.\n'
printf '  3. Scan your library.\n'
printf '  4. Optionally connect Steam and metadata providers.\n\n'
