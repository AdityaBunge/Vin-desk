#!/usr/bin/env python3
"""Run Vin Desk for development with one command: database, backend and frontend.

    python run.py              start everything and open the browser
    python run.py --setup      first time on a new computer: create the Python environment,
                               install packages, set up the database and demo data, then start
    python run.py --stop-db    also stop the database when you press Ctrl+C

Logs from the backend [api] and frontend [web] appear in this window. Press Ctrl+C to stop.
Uses only the Python standard library, so any Python 3.10+ can run it.
"""
import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
WINDOWS = os.name == "nt"
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
DB_PORT = 5544
PG_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ForceServiceCentre" / "pgdata"

COLOURS = {"api": "\033[36m", "web": "\033[35m", "db": "\033[33m", "run": "\033[32m", "err": "\033[31m"}
RESET = "\033[0m"


def say(tag: str, text: str) -> None:
    print(f"{COLOURS.get(tag, '')}[{tag}]{RESET} {text}", flush=True)


def port_open(port: int) -> bool:
    # Vite listens on "localhost", which is IPv6 (::1) on recent Windows/Node; check both.
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def wait_for(check, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.5)
    return False


def run(cmd: list, cwd: Path, what: str) -> None:
    say("run", f"{what}...")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        say("err", f"{what} failed (exit code {result.returncode}).")
        sys.exit(1)


# --- Database -----------------------------------------------------------------------------


def pg_bin() -> Path | None:
    if os.environ.get("PG_BIN"):
        return Path(os.environ["PG_BIN"])
    if WINDOWS:
        base = Path("C:/Program Files/PostgreSQL")
        versions = sorted((p for p in base.glob("*") if (p / "bin" / "pg_ctl.exe").exists()),
                          key=lambda p: int("".join(c for c in p.name if c.isdigit()) or 0), reverse=True)
        return versions[0] / "bin" if versions else None
    found = shutil.which("pg_ctl")
    return Path(found).parent if found else None


def exe(bin_dir: Path, name: str) -> str:
    return str(bin_dir / (name + (".exe" if WINDOWS else "")))


def start_database() -> None:
    if port_open(DB_PORT):
        say("db", f"PostgreSQL already running on port {DB_PORT}.")
        return
    bin_dir = pg_bin()
    if bin_dir is None:
        say("err", "PostgreSQL binaries not found. Install PostgreSQL 15+ or set the PG_BIN environment variable.")
        sys.exit(1)
    if not (PG_DATA / "PG_VERSION").exists():
        say("db", f"Creating a development database cluster in {PG_DATA} ...")
        PG_DATA.mkdir(parents=True, exist_ok=True)
        subprocess.run([exe(bin_dir, "initdb"), "-D", str(PG_DATA), "-U", "fsc", "-A", "trust", "-E", "UTF8", "--locale=C"],
                       check=True, stdout=subprocess.DEVNULL)
    say("db", f"Starting PostgreSQL on port {DB_PORT} ...")
    # Start detached with no pipes: an inherited pipe would keep this script waiting on the server.
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if WINDOWS else 0
    subprocess.Popen(
        [exe(bin_dir, "pg_ctl"), "-D", str(PG_DATA), "-l", str(PG_DATA.parent / "pg.log"),
         "-o", f"-p {DB_PORT} -c listen_addresses=localhost", "start"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags, start_new_session=not WINDOWS,
    )
    if not wait_for(lambda: port_open(DB_PORT), 30):
        say("err", f"PostgreSQL did not start. See {PG_DATA.parent / 'pg.log'}")
        sys.exit(1)

    def pg_ready() -> bool:
        result = subprocess.run(
            [exe(bin_dir, "psql"), "-h", "localhost", "-p", str(DB_PORT), "-U", "fsc", "-d", "postgres",
             "-Atc", "select 1"],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    if not wait_for(pg_ready, 30):
        say("err", f"PostgreSQL is listening but not accepting connections yet. See {PG_DATA.parent / 'pg.log'}")
        sys.exit(1)

    existing = subprocess.run([exe(bin_dir, "psql"), "-h", "localhost", "-p", str(DB_PORT), "-U", "fsc", "-d", "postgres",
                               "-Atc", "select datname from pg_database"], capture_output=True, text=True).stdout.split()
    for name in ("fsc_dev", "fsc_test"):
        if name not in existing:
            subprocess.run([exe(bin_dir, "createdb"), "-h", "localhost", "-p", str(DB_PORT), "-U", "fsc", name], check=True)
    say("db", "PostgreSQL is running.")


def stop_database() -> None:
    bin_dir = pg_bin()
    if bin_dir and port_open(DB_PORT):
        subprocess.run([exe(bin_dir, "pg_ctl"), "-D", str(PG_DATA), "-m", "fast", "stop"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        say("db", "PostgreSQL stopped.")


# --- First-time setup ---------------------------------------------------------------------


def setup() -> None:
    if not VENV_PY.exists():
        run([sys.executable, "-m", "venv", ".venv"], BACKEND, "Creating the Python environment (backend/.venv)")
    run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", "requirements-dev.txt"], BACKEND, "Installing backend packages")
    run([npm(), "install"], FRONTEND, "Installing frontend packages")
    if not (ROOT / ".env").exists() and not (BACKEND / ".env").exists():
        shutil.copy(ROOT / ".env.example", ROOT / ".env")
        say("run", "Created .env from .env.example (email goes to the development simulator until you set up Gmail).")


def npm() -> str:
    found = shutil.which("npm")
    if not found:
        say("err", "Node.js / npm not found. Install Node.js 20 LTS from https://nodejs.org and try again.")
        sys.exit(1)
    return found


# --- Running the servers ------------------------------------------------------------------


def stream(tag: str, proc: subprocess.Popen) -> None:
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace").rstrip()
        if line:
            say(tag, line)


def launch(tag: str, cmd: list, cwd: Path, **extra_env: str) -> subprocess.Popen:
    env = dict(os.environ, PYTHONUNBUFFERED="1", **extra_env)
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0, start_new_session=not WINDOWS,
    )
    threading.Thread(target=stream, args=(tag, proc), daemon=True).start()
    return proc


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WINDOWS:  # uvicorn --reload and npm both start child processes: stop the whole tree
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def backend_healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--setup", action="store_true", help="first-time install, database and demo data")
    parser.add_argument("--stop-db", action="store_true", help="stop PostgreSQL when exiting")
    parser.add_argument("--no-db", action="store_true", help="do not start PostgreSQL (use DATABASE_URL as is)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=5173)
    args = parser.parse_args()
    if WINDOWS:
        os.system("")  # enable colours in the Windows console
    sys.stdout.reconfigure(errors="replace")  # never crash on a character the console cannot show

    if args.setup:
        setup()
    if not VENV_PY.exists():
        say("err", "The backend Python environment is missing. Run:  python run.py --setup")
        sys.exit(1)
    if not (FRONTEND / "node_modules").exists():
        run([npm(), "install"], FRONTEND, "Installing frontend packages")

    if not args.no_db:
        start_database()
    run([str(VENV_PY), "-m", "alembic", "upgrade", "head"], BACKEND, "Updating the database schema")
    if args.setup:
        run([str(VENV_PY), "-m", "app.seed"], BACKEND, "Loading demo users, parts and customers")

    procs: list[tuple[str, subprocess.Popen]] = []
    if port_open(args.api_port):
        say("api", f"Something is already running on port {args.api_port}; using it as the backend.")
    else:
        procs.append(("api", launch("api", [str(VENV_PY), "-m", "uvicorn", "app.main:app", "--port", str(args.api_port),
                                            "--reload", "--reload-dir", "app"], BACKEND)))
    if port_open(args.web_port):
        say("web", f"Something is already running on port {args.web_port}; using it as the frontend.")
    else:
        procs.append(("web", launch("web", [npm(), "run", "dev", "--", "--port", str(args.web_port), "--strictPort"], FRONTEND,
                                    VITE_API_PROXY=f"http://127.0.0.1:{args.api_port}")))

    def shutdown(code: int = 0) -> None:
        say("run", "Stopping...")
        for _, p in procs:
            stop(p)
        if args.stop_db:
            stop_database()
        sys.exit(code)

    try:
        ready = wait_for(lambda: backend_healthy(args.api_port) and port_open(args.web_port), 90)
        if not ready:
            say("err", "The servers did not become ready within 90 seconds; see the messages above.")
            shutdown(1)
        url = f"http://localhost:{args.web_port}"
        say("run", "")
        say("run", f"Vin Desk is running:  {url}")
        say("run", "Demo sign-in (password Demo@12345): manager@ / mechanic@ / inventory@ / admin@demo.local")
        say("run", "Press Ctrl+C to stop.")
        if not args.no_browser:
            webbrowser.open(url)
        while True:
            for tag, p in procs:
                if p.poll() is not None:
                    say("err", f"The {'backend' if tag == 'api' else 'frontend'} stopped unexpectedly (exit code {p.returncode}).")
                    shutdown(1)
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(0)


if __name__ == "__main__":
    main()
