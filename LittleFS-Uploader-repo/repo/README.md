# LittleFS Uploader

A standalone GUI tool to build and flash [LittleFS](https://github.com/littlefs-project/littlefs) filesystem images to ESP32 boards.

One `.exe`, zero dependencies for end users.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows)
![License](https://img.shields.io/badge/License-MIT-green)
![ESP32](https://img.shields.io/badge/ESP32-S2%20%7C%20S3%20%7C%20C3%20%7C%20C6%20%7C%20H2-red?logo=espressif)

---

## Features

- **No Arduino IDE required** — upload LittleFS data without opening the IDE
- **Auto-detect COM ports** — scans and lists all available serial ports
- **All ESP32 variants** — ESP32, S2, S3, C3, C6, H2
- **Partition presets** — built-in presets for common 4MB / 8MB / 16MB flash layouts
- **Image verification** — checks that all files made it into the image before flashing
- **Real-time progress** — progress bar with percentage, elapsed timer, live esptool output
- **Flash protection** — warns on window close during flash, bold "DO NOT CLOSE" status
- **Persistent settings** — remembers COM port, chip, data folder, offsets between sessions
- **Bundled tools** — ships `esptool.exe` and `mklittlefs.exe` inside the exe (no setup)
- **Fallback chain** — bundled tools → user browse → system PATH → Python esptool module

## Quick Start

### Option A: Download the Release (recommended)

1. Download `LittleFS_Uploader.exe` from the [Releases](../../releases) page
2. Run it — no Python or dependencies needed
3. Select your COM port, chip, data folder, and partition settings
4. Click **Upload**

### Option B: Run from Source

```bash
git clone https://github.com/YOUR_USERNAME/LittleFS-Uploader.git
cd LittleFS-Uploader
pip install pyserial
python littlefs_uploader.py
```

> **Note:** When running from source, place `esptool.exe`, `mklittlefs.exe`, and `libwinpthread-1.dll` in the `tools/` subfolder — or install esptool via pip as a fallback: `pip install esptool`

## Building the Standalone .exe

### Prerequisites

```bash
pip install pyinstaller pyserial
```

### Setup

Place the required tool binaries in the `tools/` folder:

```
LittleFS-Uploader/
├── littlefs_uploader.py
├── build.bat
└── tools/
    ├── esptool.exe            ← required
    ├── mklittlefs.exe         ← required
    └── libwinpthread-1.dll    ← required by esptool.exe
```

### Where to Find the Tools

If you have Arduino IDE with the ESP32 board package installed, they're already on your machine:

```
%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\<version>\esptool.exe
%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\<version>\libwinpthread-1.dll
%LOCALAPPDATA%\Arduino15\packages\esp32\tools\mklittlefs\<version>\mklittlefs.exe
```

Or download them directly:
- **mklittlefs** — [github.com/earlephilhower/mklittlefs/releases](https://github.com/earlephilhower/mklittlefs/releases)
- **esptool** — [github.com/espressif/esptool/releases](https://github.com/espressif/esptool/releases)

### Build

**Using the build script:**
```bash
build.bat
```

**Using [auto-py-to-exe](https://github.com/brentvollebregt/auto-py-to-exe) (GUI):**
1. Script Location → `littlefs_uploader.py`
2. One File → **One File**
3. Console Window → **Window Based (hide the console)**
4. Additional Files → **Add Folder** → select `tools/` → destination: `tools`
5. Click **Convert**

**Manual PyInstaller command:**
```bash
pyinstaller --onefile --windowed --add-data "tools;tools" --name "LittleFS_Uploader" littlefs_uploader.py
```

Output: `dist/LittleFS_Uploader.exe` — fully standalone.

## Usage Guide

### 1. Partition Offset & Size

These **must** match your project's partition table. Open your `partitions.csv` and find the `spiffs` or `littlefs` entry:

```csv
# Name,    Type, SubType, Offset,     Size
nvs,       data, nvs,     0x9000,     0x5000
otadata,   data, ota,     0xe000,     0x2000
app0,      app,  ota_0,   0x10000,    0x300000
spiffs,    data, spiffs,  0x310000,   0x9F0000    ← this line
```

→ **Offset** = `0x310000`, **Size** = `0x9F0000`

The tool includes presets for common layouts:

| Preset | Offset | Size | Notes |
|--------|--------|------|-------|
| 16MB — Large LittleFS | `0x310000` | `0x9F0000` | ~10MB filesystem |
| 16MB — Half LittleFS | `0x310000` | `0x4F0000` | ~5MB filesystem |
| 8MB — Typical | `0x310000` | `0x4F0000` | ~5MB filesystem |
| 4MB — Small | `0x290000` | `0x170000` | ~1.5MB filesystem |

### 2. Data Folder

Point the tool to any folder containing the files you want on the LittleFS partition. All files in the folder will be packed into the image.

### 3. Upload Process

The upload runs in three steps:

1. **Build** — `mklittlefs` packs your data folder into a `.bin` image
2. **Verify** — the tool lists the image contents and confirms all files were included
3. **Flash** — `esptool` writes the image to the ESP32 at the specified offset

During the flash step:
- The progress bar shows real-time write percentage
- The window title changes to **⚠ FLASHING IN PROGRESS**
- A warning dialog blocks accidental window close
- The log displays a **DO NOT CLOSE** banner

## Tool Resolution Priority

For both `esptool` and `mklittlefs`, the tool checks in this order:

1. **User browse path** — whatever you select via the Browse button
2. **Bundled `tools/`** — the `tools/` subfolder (works in dev and PyInstaller builds)
3. **System PATH** — if the tool is on your system PATH
4. **Python module** (esptool only) — `import esptool` as a last resort

## Settings Persistence

All settings are saved to `~/.littlefs_uploader.json` and restored on next launch:
- COM port, chip model, baud rate
- Data folder path
- Partition offset and size
- Tool paths (mklittlefs, esptool)

## Troubleshooting

### "mklittlefs not found"
Place `mklittlefs.exe` in the `tools/` folder next to the script/exe, or use Browse to locate it.

### "esptool not available"
Place `esptool.exe` + `libwinpthread-1.dll` in `tools/`, or install via pip: `pip install esptool`

### Files missing from image / "DID NOT FIT"
Your files exceed the partition size. Either increase the LittleFS partition in your `partitions.csv` (and re-flash your sketch), or remove files from the data folder.

### esptool can't connect
- Close Arduino IDE and any Serial Monitor
- Check that the correct COM port is selected (click ↻ to refresh)
- Try a lower baud rate (230400 or 115200)
- Make sure the USB cable supports data (not charge-only)

### "Access denied" on COM port
Another program has the port open. Close Arduino IDE, PuTTY, or any other serial tool.

## Project Structure

```
LittleFS-Uploader/
├── littlefs_uploader.py      # Main application
├── build.bat                 # PyInstaller build script
├── requirements.txt          # Python dependencies
├── LICENSE                   # MIT License
├── README.md                 # This file
├── .gitignore
└── tools/                    # Place tool binaries here (not in repo)
    ├── esptool.exe
    ├── mklittlefs.exe
    └── libwinpthread-1.dll
```

## Requirements

**For running from source:**
- Python 3.10+
- `pyserial` (for COM port detection)
- `esptool` (optional — only needed if not using bundled exe)

**For building standalone exe:**
- Everything above plus `pyinstaller`

**For end users:**
- Nothing. The `.exe` is fully standalone.

## License

[MIT](LICENSE)

## Credits

- [esptool](https://github.com/espressif/esptool) by Espressif Systems
- [mklittlefs](https://github.com/earlephilhower/mklittlefs) by Earle F. Philhower III
- [LittleFS](https://github.com/littlefs-project/littlefs) by ARM / Geky
