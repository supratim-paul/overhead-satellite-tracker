"""One-command launcher, no Docker. Usage: python start.py [--port 8000] [--rebuild]"""
import subprocess, sys, shutil, os, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB, API, VENV = ROOT / "frontend", ROOT / "backend", ROOT / ".venv"
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=int(os.getenv("PORT", 8000)))
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--rebuild", action="store_true")
ap.add_argument("--dev", action="store_true", help="hot reload: backend :8000 + vite :5173")
a = ap.parse_args()


def run(cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True, shell=(os.name == "nt" and cmd[0] == "npm"))


py = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not py.exists():
    run([sys.executable, "-m", "venv", str(VENV)])
run([str(py), "-m", "pip", "install", "-q", "-r", str(API / "requirements.txt")])

if a.dev:
    if not shutil.which("npm"):
        sys.exit("Node.js 18+ is required: https://nodejs.org")
    if not (WEB / "node_modules").exists():
        run(["npm", "install"], WEB)
    nt = os.name == "nt"
    procs = [
        subprocess.Popen([str(py), "-m", "uvicorn", "main:app", "--reload", "--port", "8000"], cwd=API),
        subprocess.Popen(["npm", "run", "dev"], cwd=WEB, shell=nt),
    ]
    print("\nOpen http://localhost:5173\n")
    try:
        procs[1].wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
    sys.exit(0)

if a.rebuild or not (WEB / "dist" / "index.html").exists():
    if not shutil.which("npm"):
        sys.exit("Node.js 18+ is required to build the frontend: https://nodejs.org")
    run(["npm", "install"], WEB)
    run(["npm", "run", "build"], WEB)

print(f"\nOpen http://localhost:{a.port}\n")
run([str(py), "-m", "uvicorn", "main:app", "--host", a.host, "--port", str(a.port)], API)
