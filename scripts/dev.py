#!/usr/bin/env python3
"""Sobe API (:8000) e web (:5173), valida os dois e abre o navegador. Ctrl+C encerra tudo.

Windows, Linux e macOS; só biblioteca padrão. Logs em .run/.
A web é validada por /api/health *através do Vite*: HTML no lugar de JSON = proxy quebrado.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / ".run"
WIN = os.name == "nt"
API_PORT, WEB_PORT = 8000, 5173


def die(msg: str) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def port_busy(port: int) -> bool:
    for fam, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(fam) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:  # sem IPv6 nesta máquina
            pass
    return False


def venv_python() -> str:
    py = ROOT / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")
    if not py.exists():
        die("falta o venv: python -m venv .venv && .venv/bin/pip install -e .[api,dev] "
            "(no Windows: .venv\\Scripts\\pip)")
    return str(py)


def start(cmd: list[str], name: str) -> subprocess.Popen:
    out = open(LOGS / f"{name}.log", "w")  # noqa: SIM115 (vive até o fim do processo)
    if WIN:
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        kw = {"start_new_session": True}
    return subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, **kw)


def stop(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    if WIN:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def wait_health(url: str, what: str, log: str, p: subprocess.Popen) -> None:
    for _ in range(60):
        if p.poll() is not None:
            die(f"{what} encerrou ao iniciar. Veja {LOGS / log}")
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if json.loads(r.read()).get("ok") is True:
                    print(f"OK  {what}  ({url})")
                    return
        except (OSError, ValueError):  # recusou, timeout ou corpo não-JSON (HTML)
            pass
        time.sleep(0.5)
    die(f"{what} não respondeu JSON em 30 s: {url}. Veja {LOGS / log}")


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)  # mensagens aparecem na hora, mesmo redirecionadas
    py = venv_python()
    npm = shutil.which("npm")
    if not npm:
        die("npm não encontrado: instale o Node.js")
    if not (ROOT / "web" / "node_modules").exists():
        die("falta instalar o web: npm --prefix web install")
    for port in (API_PORT, WEB_PORT):
        if port_busy(port):
            die(f"porta {port} já em uso. Feche o processo que a usa e rode de novo.")
    LOGS.mkdir(exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    procs: list[subprocess.Popen] = []
    try:
        api = start([py, "-m", "uvicorn", "market_holder.api.app:create_app", "--factory",
                     "--port", str(API_PORT)], "api")
        procs.append(api)
        wait_health(f"http://127.0.0.1:{API_PORT}/api/health", "API", "api.log", api)

        web = start([npm, "--prefix", "web", "run", "dev", "--", "--port", str(WEB_PORT),
                     "--strictPort"], "web")
        procs.append(web)
        wait_health(f"http://localhost:{WEB_PORT}/api/health", "Web + proxy", "web.log", web)

        webbrowser.open(f"http://localhost:{WEB_PORT}")
        print(f"\nPronto: http://localhost:{WEB_PORT}   (Ctrl+C para encerrar; logs em .run/)")
        while True:
            time.sleep(1)
            for p in procs:
                if p.poll() is not None:
                    die(f"processo {p.pid} caiu. Veja os logs em {LOGS}")
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        for p in reversed(procs):
            stop(p)


if __name__ == "__main__":
    main()
