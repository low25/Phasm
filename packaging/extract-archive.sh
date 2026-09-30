#!/usr/bin/env bash
set -Eeuo pipefail

archive="${1:-}"
if [[ -z "$archive" || ! -f "$archive" ]]; then
    exit 2
fi

directory="$(dirname -- "$archive")"
archive_name="$(basename -- "$archive")"
archive_name="${archive_name%.*}"
destination="$directory/$archive_name"
mkdir -p "$destination"
error_message="Install 7z, 7zz, unzip, or unrar to extract archives from Dolphin."

if command -v 7z >/dev/null 2>&1; then
    7z x "$archive" "-o$destination"
elif command -v 7zz >/dev/null 2>&1; then
    7zz x "$archive" "-o$destination"
elif [[ "${archive,,}" == *.zip ]] && command -v unzip >/dev/null 2>&1; then
    unzip -o "$archive" -d "$destination"
elif [[ "${archive,,}" == *.rar ]] && command -v unrar >/dev/null 2>&1; then
    unrar x -o+ "$archive" "$destination/"
else
    if command -v kdialog >/dev/null 2>&1; then
        kdialog --error "$error_message" --title "Phasm archive extraction"
    else
        printf '%s\n' "$error_message" >&2
    fi
    exit 1
fi
