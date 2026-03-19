# Tools Directory

Place the following binaries in this folder before building:

- `esptool.exe` — ESP32 flash tool
- `mklittlefs.exe` — LittleFS image builder
- `libwinpthread-1.dll` — required runtime dependency for esptool.exe

These are **not** included in this repository. See the main [README](../README.md#where-to-find-the-tools) for download instructions.

## Quick Copy (if you have Arduino IDE + ESP32 board package)

```batch
copy "%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\5.1.0\esptool.exe" .
copy "%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\5.1.0\libwinpthread-1.dll" .
copy "%LOCALAPPDATA%\Arduino15\packages\esp32\tools\mklittlefs\4.0.2-db0513a\mklittlefs.exe" .
```

> **Note:** Version numbers may differ — check your `Arduino15\packages\esp32\tools\` folder for exact paths.
