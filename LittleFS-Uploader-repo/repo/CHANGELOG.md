# Changelog

## v1.0.0 — 2026-03-19

### Initial Release

- GUI tool for building and flashing LittleFS images to ESP32 boards
- Support for all ESP32 variants (ESP32, S2, S3, C3, C6, H2)
- Auto-detect COM ports via pyserial
- Bundled tool support (esptool.exe + mklittlefs.exe via PyInstaller)
- Fallback chain: bundled → user browse → system PATH → Python module
- Image verification step — confirms all files packed before flashing
- Real-time progress bar with esptool percentage parsing
- Flash protection: window close warning, bold status, title bar update
- Elapsed timer with completion time
- Partition presets for common 4MB / 8MB / 16MB layouts
- Persistent settings saved to ~/.littlefs_uploader.json
- Standalone .exe build via PyInstaller or auto-py-to-exe
