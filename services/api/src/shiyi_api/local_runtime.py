"""Start the local synthetic workbench and worker with an isolated disposable database."""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run(port):
    # Never use the caller's actual SHIYI_DB_PATH or network model configuration.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    with TemporaryDirectory(prefix="shiyi-workbench-") as folder:
        env = {
            **os.environ,
            "SHIYI_DB_PATH": str(Path(folder) / "demo.sqlite3"),
            "SHIYI_DEV_USERS": "{}",
            "SHIYI_DEV_DEVICES": "{}",
            "SHIYI_RANKER": "rules",
            "SHIYI_DEBUG_WORKBENCH": "1",
        }
        children = []
        try:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "shiyi_api.main:app",
                 "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers"],
                env=env,
            )
            children.append(server)
            with httpx.Client(timeout=0.5, trust_env=False) as client:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError("API stopped during startup")
                    try:
                        res = client.get(f"http://127.0.0.1:{port}/api/v1/health")
                        if res.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Local API startup timed out")
            children.append(subprocess.Popen(
                [sys.executable, "-m", "shiyi_api.harness.scheduler", "--interval", "30"],
                env=env,
            ))
            print(f"LOCAL SYNTHETIC WORKBENCH: http://127.0.0.1:{port}/workbench", flush=True)
            print("Temporary database; Ctrl+C stops API and worker and removes data.", flush=True)
            while all(child.poll() is None for child in children):
                time.sleep(0.5)
            raise RuntimeError("API or worker stopped unexpectedly")
        finally:
            for process in reversed(children):
                stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be in 1024..65535")

    def terminate(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    try:
        run(args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
