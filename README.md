# Phasm

Phasm is a Linux game-library application for organizing and launching games from emulators and PC game launchers in one place.

It can scan PS1, PS2, PS3, PS4, and Switch game folders, import owned Steam games, display covers and metadata, track favorites and playtime, organize custom collections, and launch each game with the emulator configured for its platform.

![Phasm home screen](docs/screenshots/home.png)

> **Screenshot placeholder:** Add the real image at `docs/screenshots/home.png` before publishing.

## What this guide covers

This README is written as a complete first-time setup walkthrough. Follow the sections in order if you are installing Phasm for the first time.

1. [Before you begin](#1-before-you-begin)
2. [Install Phasm](#2-install-phasm)
3. [Run the installation check](#3-run-the-installation-check)
4. [Start Phasm](#4-start-phasm)
5. [Configure your game folders](#5-configure-your-game-folders)
6. [Configure your emulators](#6-configure-your-emulators)
7. [Scan your library](#7-scan-your-library)
8. [Understand the Home screen](#8-understand-the-home-screen)
9. [Launch your first game](#9-launch-your-first-game)
10. [Connect Steam](#10-connect-steam)
11. [Enable artwork and metadata](#11-enable-artwork-and-metadata)
12. [Organize your library](#12-organize-your-library)
13. [Configure appearance and audio](#13-configure-appearance-and-audio)
14. [Use a controller](#14-use-a-controller)
15. [Build or install the AppImage](#15-build-or-install-the-appimage)
16. [Troubleshoot common problems](#16-troubleshoot-common-problems)
17. [Back up or reset Phasm](#17-back-up-or-reset-phasm)
18. [For contributors and packagers](#18-for-contributors-and-packagers)

## 1. Before you begin

Phasm is designed for Linux. Before installing it, make sure you have:

- Python 3.10 or newer.
- A desktop session with Qt 6 support.
- A working emulator for every platform you want to use.
- Legal copies of the games, firmware, BIOS files, and keys required by those emulators.
- Read/write access to the folders containing your games.
- `xdg-open`, which is normally installed by Linux desktop environments.

Phasm does not include games, BIOS files, firmware, emulator keys, or copyrighted game assets. You must obtain and use those files legally.

### Platforms and file formats

| Platform | What Phasm detects | Default launcher in this project |
| --- | --- | --- |
| PS2 | `.iso`, `.chd`, `.cso`, `.mdf`/`.mds` | PCSX2 |
| PS3 | `.iso` or extracted folders containing `PS3_DISC.SFB` | RPCS3 |
| PS4 | `.pkg` or extracted folders containing `EBOOT.BIN` | ShadPS4 |
| Switch | `.nsp`, `.xci`, `.nsz` | Ryujinx Flatpak |
| PC | Imported launcher records, currently Steam-focused | Steam/PC launcher URI |

The scanner searches recursively, so your games can be inside subfolders.

## 2. Install Phasm

### Recommended: use the setup tool

The repository includes `setup.sh` so a fresh checkout can be prepared without storing emulator AppImages, Python environments, or generated artwork in Git. Run:

```bash
chmod +x setup.sh
./setup.sh
```

The setup wizard:

1. Checks for Python 3.10 or newer.
2. On Arch Linux, installs the common Qt/XCB/Wayland runtime libraries required by PySide6.
3. Creates `.venv`.
4. Installs `PySide6` and `requests`, then attempts optional `evdev` controller support.
5. Creates empty cache and emulator directories.
6. Creates local configuration from the safe `config/*.example` files when needed.
7. Optionally downloads emulator AppImages from URLs you explicitly provide.
8. Runs the initialization check.
9. Builds `Phasm-x86_64.AppImage` as the final step.

It does not download games, BIOS files, firmware, keys, or emulator binaries by default. This keeps the public repository small and avoids silently downloading software from an unverified source.

To download emulator AppImages, supply trusted URLs explicitly:

```bash
PHASM_PS2_URL="https://trusted.example/pcsx2.AppImage" \
PHASM_PS3_URL="https://trusted.example/rpcs3.AppImage" \
PHASM_PS4_URL="https://trusted.example/shadps4.AppImage" \
./setup.sh --download-emulators
```

The URL examples above are placeholders. Replace them with official release URLs you have verified. Switch uses the configured Ryujinx Flatpak command and is not downloaded by this script.

On Arch Linux, the wizard also offers the Qt runtime packages needed by the graphical AppImage, including `xcb-util-cursor`, `xcb-util-renderutil`, `libxkbcommon-x11`, `qt6-wayland`, `qt6-multimedia`, and `pyside6`. The `xcb-util-cursor` package provides `libxcb-cursor.so.0`, which is required by Qt’s XCB platform plugin. [Arch package file list](https://archlinux.org/packages/extra/x86_64/xcb-util-cursor/files/)

Run `./setup.sh --help` to see all options. Use `--no-deps` when Python dependencies are already installed, `--no-appimage` when you only want to prepare the checkout, and `--non-interactive` for automation. If `appimagetool` or the AppImage runtime is missing, the wizard downloads the official x86_64 tools into the ignored `.tools/` directory automatically.

On KDE, setup permanently installs a Dolphin context-menu action named **Extract here** for ZIP, 7z, and RAR archives. Archives are extracted into a same-name folder beside the archive. Setup also permanently configures Dolphin's built-in **Open Terminal Here** action to use Alacritty and refreshes KDE's service cache so its Alacritty icon appears. Extraction uses `7z`/`7zz` when available, with `unzip` and `unrar` as fallbacks.

### Option A: Run from the source folder

Clone or download the project, then open a terminal in the Phasm folder:

```bash
cd /path/to/Phasm
```

Create a private Python environment manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the Python packages manually if you are not using the wizard:

```bash
python -m pip install --upgrade pip
python -m pip install PySide6 requests
# Optional controller support; requires a C compiler on some systems.
python -m pip install evdev
```

Make the launcher executable:

```bash
chmod +x Phasm.sh
```

You can now continue to [run the installation check](#3-run-the-installation-check). The setup tool is recommended for new users because it performs these steps automatically.

### Option B: Use an AppImage

If a release AppImage is published, download it, make it executable, and run it:

```bash
chmod +x Phasm-x86_64.AppImage
./Phasm-x86_64.AppImage
```

An AppImage keeps its writable settings in your XDG user directories instead of modifying the read-only application bundle. See [AppImage data locations](#appimage-data-locations) for details.

![Installation screenshot](docs/screenshots/installation.png)

> **Screenshot placeholder:** Show the downloaded AppImage or the first launch here.

## 3. Run the installation check

Before opening the graphical interface, verify that Python and the basic configuration load correctly:

```bash
./Phasm.sh --check
```

A successful check looks like this:

```text
[INIT] Running check mode
[INIT] Config loaded successfully
```

If this command fails:

- Check that the virtual environment is active.
- Reinstall `PySide6` and `requests`. Install `evdev` separately if you want controller support.
- Confirm that you are using Python 3.10 or newer.
- Run the command from the Phasm project folder.

The check only verifies initialization. It does not verify emulator installation, game paths, controller permissions, or online API keys.

![Installation check](docs/screenshots/check-mode.png)

> **Screenshot placeholder:** Show a successful `./Phasm.sh --check` terminal result.

## 4. Start Phasm

From the project folder, run:

```bash
./Phasm.sh
```

If you need to select a specific interpreter:

```bash
PYTHON_BIN=/usr/bin/python3 ./Phasm.sh
```

Phasm normally starts fullscreen. The first screen may be empty until you configure at least one library folder and run a scan.

If the window does not appear, leave the terminal open and read the output printed by Phasm. It usually identifies whether the problem is a missing Python package, Qt platform plugin, graphics driver, or invalid configuration.

## 5. Configure your game folders

There are two ways to configure folders:

- Use the dedicated **Game Library** screen when you want multiple folders per platform.
- Use **Settings → Library** for quick editing of the current folder and emulator values.

### Add a folder

1. Open **Game Library** from the navigation bar.
2. Find the platform you want to configure.
3. Select **+ ADD FOLDER**.
4. Choose the folder containing that platform’s games.
5. Repeat the process if your games are stored in more than one location.
6. Select **REMOVE** only after selecting the folder entry you want to remove.

Recommended example:

```text
Games/
├── PS1Games/
├── PS2/
├── PS3/
├── PS4/
└── Switch/
```

You can also use folders on another drive, for example `/mnt/games/PS2/`.

PS1 games use one folder per game inside the configured PS1Games folder:

```text
PS1Games/
└── Game Name/
    ├── game.cue
    └── game.bin
```

PS1 `.chd` files can be stored directly in `PS1Games/` or inside a game
subfolder.

![Game Library screen](docs/screenshots/library-setup.png)

> **Screenshot placeholder:** Show the Game Library screen with folders added for at least two platforms.

### What happens during a scan

Phasm walks each configured folder and checks files according to the platform rules:

- PS2 image files become PS2 game entries. When both `.mdf` and `.mds` exist, Phasm uses the `.mds` file as the launch target.
- PS1 CUE/BIN files become PS1 entries when they are inside a game folder directly below the configured PS1Games folder. PS1 CHD files work directly in PS1Games or inside those subfolders. CUE is preferred when multiple formats are present.
- PS3 ISO files and extracted folders with `PS3_DISC.SFB` become PS3 entries.
- PS4 PKG files and extracted folders with `EBOOT.BIN` become PS4 entries.
- Switch NSP, XCI, and NSZ files become Switch entries.
- Unsupported extensions are ignored.
- Missing folders are skipped with a warning.
- Duplicate paths are combined into one entry.

## 6. Configure your emulators

Phasm scans and displays games, but the emulator itself must already be installed and working.

### Configure through Settings

1. Open **Settings**.
2. Select the **Library** tab.
3. Find the emulator field for PS1, PS2, PS3, PS4, or Switch.
4. Enter the executable path or use the folder/file browse button.
5. Confirm that the selected file is executable.
6. Close Settings or allow the automatic save to complete.

Settings also includes **Badge Icons** fields where you can enter or browse to a custom image for each platform badge. Leave a field empty to use Phasm's built-in logo.

![Emulator settings](docs/screenshots/emulator-settings.png)

> **Screenshot placeholder:** Show the emulator fields and browse buttons.

### Default emulator commands

The bundled configuration uses these defaults:

| Platform | Default command |
| --- | --- |
| PS1 | Configure your PS1 emulator path in Settings |
| PS2 | `emulators/pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage` |
| PS3 | `emulators/rpcs3-v0.0.42-20067-dad97b9a_linux64.AppImage` |
| PS4 | `emulators/Shadps4-qt.AppImage` |
| Switch | `flatpak run io.github.ryubing.Ryujinx` |

If you use different emulator builds, replace these values with your own paths or commands.

The emulator files are intentionally not required to be committed to the repository. Install them separately, use system-installed emulators, or provide trusted download URLs to `setup.sh`.

### Test an emulator before testing Phasm

Before troubleshooting Phasm, launch the emulator directly with a known game. If it cannot launch the game outside Phasm, fix the emulator configuration, firmware, keys, permissions, or game dump first.

## 7. Scan your library

After adding folders and configuring emulators:

1. Return to the Home screen.
2. Select the scan action from the navigation bar.
3. Wait for the scan and metadata refresh to complete.
4. Open each platform tab to confirm that the expected games appear.

Phasm also watches configured directories for changes and can refresh when files or folders change. A manual rescan is still recommended after changing several library paths at once.

If a game is missing, check the file extension and folder layout against [the supported formats](#platforms-and-file-formats).

## 8. Understand the Home screen

The Home screen is the main place to use Phasm:

- **Collections:** Home is the only automatic top-level menu. All other top-level menus are user-created collections and can be reordered.
- **Game cards:** Show the game title, platform, artwork, and installed state where applicable.
- **Hero panel:** Shows details and artwork for the selected title.
- **Play action:** Starts the selected game.
- **Favorite action:** Adds or removes the title from Favorites.
- **Collections:** Opens custom groups created by you; these are the only menus besides Home.
- **Recently played:** Shows games launched most recently.
- **Search:** Finds games by title and filters by platform.
- **Settings:** Changes library, emulator, appearance, audio, and metadata options.

![Home screen](docs/screenshots/home.png)

> **Screenshot placeholder:** Show the Home screen with a selected game and visible manual collection tabs.

## 9. Launch your first game

Choose a small, known-working game for your first test:

1. Select the correct platform tab.
2. Select a game card.
3. Confirm that the displayed path is correct.
4. Select **Play**.
5. Wait for the configured emulator or launcher to open.
6. Close the game normally.
7. Return to Phasm and check **Recently Played** and the game’s playtime.

For emulator games, Phasm replaces `{game}` in the configured argument list with the scanned path. For PC/Steam games, it opens the saved launcher URI with `xdg-open`.

Phasm monitors the launched process. When the emulator closes, or when it reports a known game-stop message, Phasm ends the session and saves its duration.

## 10. Connect Steam

Steam integration imports your owned games as PC entries. It does not install games or replace the Steam client.

### What you need

- A Steam account.
- Steam game details set to public, so the owned-games API can return your library.
- A Steam Web API key.
- A browser available on the same machine.

### Connect your account

1. Open **Accounts** in Phasm.
2. Select **LOGIN WITH STEAM**.
3. Complete the login in your browser.
4. Return to Phasm after the browser reports that login is complete.
5. Enter your Steam Web API key when prompted.
6. Wait for the imported game count and library refresh.

Phasm uses Steam OpenID in the browser and a temporary localhost callback. It does not receive or store your Steam password. The Steam ID, API key, and connection state are stored locally in user data.

Only installed Steam games are displayed as launchable. Phasm checks Steam library manifests and hides runtimes, Proton packages, redistributables, SDKs, and other Steam helper tools.

![Steam Accounts screen](docs/screenshots/steam-account.png)

> **Screenshot placeholder:** Show the Accounts screen with Steam disconnected or connected. Do not show a real Steam ID or API key.

### Disconnect Steam

Open **Accounts** and select **DISCONNECT**. This removes imported Steam records from Phasm’s local library data. It does not uninstall games or change your Steam account.

## 11. Enable artwork and metadata

Artwork and descriptions are optional. Games can be scanned and launched without online services.

### SteamGridDB artwork

SteamGridDB can provide covers, hero artwork, logos, and alternative artwork choices from the game detail screen.

To enable it:

1. Open **Settings → Appearance**.
2. Enter your SteamGridDB API key.
3. Enable SteamGridDB.
4. Rescan or reopen the library.

### RAWG metadata

RAWG can provide descriptions, release year, developer, hero images, and screenshots.

To enable it:

1. Open **Settings → Appearance**.
2. Enter your RAWG API key.
3. Enable RAWG metadata.
4. Rescan or reopen the library.

Downloaded files are cached locally and reused on later launches. If a provider is offline, rate-limited, or cannot find a matching title, the game remains usable without metadata.

![Artwork editor](docs/screenshots/artwork-editor.png)

> **Screenshot placeholder:** Show artwork choices without exposing API keys.

### Important public-release warning

Never commit API keys to a public GitHub repository. Do not include them in screenshots, bug reports, example JSON, or logs. If a key has already been committed or published, revoke it and create a replacement before making the repository public.

## 12. Organize your library

### Favorites

Select the favorite action on a game card or detail view. Favorites are stored locally and remain available after restarting Phasm.

### Collections

Use collections to group games such as “Currently Playing”, “Co-op”, or “Backlog”. You can:

1. Create a collection from Home.
2. Give it a unique name.
3. Add games from the game action menu.
4. Rename or delete the collection later.
5. Choose grid or list view for the collection.
6. Reorder collection tabs where supported.

Moving a game to one collection removes it from other collections. Deleting a collection does not delete the games inside it.

### Search

1. Open **Search**.
2. Enter a title.
3. Select **ALL**, **PC**, **PS1**, **PS2**, **PS3**, **PS4**, or **SWITCH**.
4. Select a result to open its actions.

![Search screen](docs/screenshots/search.png)

> **Screenshot placeholder:** Show a search result and platform filter buttons.

### Playtime

Phasm records the duration of each monitored launch session. It keeps the total seconds and number of sessions for each game. To clear all playtime, open **Settings → General → Playtime** and select the clear action.

## 13. Configure appearance and audio

Open **Settings** and use the relevant tab:

### Appearance

- Choose an accent color.
- Enable or disable fullscreen mode.
- Enable or disable the custom accent cursor.
- Choose a vertical side-panel or horizontal hero layout.
- Enable SteamGridDB and RAWG.

### Audio

- Enable or disable sound effects.
- Set sound-effect volume.
- Enable or disable music/ambience.
- Set music volume.

### General

- Enable or disable minimize-on-launch.
- Clear playtime records.

![Settings screen](docs/screenshots/settings.png)

> **Screenshot placeholder:** Show the Settings tabs. Hide provider keys in the screenshot.

## 14. Use a controller

Phasm supports Linux gamepads through `python-evdev` and the Linux joystick interface. Keyboard input remains available if controller support is not installed or the device is unavailable.

| Controller input | Phasm action |
| --- | --- |
| D-pad / left stick | Navigate |
| A | Confirm, open, or launch |
| B | Back/cancel |
| Y | Toggle favorite |
| X | Open context menu |
| Start/Menu | Open quit confirmation |
| LB / RB | Previous/next tab or platform |
| View/Back | Toggle fullscreen |

If a controller does not work, install `evdev`, reconnect the device, and verify that your user can read the relevant `/dev/input/event*` device. Do not change device permissions broadly without understanding the security impact.

![Controller navigation](docs/screenshots/controller-navigation.png)

> **Screenshot placeholder:** Show a controller-friendly library screen or an annotated controller mapping.

## 15. Build or install the AppImage

This section is for maintainers or users building Phasm locally. If you downloaded a release AppImage, skip to [Start Phasm](#4-start-phasm).

Install `rsvg-convert`, then build from the project folder:

```bash
./Phasm.sh --buildapp
```

The output is:

```text
Phasm-x86_64.AppImage
```

The setup wizard automatically downloads the official x86_64 `appimagetool` and AppImage runtime into `.tools/` when they are missing. If you prefer to provide your own trusted copies, specify them:

```bash
APPIMAGETOOL=/path/to/appimagetool-x86_64.AppImage ./Phasm.sh --buildapp
```

You can also override the download sources for the setup wizard with `APPIMAGETOOL_URL` and `APPIMAGE_RUNTIME_URL`.

The build always creates the AppImage. If Gear Lever is installed, the build asks whether it should move Phasm into Gear Lever and add it to the desktop app menu. If Gear Lever is unavailable, the build finishes after creating the standalone AppImage.

![AppImage build](docs/screenshots/appimage-integration.png)

> **Screenshot placeholder:** Show the generated AppImage and the final setup wizard output.

### AppImage data locations

When running from an AppImage, Phasm stores writable files here:

```text
${XDG_CONFIG_HOME:-~/.config}/Phasm/
${XDG_DATA_HOME:-~/.local/share}/Phasm/
```

Configuration files go in the config directory. Artwork and metadata cache files go in the data directory. Replacing the AppImage does not overwrite these files.

## 16. Troubleshoot common problems

### Phasm says a Python module is missing

Activate the virtual environment and install the dependencies again:

```bash
source .venv/bin/activate
python -m pip install PySide6 requests evdev
```

Then run `./Phasm.sh --check`.

### The window does not open

Run Phasm from a terminal and look for the first error. If `--check` succeeds, the problem may be Qt or the graphics session. Phasm requests Wayland first and supports X11 through Qt’s fallback behavior.

### A game does not appear

Check that the folder is listed under the correct platform, exists, is readable, uses a supported file extension or extracted-folder marker, and was rescanned. Steam runtimes and helper packages are intentionally hidden.

### A game appears but will not launch

Test the emulator directly with the same game, check the emulator path, confirm the executable permission, and confirm `{game}` is present in the configured arguments. For Switch, test the configured Ryujinx Flatpak command. For Steam, verify that the Steam URI handler works.

### Steam imports zero games

Make game details public, verify the Steam Web API key, and reconnect the account. Browser login identifies the account; the Web API key retrieves the owned-games list.

### Artwork is missing

Artwork is optional. Verify that the provider is enabled, the key is valid, and the machine can access the provider. Previously downloaded files are stored in `cache/artwork/` or the AppImage data directory.

### The controller is not detected

Install `python-evdev`, reconnect the controller, and check Linux input-device permissions. Test keyboard navigation to confirm that the application itself is working.

### The AppImage build fails

Confirm that `appimagetool` and `rsvg-convert` are installed and executable. The build script also supports an explicit `APPIMAGETOOL=/path/to/appimagetool` value.

## 17. Back up or reset Phasm

Close Phasm before manually changing configuration. For a source checkout, back up:

```bash
cp -a config config.backup
cp -a cache cache.backup
```

Important files:

```text
config/settings.json       Appearance, audio, and provider settings
config/library.json        Folders and imported launcher records
config/emulators.json      Emulator commands and arguments
config/userdata.json       Favorites, history, collections, accounts, playtime
cache/metadata/            Downloaded metadata
cache/artwork/             Downloaded images
```

For an AppImage, back up both `${XDG_CONFIG_HOME:-~/.config}/Phasm/` and `${XDG_DATA_HOME:-~/.local/share}/Phasm/`.

To reset Phasm safely, close the application and move these directories to a backup location. Start Phasm again and restore files only after confirming the clean setup works. Moving files preserves the possibility of recovery.

## 18. For contributors and packagers

```text
main.py                 Startup and Qt initialization
Phasm.sh                Source launcher
core/
├── config.py           JSON files and source/AppImage data paths
├── scanner.py          Platform-aware game discovery
├── library.py          Installed-state and Steam filtering
├── launcher.py         Emulator and PC URI launching
├── session.py          Process monitoring and playtime duration
├── metadata.py         Metadata enrichment and local cache persistence
├── assets.py           SteamGridDB and artwork downloads
├── accounts.py         Steam authentication and library import
└── userdata.py         Favorites, history, collections, and playtime
ui/
├── main_window.py      Main window and view switching
├── home_view.py        Home, cards, collections, and artwork actions
├── search_view.py      Search and platform filtering
├── library_view.py     Library folder management
├── account_view.py     Steam account UI
├── settings_view.py    Settings UI and persistence
└── controller.py       Gamepad-to-Qt input translation
packaging/              AppImage and desktop-entry files
assets/                 Icons, sounds, platform art, and branding
```

Basic checks before submitting a change:

```bash
./Phasm.sh --check
python3 -m compileall core ui main.py
```

Before making the repository public, add a license, contribution guidelines, issue templates, release instructions, and AppImage downloads. Keep `config/*.example` files in Git, but do not commit personal `config/settings.json`, `config/library.json`, `config/userdata.json`, or `config/emulators.json` files. Remove or rotate any API keys from configuration files first.

## Screenshot checklist

Add these files under `docs/screenshots/` when preparing the public repository:

| File | Capture |
| --- | --- |
| `home.png` | Main Home screen with a selected game. |
| `installation.png` | First launch or downloaded AppImage. |
| `check-mode.png` | Successful terminal initialization check. |
| `library-setup.png` | Game Library screen with folders configured. |
| `emulator-settings.png` | Emulator settings fields. |
| `steam-account.png` | Accounts screen without private data. |
| `artwork-editor.png` | Artwork selection dialog without API keys. |
| `search.png` | Search results and platform filters. |
| `settings.png` | Settings tabs. |
| `controller-navigation.png` | Controller-friendly navigation. |
| `appimage-integration.png` | AppImage or desktop integration. |

Before uploading screenshots, hide API keys, Steam IDs, usernames, home-directory paths, private game names, and other personal information.
