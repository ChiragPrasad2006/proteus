#!/usr/bin/env python3
"""
Proteus Launcher - Standalone Windows executable for the Proteus email agent.

This script manages the complete Proteus stack:
1. Sets up environment variables (HF_HOME, EMAIL_WRITER_LOCAL_DATA_DIR)
2. Starts Ollama if not running, verifies qwen3:8b model (with GPU warm-up)
3. Builds frontend (npm run build) if needed
4. Starts FastAPI backend and polls for health
5. Opens browser to http://127.0.0.1:8000 (single-port serving)
6. Clean shutdown on exit
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Configuration
# When frozen by PyInstaller (--onefile), __file__ points into the temporary
# _MEI extraction directory, which is wiped on exit. The real application root
# is the directory containing the frozen executable (sys.executable).
if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).resolve().parent
else:
    APP_ROOT = Path(__file__).resolve().parent

VENV_PYTHON = Path(r"D:\\MLops\\.venv\\Scripts\\python.exe")
# Use full path to npm to avoid PATH issues in frozen executable
NPM_CMD = Path(r"C:\\Program Files\\nodejs\\npm.cmd")
BACKEND_MODULE = "backend.main:app"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_DIR = APP_ROOT / "frontend"
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:8b"
HEALTH_ENDPOINT = f"http://{BACKEND_HOST}:{BACKEND_PORT}/api/health"
FRONTEND_DIST = FRONTEND_DIR / "dist"

# Global process handles for cleanup
ollama_process: Optional[subprocess.Popen] = None
backend_process: Optional[subprocess.Popen] = None


def log(msg: str) -> None:
    """Print a timestamped log message."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def run_cmd(cmd: list[str], cwd: Optional[Path] = None, **kwargs) -> subprocess.Popen:
    """Run a command and return the process handle."""
    log(f"Starting: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, **kwargs)


def check_url(url: str, timeout: float = 5.0) -> tuple[bool, Optional[dict]]:
    """Check if a URL responds with HTTP 200. Returns (success, json_data)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Proteus-Launcher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = resp.read().decode("utf-8")
                return True, json.loads(data) if data else None
    except Exception:
        pass
    return False, None


def wait_for_url(url: str, max_wait: int = 60, interval: float = 2.0, check_json: bool = False) -> tuple[bool, Optional[dict]]:
    """Poll a URL until it responds or timeout."""
    log(f"Waiting for {url}...")
    start = time.time()
    while time.time() - start < max_wait:
        success, data = check_url(url)
        if success:
            if check_json and data:
                return True, data
            elif not check_json:
                return True, data
            log("  Response received but JSON check pending...")
        time.sleep(interval)
    return False, None


def cleanup_stale_ports() -> None:
    """Kill any stale processes listening on ports 8000 (FastAPI) and 5173 (Vite)."""
    log("=" * 60)
    log("[0/5] Pre-flight port cleanup (8000, 5173)...")
    log("=" * 60)

    target_ports = {8000, 5173}
    killed_any = False

    if HAS_PSUTIL:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.net_connections(kind='inet'):
                    if conn.laddr.port in target_ports and conn.status == 'LISTEN':
                        log(f"  Killing stale process on port {conn.laddr.port}: PID={proc.pid}, name={proc.info['name']}")
                        proc.kill()
                        killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    else:
        # Fallback: use netstat + taskkill
        try:
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                for port in target_ports:
                    if f":{port} " in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            if pid.isdigit():
                                log(f"  Killing stale process on port {port}: PID={pid}")
                                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                                killed_any = True
        except Exception as e:
            log(f"  Warning: netstat fallback failed: {e}")

    if killed_any:
        log("  Stale processes terminated, waiting for ports to release...")
        time.sleep(2)
    else:
        log("  No stale listeners found on ports 8000 or 5173")


def setup_environment() -> None:
    """Set up environment variables."""
    # HF_HOME on D: drive if available
    if Path("D:\\").exists():
        os.environ["HF_HOME"] = r"D:\huggingface_cache"
        log(f"HF_HOME set to D:\\huggingface_cache")
    else:
        log("D:\\ drive not found, using default HF cache location")

    # Local data directory
    local_data_dir = APP_ROOT / "local_user_data"
    local_data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["EMAIL_WRITER_LOCAL_DATA_DIR"] = str(local_data_dir)
    # The packaged launcher serves the built SPA from FastAPI on port 8000;
    # OAuth callbacks must not redirect to Vite's development port 5173.
    os.environ["FRONTEND_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    log(f"EMAIL_WRITER_LOCAL_DATA_DIR set to {local_data_dir}")


def ensure_ollama() -> bool:
    """Ensure Ollama is running and qwen3:8b model is available."""
    global ollama_process

    log("=" * 60)
    log("[2/5] Checking Ollama & qwen3:8b...")
    log("=" * 60)

    # Check if Ollama API is responding
    success, _ = check_url(f"{OLLAMA_URL}/api/tags", timeout=3.0)
    if not success:
        log("Ollama not responding. Starting Ollama server...")
        try:
            # Start ollama serve in background (CREATE_NO_WINDOW on Windows)
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            ollama_process = subprocess.Popen(
                ["ollama", "serve"],
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log("Ollama server started in background")
        except FileNotFoundError:
            log("ERROR: 'ollama' command not found. Please install Ollama from https://ollama.ai")
            return False
        except Exception as e:
            log(f"ERROR: Failed to start Ollama: {e}")
            return False

        # Wait for Ollama API to become available
        success, _ = wait_for_url(f"{OLLAMA_URL}/api/tags", max_wait=60, interval=2.0)
        if not success:
            log("ERROR: Ollama failed to start within 60 seconds")
            return False
        log("Ollama API is now responding")
    else:
        log("Ollama is already running")

    # Check if qwen3:8b model is pulled
    success, data = check_url(f"{OLLAMA_URL}/api/tags", timeout=5.0)
    if success and data:
        models = [m.get("name", "") for m in data.get("models", [])]
        if any(OLLAMA_MODEL in m for m in models):
            log(f"Model {OLLAMA_MODEL} is already available")
        else:
            log(f"Model {OLLAMA_MODEL} not found. Pulling...")
            try:
                result = subprocess.run(
                    ["ollama", "pull", OLLAMA_MODEL],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode != 0:
                    log(f"ERROR: Failed to pull {OLLAMA_MODEL}: {result.stderr}")
                    return False
                log(f"Model {OLLAMA_MODEL} pulled successfully")
            except subprocess.TimeoutExpired:
                log(f"ERROR: Pulling {OLLAMA_MODEL} timed out")
                return False
            except Exception as e:
                log(f"ERROR: Failed to pull model: {e}")
                return False
    else:
        log(f"Model {OLLAMA_MODEL} not found. Pulling...")
        try:
            result = subprocess.run(
                ["ollama", "pull", OLLAMA_MODEL],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                log(f"ERROR: Failed to pull {OLLAMA_MODEL}: {result.stderr}")
                return False
            log(f"Model {OLLAMA_MODEL} pulled successfully")
        except subprocess.TimeoutExpired:
            log(f"ERROR: Pulling {OLLAMA_MODEL} timed out")
            return False
        except Exception as e:
            log(f"ERROR: Failed to pull model: {e}")
            return False

    # GPU warm-up: send a tiny inference request to load qwen3:8b into VRAM
    log(f"Warming up {OLLAMA_MODEL} on GPU (keep_alive=30m)...")
    try:
        warmup_payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "think": False,
            "options": {"num_predict": 1},
            "keep_alive": "30m"
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(warmup_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Proteus-Launcher/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                log(f"{OLLAMA_MODEL} loaded into GPU VRAM and warmed up")
            else:
                log(f"Warm-up request returned {resp.status}, continuing anyway")
    except Exception as e:
        log(f"Warning: GPU warm-up failed ({e}), continuing anyway")

    return True


def build_frontend() -> bool:
    """Build frontend for production if dist is missing or outdated."""
    if not FRONTEND_DIST.exists():
        log("Frontend dist/ not found. Building...")
        return run_npm_build()

    # Compare the newest source file under frontend/src/ against the newest file
    # in the build. The dist/ *directory* mtime is not reliable: replacing a file
    # in place leaves the directory mtime untouched, so a stale build would look
    # fresh. The source scan must exclude dist/ and node_modules.
    try:
        src_root = FRONTEND_DIR / "src"
        src_files = (
            src_root.rglob("*")
            if src_root.is_dir()
            else FRONTEND_DIR.rglob("*")
        )
        src_mtime = max(
            (
                f.stat().st_mtime
                for f in src_files
                if f.is_file()
                and "node_modules" not in f.parts
                and "dist" not in f.relative_to(FRONTEND_DIR).parts
            ),
            default=0
        )
        dist_mtime = max(
            (f.stat().st_mtime for f in FRONTEND_DIST.rglob("*") if f.is_file()),
            default=0
        )
        if src_mtime > dist_mtime:
            log("Frontend source is newer than dist/. Rebuilding...")
            return run_npm_build()
    except Exception:
        pass

    log("Frontend dist/ is up to date")
    return True


def run_npm_build() -> bool:
    """Run npm run build in frontend directory."""
    if not (FRONTEND_DIR / "package.json").exists():
        log("ERROR: Frontend package.json not found")
        return False

    log("Running npm install...")
    result = subprocess.run([str(NPM_CMD), "install"], cwd=FRONTEND_DIR, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log(f"ERROR: npm install failed: {result.stderr}")
        return False

    log("Running npm run build...")
    result = subprocess.run([str(NPM_CMD), "run", "build"], cwd=FRONTEND_DIR, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log(f"ERROR: npm run build failed: {result.stderr}")
        return False

    log("Frontend built successfully")
    return True


def start_backend() -> bool:
    """Start FastAPI backend and wait for health endpoint."""
    global backend_process

    log("=" * 60)
    log("[4/5] Starting FastAPI Backend...")
    log("=" * 60)

    if not VENV_PYTHON.exists():
        log(f"ERROR: Python not found at {VENV_PYTHON}")
        log("Please verify the virtual environment path")
        return False

    # Verify the backend package actually lives under the resolved app root.
    # In a frozen build APP_ROOT is the executable's directory; if backend/
    # is missing there, uvicorn cannot import "backend.main:app".
    backend_dir = APP_ROOT / "backend"
    if not backend_dir.is_dir():
        log(f"ERROR: Backend directory not found at {backend_dir}")
        log(f"Application root resolved to: {APP_ROOT}")
        log("Expected the 'backend' package to be alongside the executable")
        return False

    # Make sure the backend package is importable by uvicorn regardless of cwd.
    backend_env = os.environ.copy()
    backend_env["PYTHONPATH"] = str(APP_ROOT)

    # Start uvicorn
    backend_process = run_cmd([
        str(VENV_PYTHON), "-m", "uvicorn", BACKEND_MODULE,
        "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)
    ], cwd=APP_ROOT, env=backend_env)

    # Wait for health endpoint with model check
    success, data = wait_for_url(HEALTH_ENDPOINT, max_wait=120, interval=3.0, check_json=True)
    if not success:
        log("ERROR: FastAPI backend failed to start within 120 seconds")
        return False

    # Verify model is loaded
    if data:
        qwen_info = data.get("qwen", {}) or data.get("generation", {})
        model_available = qwen_info.get("preferred_ollama_model_available", False)
        if model_available:
            log("Backend is healthy with model loaded")
        else:
            log("WARNING: Backend started but model may not be fully loaded yet")
            log(f"  qwen info: {qwen_info}")
    else:
        log("Backend health endpoint responded but no data")

    return True


def open_browser() -> None:
    """Open the default browser to the backend URL (single-port serving)."""
    log("=" * 60)
    log("[5/5] Opening browser...")
    log("=" * 60)

    backend_url = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    try:
        if sys.platform == "win32":
            os.startfile(backend_url)  # type: ignore
        elif sys.platform == "darwin":
            subprocess.run(["open", backend_url])
        else:
            subprocess.run(["xdg-open", backend_url])
        log(f"Opened {backend_url} in default browser")
    except Exception as e:
        log(f"Could not open browser automatically: {e}")
        log(f"Please manually open: {backend_url}")


def cleanup() -> None:
    """Clean up all child processes on exit."""
    log("Shutting down...")

    for name, proc in [
        ("Backend", backend_process),
        ("Ollama", ollama_process),
    ]:
        if proc and proc.poll() is None:
            log(f"Terminating {name} (PID: {proc.pid})...")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            except Exception:
                pass

    log("All processes terminated")


def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals."""
    log(f"Received signal {signum}")
    cleanup()
    sys.exit(0)


def main() -> int:
    """Main entry point."""
    # Register cleanup handlers
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal_handler)

    print("=" * 60)
    print("  Proteus — The Local-First AI Email Agent")
    print("=" * 60)
    print()

    # Step 0: Pre-flight port cleanup
    cleanup_stale_ports()

    # Step 1: Environment
    log("=" * 60)
    log("[1/5] Environment & Cache Safety")
    log("=" * 60)
    setup_environment()

    # Step 2: Build frontend (before backend so dist/ is ready for static serving)
    log("=" * 60)
    log("[2/5] Building frontend (production)...")
    log("=" * 60)
    if not build_frontend():
        log("FATAL: Frontend build failed")
        return 1

    # Step 3: Ollama + GPU warm-up
    if not ensure_ollama():
        log("FATAL: Ollama setup failed")
        return 1

    # Step 4: Backend (serves both API and SPA static files)
    if not start_backend():
        log("FATAL: Backend startup failed")
        return 1

    # Step 5: Open browser
    open_browser()

    # Success message
    print()
    print("=" * 60)
    print("  Proteus is live!")
    print("=" * 60)
    print(f"  Backend API + UI : http://{BACKEND_HOST}:{BACKEND_PORT}")
    print(f"  API Health       : {HEALTH_ENDPOINT}")
    print(f"  Ollama           : {OLLAMA_URL} (model: {OLLAMA_MODEL})")
    print()
    print("  Press Ctrl+C to stop all services")
    print("=" * 60)

    # Keep running until interrupted
    try:
        while True:
            # Check if any critical process died
            if backend_process and backend_process.poll() is not None:
                log("ERROR: Backend process died unexpectedly")
                return 1
            time.sleep(5)
    except KeyboardInterrupt:
        log("Interrupted by user")

    return 0


if __name__ == "__main__":
    sys.exit(main())
