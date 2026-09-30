#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
APPDIR="$PROJECT_DIR/.appimage-build/Phasm.AppDir"
OUTPUT="$PROJECT_DIR/Phasm-x86_64.AppImage"
VERSION_FILE="$PROJECT_DIR/VERSION"
if [[ -z "${APP_VERSION:-}" && -f "$VERSION_FILE" ]]; then
    APP_VERSION="$(<"$VERSION_FILE")"
fi
APP_VERSION="${APP_VERSION:-1.2.0}"
APPIMAGE_ARCH="${ARCH:-x86_64}"
if [[ -n "${APPIMAGETOOL:-}" ]]; then
    : # Respect an explicitly selected builder.
elif command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL="$(command -v appimagetool)"
elif [[ -x "$PROJECT_DIR/.tools/appimagetool-x86_64.AppImage" ]]; then
    APPIMAGETOOL="$PROJECT_DIR/.tools/appimagetool-x86_64.AppImage"
else
    # Keep the historical /tmp location as a final compatibility fallback.
    APPIMAGETOOL="/tmp/appimagetool-x86_64.AppImage"
fi
RUNTIME_FILE="${APPIMAGE_RUNTIME:-$PROJECT_DIR/packaging/runtime-x86_64}"
APPIMAGETOOL_ARGS=()

if [[ ! -f "$RUNTIME_FILE" && -f /tmp/runtime-x86_64 ]]; then
    RUNTIME_FILE=/tmp/runtime-x86_64
fi
if [[ -f "$RUNTIME_FILE" ]]; then
    APPIMAGETOOL_ARGS+=(--runtime-file "$RUNTIME_FILE")
fi

if [[ "$APPIMAGETOOL" == *.AppImage && ! -x "$APPIMAGETOOL" ]]; then
    printf 'AppImage builder not found. Install appimagetool or set APPIMAGETOOL.\n' >&2
    printf 'Example: APPIMAGETOOL=/path/to/appimagetool-x86_64.AppImage python main.py --buildapp\n' >&2
    exit 1
fi

# AppImage execution may not have FUSE available. Extract the downloaded
# builder automatically in that case, so `python main.py --buildapp` remains
# usable on minimal CI/dev environments.
if [[ "$APPIMAGETOOL" == *.AppImage ]]; then
    EXTRACTED_TOOL="/tmp/phasm-appimagetool"
    if [[ ! -x "$EXTRACTED_TOOL/root/AppRun" ]]; then
        rm -rf "$EXTRACTED_TOOL"
        mkdir -p "$EXTRACTED_TOOL"
        (cd "$EXTRACTED_TOOL" && "$APPIMAGETOOL" --appimage-extract >/dev/null)
        mv "$EXTRACTED_TOOL/squashfs-root" "$EXTRACTED_TOOL/root"
    fi
    APPIMAGETOOL="$EXTRACTED_TOOL/root/AppRun"
fi

if [[ ! -x "$APPIMAGETOOL" ]]; then
    printf 'AppImage builder is not executable: %s\n' "$APPIMAGETOOL" >&2
    printf 'Install appimagetool or set APPIMAGETOOL=/path/to/appimagetool.\n' >&2
    exit 1
fi

rm -rf "$PROJECT_DIR/.appimage-build"
mkdir -p "$APPDIR/usr/share/phasm" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -a "$PROJECT_DIR/core" "$PROJECT_DIR/ui" "$PROJECT_DIR/assets" \
    "$PROJECT_DIR/config" "$PROJECT_DIR/cache" "$PROJECT_DIR/emulators" \
    "$PROJECT_DIR/main.py" "$APPDIR/usr/share/phasm/"
cp "$PROJECT_DIR/VERSION" "$APPDIR/usr/share/phasm/VERSION"
find "$APPDIR" -type d -name __pycache__ -prune -exec rm -rf {} +
cp "$SCRIPT_DIR/AppRun" "$APPDIR/AppRun"
cp "$SCRIPT_DIR/Phasm.desktop" "$APPDIR/usr/share/applications/Phasm.desktop"
cp "$SCRIPT_DIR/Phasm.desktop" "$APPDIR/Phasm.desktop"
# Keep the source desktop entry reusable, while stamping the actual build
# version into both copies embedded in the AppImage. Gear Lever reads
# X-AppImage-Version from this desktop entry during integration.
sed -i "s/^X-AppImage-Version=.*/X-AppImage-Version=$APP_VERSION/" \
    "$APPDIR/usr/share/applications/Phasm.desktop" "$APPDIR/Phasm.desktop"
rsvg-convert -w 256 -h 256 "$PROJECT_DIR/assets/icon.svg" \
    -o "$APPDIR/usr/share/icons/hicolor/256x256/apps/Phasm.png"
cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/Phasm.png" "$APPDIR/Phasm.png"
chmod +x "$APPDIR/AppRun"

ARCH="$APPIMAGE_ARCH" "$APPIMAGETOOL" "${APPIMAGETOOL_ARGS[@]}" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"
printf 'Created %s\n' "$OUTPUT"

# Gear Lever can both move the AppImage to its managed location and create the
# desktop-menu entry.  Offer that optional step only when Gear Lever is
# actually available; a normal AppImage build must still finish cleanly on
# systems that do not use it.
GEARLEVER=()
if command -v gearlever >/dev/null 2>&1; then
    GEARLEVER=(gearlever)
elif command -v flatpak >/dev/null 2>&1 && flatpak info it.mijorus.gearlever >/dev/null 2>&1; then
    GEARLEVER=(flatpak run it.mijorus.gearlever)
fi

if ((${#GEARLEVER[@]} == 0)); then
    printf 'Gear Lever not detected; leaving the AppImage at %s\n' "$OUTPUT"
elif [[ -t 0 && -t 1 ]]; then
    # Gear Lever provides its own safety confirmation. Invoke it directly so
    # the user sees only Gear Lever's native "Do you really want to integrate
    # this AppImage?" prompt.
    if "${GEARLEVER[@]}" --integrate "$OUTPUT"; then
        printf 'Phasm integration requested through Gear Lever.\n'
    else
        printf 'Gear Lever could not integrate Phasm; the AppImage remains at %s\n' "$OUTPUT" >&2
    fi
else
    printf 'Gear Lever detected, but this build is non-interactive; leaving the AppImage at %s\n' "$OUTPUT"
fi
