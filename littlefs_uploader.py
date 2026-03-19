#!/usr/bin/env python3
"""
LittleFS Uploader — GUI tool for uploading data/ folders to ESP32 LittleFS partitions.

Bundle layout (place in tools/ subfolder next to this script):
    tools/
        esptool.exe
        mklittlefs.exe
        libwinpthread-1.dll

Run directly:       python littlefs_uploader.py
Build standalone:   pyinstaller --onefile --add-data "tools;tools" --windowed littlefs_uploader.py
"""

import os
import sys
import json
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------
CONFIG_FILE = Path.home() / ".littlefs_uploader.json"

DEFAULT_CONFIG = {
    "com_port": "",
    "chip": "esp32s3",
    "data_dir": "",
    "mklittlefs_path": "",
    "esptool_path": "",
    "fs_offset": "0x310000",
    "fs_size": "0x9F0000",
    "baud": "460800",
}

CHIP_OPTIONS = [
    "esp32",
    "esp32s2",
    "esp32s3",
    "esp32c3",
    "esp32c6",
    "esp32h2",
]

BAUD_OPTIONS = ["115200", "230400", "460800", "921600"]

PARTITION_PRESETS = {
    "Custom": ("", ""),
    "16MB — Large LittleFS (0x310000 / 0x9F0000)": ("0x310000", "0x9F0000"),
    "16MB — Half LittleFS (0x310000 / 0x4F0000)": ("0x310000", "0x4F0000"),
    "8MB — Typical (0x310000 / 0x4F0000)": ("0x310000", "0x4F0000"),
    "4MB — Small (0x290000 / 0x170000)": ("0x290000", "0x170000"),
}


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            saved = json.load(f)
        return {**DEFAULT_CONFIG, **saved}
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# COM port detection
# ---------------------------------------------------------------------------
def list_com_ports() -> list[str]:
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        return [f"{p.device} — {p.description}" for p in sorted(ports, key=lambda x: x.device)]
    except ImportError:
        result = []
        for i in range(1, 33):
            name = f"COM{i}"
            try:
                import serial
                s = serial.Serial(name)
                s.close()
                result.append(name)
            except Exception:
                pass
        return result if result else ["(no ports found — install pyserial)"]


# ---------------------------------------------------------------------------
# Bundled tool resolution
# ---------------------------------------------------------------------------
def _get_tools_dir() -> str:
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "tools")


def find_tool(filename: str, user_override: str = "") -> str | None:
    if user_override and os.path.isfile(user_override):
        return user_override
    bundled = os.path.join(_get_tools_dir(), filename)
    if os.path.isfile(bundled):
        return bundled
    on_path = shutil.which(filename.replace(".exe", ""))
    if on_path:
        return on_path
    return None


def tool_status_text(filename: str, user_override: str = "") -> tuple[str, str]:
    if user_override and os.path.isfile(user_override):
        return (f"(user: {os.path.basename(user_override)})", "#2a7e2a")
    bundled = os.path.join(_get_tools_dir(), filename)
    if os.path.isfile(bundled):
        return ("(bundled ✓)", "#2a7e2a")
    on_path = shutil.which(filename.replace(".exe", ""))
    if on_path:
        return (f"(PATH: {on_path})", "#2a7e2a")
    return ("(NOT FOUND — browse to it)", "#cc3333")


# ---------------------------------------------------------------------------
# Upload logic (runs in a thread)
# ---------------------------------------------------------------------------
def do_upload(chip, port, baud, data_dir, mklittlefs_override, esptool_override,
              fs_offset, fs_size, log_fn, progress_fn, done_fn):
    """
    Build LittleFS image and flash it.

    Callbacks (all thread-safe, dispatched to main thread by caller):
        log_fn(str)                          — append to log
        progress_fn(phase_str, pct_or_None)  — update phase label + progress bar
        done_fn(bool)                        — signal completion
    """
    PAGE_SIZE = 256
    BLOCK_SIZE = 4096

    try:
        # --- Validate data dir ---
        progress_fn("Validating files...", 0)
        data_path = Path(data_dir)
        if not data_path.is_dir():
            log_fn(f"ERROR: Data folder not found: {data_dir}")
            done_fn(False)
            return

        files = list(data_path.iterdir())
        if not files:
            log_fn("ERROR: Data folder is empty — nothing to upload.")
            done_fn(False)
            return

        log_fn(f"Data folder: {data_dir}")
        log_fn(f"Files ({len(files)}):")
        total_size = 0
        for f in files:
            sz = f.stat().st_size if f.is_file() else 0
            total_size += sz
            log_fn(f"  {f.name}  ({sz:,} bytes)" if f.is_file() else f"  {f.name}/")
        log_fn(f"Total data size: {total_size:,} bytes")

        fs_size_int = int(fs_size, 16)
        if total_size > fs_size_int:
            log_fn(f"ERROR: Data ({total_size:,} bytes) exceeds partition ({fs_size_int:,} bytes).")
            done_fn(False)
            return

        # --- Step 1: Build LittleFS image ---
        import tempfile
        img_file = os.path.join(tempfile.gettempdir(), "littlefs_upload.bin")

        mklfs = find_tool("mklittlefs.exe", mklittlefs_override)
        if not mklfs:
            log_fn("ERROR: mklittlefs not found.")
            log_fn("  Place mklittlefs.exe in the tools/ folder, or browse to it in Settings.")
            done_fn(False)
            return

        progress_fn("Building LittleFS image...", 10)
        log_fn(f"\n[1/3] Building LittleFS image ({fs_size})...")
        log_fn(f"  Using: {mklfs}")

        cmd = [
            mklfs, "-c", str(data_path),
            "-s", str(fs_size_int),
            "-p", str(PAGE_SIZE),
            "-b", str(BLOCK_SIZE),
            img_file,
        ]
        log_fn(f"  > {' '.join(cmd)}")

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            log_fn(f"  mklittlefs FAILED (exit {proc.returncode}):")
            log_fn(proc.stderr or proc.stdout or "(no output)")
            done_fn(False)
            return

        if not os.path.isfile(img_file):
            log_fn("  ERROR: Image file was not created.")
            done_fn(False)
            return

        img_size = os.path.getsize(img_file)
        log_fn(f"  Image built: {img_size:,} bytes")
        progress_fn("Building LittleFS image...", 25)

        # --- Step 2: Verify image contents ---
        progress_fn("Verifying image contents...", 30)
        log_fn("\n[2/3] Verifying image contents...")
        verify_cmd = [mklfs, "-l", img_file, "-s", str(fs_size_int), "-p", str(PAGE_SIZE), "-b", str(BLOCK_SIZE)]
        verify_proc = subprocess.run(verify_cmd, capture_output=True, text=True)

        packed_files = set()
        if verify_proc.returncode == 0 and verify_proc.stdout:
            for line in verify_proc.stdout.strip().splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                parts = line_stripped.split(None, 1)
                if len(parts) < 2:
                    continue
                # Only process lines where first field is a number (file size)
                # Skip header lines, "<dir>" entries, metadata lines, etc.
                if parts[0] == "<dir>" or not parts[0].isdigit():
                    continue
                file_size = int(parts[0])
                # mklittlefs -l format varies by version:
                #   "107448 chrono_alarm.mp3"
                #   "107448 chrono_alarm.mp3\tSat Mar 07 01:11:26 2026"
                # Split on tab first to strip timestamp, then clean the path
                raw_name = parts[1].split("\t")[0].strip().lstrip("/")
                # Take just the filename (no subdirectory path issues)
                fname = os.path.basename(raw_name) if "/" in raw_name else raw_name
                packed_files.add(fname)
                log_fn(f"    ✓ {fname} ({file_size:,} bytes)")

        source_files = {f.name for f in data_path.iterdir() if f.is_file()}
        missing = source_files - packed_files

        if missing:
            log_fn("")
            log_fn(f"  ⚠ WARNING: {len(missing)} file(s) DID NOT FIT in the image:")
            for m in sorted(missing):
                fsize = (data_path / m).stat().st_size
                log_fn(f"    ✗ {m} ({fsize:,} bytes) — SKIPPED")
            log_fn("")
            log_fn(f"  Partition size {fs_size} ({fs_size_int:,} bytes) is too small")
            log_fn(f"  for all {len(source_files)} files ({total_size:,} bytes total).")
            log_fn("  Increase FS Size or remove files from the data folder.")
            log_fn("")
            log_fn("  ABORTING — not all files would be uploaded.")
            log_fn("  Fix the partition size and try again.")
            try:
                os.remove(img_file)
            except Exception:
                pass
            done_fn(False)
            return
        else:
            log_fn(f"  All {len(source_files)} files packed successfully.")

        # --- Step 3: Flash with esptool ---
        progress_fn("⚠ FLASHING — DO NOT CLOSE OR UNPLUG", 40)
        log_fn(f"\n[3/3] Flashing to {chip} on {port} @ {baud} baud...")
        log_fn(f"  Offset: {fs_offset}  Size: {fs_size}")
        log_fn("")
        log_fn("  ╔══════════════════════════════════════════════════╗")
        log_fn("  ║  DO NOT close this window or unplug the board!  ║")
        log_fn("  ║  Interrupting a flash can corrupt the partition. ║")
        log_fn("  ╚══════════════════════════════════════════════════╝")
        log_fn("")

        esptool_exe = find_tool("esptool.exe", esptool_override)

        if esptool_exe:
            log_fn(f"  Using: {esptool_exe}")

            env = os.environ.copy()
            esptool_dir = os.path.dirname(esptool_exe)
            env["PATH"] = esptool_dir + os.pathsep + env.get("PATH", "")

            cmd = [
                esptool_exe,
                "--chip", chip,
                "--port", port,
                "--baud", baud,
                "--before", "default_reset",
                "--after", "hard_reset",
                "write_flash",
                fs_offset, img_file,
            ]
            log_fn(f"  > {' '.join(cmd)}")

            # Stream output line-by-line for real-time progress
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, env=env, bufsize=1,
            )

            flash_started = False
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                log_fn(f"  {line}")

                # Parse esptool progress: "Writing at 0x00310000... (1 %)"
                if "Writing at" in line and "%" in line:
                    flash_started = True
                    try:
                        pct_str = line.split("(")[1].split("%")[0].strip()
                        pct = int(pct_str)
                        # Map esptool's 0-100% to our 45-95% range
                        bar_pct = 45 + int(pct * 0.5)
                        progress_fn(f"⚠ FLASHING — {pct}% — DO NOT CLOSE", bar_pct)
                    except (IndexError, ValueError):
                        pass
                elif "Connecting" in line:
                    progress_fn("⚠ Connecting to board...", 42)
                elif "Compressed" in line:
                    progress_fn("⚠ FLASHING — starting write...", 45)

            proc.wait()

            if proc.returncode != 0:
                log_fn(f"\n  esptool FAILED (exit {proc.returncode})")
                done_fn(False)
                return

        else:
            # Fallback: esptool Python module
            log_fn("  esptool.exe not found — trying Python esptool module...")
            try:
                import esptool
            except ImportError:
                log_fn("ERROR: esptool not available.")
                log_fn("  Either place esptool.exe in tools/, or: pip install esptool")
                done_fn(False)
                return

            log_fn(f"  Using: python -m esptool (v{getattr(esptool, '__version__', '?')})")

            esptool_args = [
                "--chip", chip,
                "--port", port,
                "--baud", baud,
                "--before", "default_reset",
                "--after", "hard_reset",
                "write_flash",
                fs_offset, img_file,
            ]
            log_fn(f"  > esptool {' '.join(esptool_args)}")

            from io import StringIO
            old_stdout, old_stderr = sys.stdout, sys.stderr
            capture = StringIO()
            sys.stdout = capture
            sys.stderr = capture

            try:
                esptool.main(esptool_args)
            except SystemExit as e:
                if e.code != 0:
                    sys.stdout, sys.stderr = old_stdout, old_stderr
                    log_fn(capture.getvalue())
                    log_fn(f"  esptool exited with code {e.code}")
                    done_fn(False)
                    return
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr

            output = capture.getvalue()
            lines = [l for l in output.strip().splitlines() if l.strip()]
            for line in lines[-15:]:
                log_fn(f"  {line}")

        # Cleanup
        progress_fn("Finishing up...", 98)
        try:
            os.remove(img_file)
        except Exception:
            pass

        log_fn("\n✓ Upload complete! Power-cycle your board and check Serial Monitor.")
        progress_fn("✓ Upload complete!", 100)
        done_fn(True)

    except Exception as e:
        log_fn(f"\nUNEXPECTED ERROR: {e}")
        import traceback
        log_fn(traceback.format_exc())
        done_fn(False)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class LittleFSUploader(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LittleFS Uploader")
        self.geometry("740x780")
        self.minsize(660, 660)
        self.resizable(True, True)

        self.cfg = load_config()
        self.uploading = False

        # Intercept window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabel", padding=2)
        style.configure("TButton", padding=4)
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10))
        style.configure("Upload.TButton", font=("Segoe UI", 10, "bold"))
        # Warning style for flash phase
        style.configure("Warning.TLabel", font=("Segoe UI", 10, "bold"), foreground="#cc0000")

        self._build_ui()
        self._load_fields()

    def _on_close(self):
        """Intercept window close — warn if upload/flash is in progress."""
        if self.uploading:
            result = messagebox.askokcancel(
                "Upload In Progress!",
                "⚠ An upload is currently in progress!\n\n"
                "Closing now may corrupt the LittleFS partition\n"
                "on your board and require a full re-flash.\n\n"
                "Are you sure you want to close?",
                icon="warning",
            )
            if not result:
                return  # User cancelled — stay open
        self.destroy()

    def _build_ui(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(main, text="LittleFS Uploader", font=("Segoe UI", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(main, text="Build & flash a LittleFS image to your ESP32",
                  font=("Segoe UI", 9), foreground="#666").pack(anchor=tk.W, pady=(0, 8))

        # Instructions
        instr_frame = ttk.LabelFrame(main, text="  Instructions  ", padding=8)
        instr_frame.pack(fill=tk.X, pady=(0, 8))

        instructions = (
            "1.  Close Arduino IDE / any Serial Monitor on this COM port.\n"
            "2.  Select the COM port your ESP32 is connected to.\n"
            "3.  Choose the correct chip model (ESP32-S3, etc.).\n"
            "4.  Point 'Data Folder' to the folder containing your files.\n"
            "5.  Set partition offset & size to match your partitions.csv.\n"
            "6.  Click 'Upload' and wait for completion.\n"
            "\n"
            "Tools:  esptool.exe + mklittlefs.exe should be in the tools/ folder.\n"
            "        If not bundled, use Browse to locate them manually."
        )
        ttk.Label(instr_frame, text=instructions, justify=tk.LEFT,
                  font=("Consolas", 9), wraplength=680).pack(anchor=tk.W)

        # ---- Settings ----
        settings = ttk.LabelFrame(main, text="  Settings  ", padding=8)
        settings.pack(fill=tk.X, pady=(0, 8))
        row = 0

        # COM Port
        ttk.Label(settings, text="COM Port:").grid(row=row, column=0, sticky=tk.W, pady=2)
        port_frame = ttk.Frame(settings)
        port_frame.grid(row=row, column=1, sticky=tk.EW, pady=2)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(port_frame, textvariable=self.port_var, width=44)
        self.port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(port_frame, text="↻", width=3, command=self._refresh_ports).pack(side=tk.LEFT, padx=(4, 0))
        row += 1

        # Chip
        ttk.Label(settings, text="Chip:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.chip_var = tk.StringVar()
        ttk.Combobox(settings, textvariable=self.chip_var, values=CHIP_OPTIONS,
                     state="readonly", width=20).grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        # Baud
        ttk.Label(settings, text="Baud Rate:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.baud_var = tk.StringVar()
        ttk.Combobox(settings, textvariable=self.baud_var, values=BAUD_OPTIONS, width=12).grid(
            row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        # Data folder
        ttk.Label(settings, text="Data Folder:").grid(row=row, column=0, sticky=tk.W, pady=2)
        data_frame = ttk.Frame(settings)
        data_frame.grid(row=row, column=1, sticky=tk.EW, pady=2)
        self.data_var = tk.StringVar()
        ttk.Entry(data_frame, textvariable=self.data_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(data_frame, text="Browse…", command=self._browse_data).pack(side=tk.LEFT, padx=(4, 0))
        row += 1

        # Partition preset
        ttk.Label(settings, text="Partition Preset:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.preset_var = tk.StringVar(value="Custom")
        preset_combo = ttk.Combobox(settings, textvariable=self.preset_var,
                                     values=list(PARTITION_PRESETS.keys()), state="readonly", width=48)
        preset_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        preset_combo.bind("<<ComboboxSelected>>", self._on_preset_change)
        row += 1

        # Offset
        ttk.Label(settings, text="FS Offset:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.offset_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.offset_var, width=16).grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        # Size
        ttk.Label(settings, text="FS Size:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.size_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.size_var, width=16).grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        # Separator before tools
        ttk.Separator(settings, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2,
                                                            sticky=tk.EW, pady=6)
        row += 1

        # --- mklittlefs ---
        ttk.Label(settings, text="mklittlefs:").grid(row=row, column=0, sticky=tk.W, pady=2)
        mkl_frame = ttk.Frame(settings)
        mkl_frame.grid(row=row, column=1, sticky=tk.EW, pady=2)
        self.mkl_var = tk.StringVar()
        ttk.Entry(mkl_frame, textvariable=self.mkl_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(mkl_frame, text="Browse…", command=self._browse_mklittlefs).pack(side=tk.LEFT, padx=(4, 0))
        row += 1

        mkl_text, mkl_color = tool_status_text("mklittlefs.exe")
        self.mkl_status_label = ttk.Label(settings, text=mkl_text, foreground=mkl_color,
                                           font=("Segoe UI", 8))
        self.mkl_status_label.grid(row=row, column=1, sticky=tk.W)
        row += 1

        # --- esptool ---
        ttk.Label(settings, text="esptool:").grid(row=row, column=0, sticky=tk.W, pady=2)
        esp_frame = ttk.Frame(settings)
        esp_frame.grid(row=row, column=1, sticky=tk.EW, pady=2)
        self.esp_var = tk.StringVar()
        ttk.Entry(esp_frame, textvariable=self.esp_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(esp_frame, text="Browse…", command=self._browse_esptool).pack(side=tk.LEFT, padx=(4, 0))
        row += 1

        esp_text, esp_color = tool_status_text("esptool.exe")
        if "NOT FOUND" in esp_text:
            try:
                import esptool
                esp_text = f"(Python module v{getattr(esptool, '__version__', '?')} ✓)"
                esp_color = "#2a7e2a"
            except ImportError:
                esp_text = "(NOT FOUND — place in tools/ or: pip install esptool)"
        self.esp_status_label = ttk.Label(settings, text=esp_text, foreground=esp_color,
                                           font=("Segoe UI", 8))
        self.esp_status_label.grid(row=row, column=1, sticky=tk.W)
        row += 1

        settings.columnconfigure(1, weight=1)

        # ---- Buttons ----
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 4))

        self.upload_btn = ttk.Button(btn_frame, text="⬆  Upload", style="Upload.TButton",
                                      command=self._start_upload)
        self.upload_btn.pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="Clear Log", command=self._clear_log).pack(side=tk.RIGHT)

        # ---- Progress section ----
        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill=tk.X, pady=(0, 4))

        # Phase label — shows current step + warning during flash
        self.phase_var = tk.StringVar(value="Ready")
        self.phase_label = ttk.Label(progress_frame, textvariable=self.phase_var,
                                      font=("Segoe UI", 10))
        self.phase_label.pack(anchor=tk.W)

        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var,
                                             maximum=100, length=400, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(2, 0))

        # Elapsed time
        self.elapsed_var = tk.StringVar(value="")
        ttk.Label(progress_frame, textvariable=self.elapsed_var,
                  font=("Segoe UI", 8), foreground="#888").pack(anchor=tk.E)

        # ---- Log ----
        log_frame = ttk.LabelFrame(main, text="  Log  ", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=12, font=("Consolas", 9),
            wrap=tk.WORD, state=tk.DISABLED,
            bg="#1e1e1e", fg="#cccccc",
            insertbackground="#cccccc",
            selectbackground="#264f78",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Configure text tags for colored log messages
        self.log_text.tag_configure("warning", foreground="#ffaa00")
        self.log_text.tag_configure("error", foreground="#ff5555")
        self.log_text.tag_configure("success", foreground="#55ff55")

        self._refresh_ports()

        # Timer tracking
        self._upload_start_time = None
        self._timer_id = None

    # ---- Field persistence ----
    def _load_fields(self):
        self.chip_var.set(self.cfg.get("chip", "esp32s3"))
        self.baud_var.set(self.cfg.get("baud", "460800"))
        self.data_var.set(self.cfg.get("data_dir", ""))
        self.offset_var.set(self.cfg.get("fs_offset", "0x310000"))
        self.size_var.set(self.cfg.get("fs_size", "0x9F0000"))
        self.mkl_var.set(self.cfg.get("mklittlefs_path", ""))
        self.esp_var.set(self.cfg.get("esptool_path", ""))

        saved_port = self.cfg.get("com_port", "")
        if saved_port:
            for val in self.port_combo["values"]:
                if val.startswith(saved_port):
                    self.port_var.set(val)
                    break
            else:
                self.port_var.set(saved_port)

    def _save_fields(self):
        port = self.port_var.get().split(" — ")[0].strip()
        self.cfg.update({
            "com_port": port,
            "chip": self.chip_var.get(),
            "baud": self.baud_var.get(),
            "data_dir": self.data_var.get(),
            "fs_offset": self.offset_var.get(),
            "fs_size": self.size_var.get(),
            "mklittlefs_path": self.mkl_var.get(),
            "esptool_path": self.esp_var.get(),
        })
        save_config(self.cfg)

    # ---- Timer ----
    def _start_timer(self):
        self._upload_start_time = time.monotonic()
        self._update_timer()

    def _update_timer(self):
        if self._upload_start_time and self.uploading:
            elapsed = time.monotonic() - self._upload_start_time
            mins, secs = divmod(int(elapsed), 60)
            self.elapsed_var.set(f"Elapsed: {mins}:{secs:02d}")
            self._timer_id = self.after(1000, self._update_timer)

    def _stop_timer(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    # ---- Callbacks ----
    def _refresh_ports(self):
        ports = list_com_ports()
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _browse_data(self):
        d = filedialog.askdirectory(title="Select data/ folder")
        if d:
            self.data_var.set(d)

    def _browse_mklittlefs(self):
        f = filedialog.askopenfilename(
            title="Select mklittlefs executable",
            filetypes=[("Executable", "*.exe"), ("All", "*.*")])
        if f:
            self.mkl_var.set(f)
            self.mkl_status_label.config(text=f"(user: {os.path.basename(f)})", foreground="#2a7e2a")

    def _browse_esptool(self):
        f = filedialog.askopenfilename(
            title="Select esptool executable",
            filetypes=[("Executable", "*.exe"), ("All", "*.*")])
        if f:
            self.esp_var.set(f)
            self.esp_status_label.config(text=f"(user: {os.path.basename(f)})", foreground="#2a7e2a")

    def _on_preset_change(self, event=None):
        preset = self.preset_var.get()
        if preset in PARTITION_PRESETS:
            offset, size = PARTITION_PRESETS[preset]
            if offset:
                self.offset_var.set(offset)
                self.size_var.set(size)

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _log(self, msg: str):
        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.after(0, _append)

    def _progress(self, phase: str, pct: int | None):
        """Thread-safe progress update."""
        def _update():
            self.phase_var.set(phase)
            if pct is not None:
                self.progress_var.set(pct)

            # Color the phase label red during flash, normal otherwise
            if "DO NOT CLOSE" in phase or "FLASHING" in phase:
                self.phase_label.config(foreground="#cc0000", font=("Segoe UI", 10, "bold"))
                # Also update window title as extra visibility
                self.title(f"⚠ FLASHING IN PROGRESS — LittleFS Uploader")
            elif "complete" in phase.lower():
                self.phase_label.config(foreground="#2a7e2a", font=("Segoe UI", 10, "bold"))
                self.title("✓ Done — LittleFS Uploader")
            else:
                self.phase_label.config(foreground="#555", font=("Segoe UI", 10))
                self.title("LittleFS Uploader")
        self.after(0, _update)

    def _start_upload(self):
        if self.uploading:
            return

        port = self.port_var.get().split(" — ")[0].strip()
        if not port:
            messagebox.showerror("Error", "Select a COM port.")
            return

        data_dir = self.data_var.get().strip()
        if not data_dir or not os.path.isdir(data_dir):
            messagebox.showerror("Error", "Select a valid data folder.")
            return

        fs_offset = self.offset_var.get().strip()
        fs_size = self.size_var.get().strip()
        try:
            int(fs_offset, 16)
            int(fs_size, 16)
        except ValueError:
            messagebox.showerror("Error", "FS Offset and Size must be valid hex (e.g. 0x310000).")
            return

        if not messagebox.askokcancel(
            "Confirm Upload",
            f"Upload to {self.chip_var.get()} on {port}?\n\n"
            f"Data: {data_dir}\n"
            f"Offset: {fs_offset}  Size: {fs_size}\n\n"
            "Make sure Arduino IDE / Serial Monitor is CLOSED.\n\n"
            "⚠ Do NOT close this window or unplug the board\n"
            "   during the upload process."):
            return

        self._save_fields()
        self._clear_log()
        self.uploading = True
        self.upload_btn.config(state=tk.DISABLED)
        self.progress_var.set(0)
        self._start_timer()

        def on_done(success):
            def _finish():
                self.uploading = False
                self.upload_btn.config(state=tk.NORMAL)
                self._stop_timer()
                if success:
                    self._progress("✓ Upload complete!", 100)
                    # Show final elapsed time
                    if self._upload_start_time:
                        elapsed = time.monotonic() - self._upload_start_time
                        mins, secs = divmod(int(elapsed), 60)
                        self.elapsed_var.set(f"Completed in {mins}:{secs:02d}")
                else:
                    self._progress("✗ Upload failed", None)
                    self.title("LittleFS Uploader")
            self.after(0, _finish)

        t = threading.Thread(target=do_upload, daemon=True, args=(
            self.chip_var.get(), port, self.baud_var.get(),
            data_dir, self.mkl_var.get().strip(), self.esp_var.get().strip(),
            fs_offset, fs_size, self._log, self._progress, on_done,
        ))
        t.start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = LittleFSUploader()
    app.mainloop()
