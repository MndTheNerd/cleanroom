#!/usr/bin/env python3
"""Install or check the optional add-ons, chosen when the plugin is enabled (plugin userConfig):

  JPlag    jar from the official GitHub release + a portable Eclipse Temurin Java runtime (JPlag 6.x needs Java 25)
  ScanCode ScanCode Toolkit in its own virtualenv, from PyPI or from a local .zip / .whl / folder

  install_tools.py --status                       what is installed where
  install_tools.py [--jplag] [--scancode] [--scancode-source PATH] [--dest DIR]
  install_tools.py --from-plugin-options [--background]
        read the choices Claude Code passes to hooks (CLAUDE_PLUGIN_OPTION_INSTALL_JPLAG, ..._INSTALL_SCANCODE,
        ..._SCANCODE_SOURCE) and install whatever is selected and missing. --background returns at once and
        logs to <dest>/install.log (used by the SessionStart hook).

Default destination: $CLAUDE_PLUGIN_DATA/tools, else <plugin>/.tools.
Docker is NOT installed by this script: it needs admin rights and (on Windows) WSL2. See README.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
JPLAG_VERSION = "6.3.0"
JAVA_VERSION = "25"


def default_dest() -> Path:
    if os.environ.get("CLAUDE_PLUGIN_DATA"):
        return Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "tools"
    return PLUGIN_ROOT / ".tools"


def truthy(v: str | None) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def venv_python(dest: Path) -> Path:
    return dest / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def scancode_exe(dest: Path) -> Path:
    return dest / "venv" / ("Scripts/scancode.exe" if os.name == "nt" else "bin/scancode")


def java_exe(dest: Path) -> Path | None:
    for exe in sorted((dest / "jdk").glob("*/bin/java*")) + sorted((dest / "jdk").glob("*/Contents/Home/bin/java")):
        if exe.stem == "java":
            return exe
    return None


def status(dest: Path) -> dict:
    return {
        "dest": str(dest),
        "jplag": (dest / "jplag.jar").exists() and java_exe(dest) is not None,
        "scancode": scancode_exe(dest).exists(),
        "docker": shutil.which("docker") is not None,
        "installing": (dest / "install.lock").exists(),
    }


def fetch(url: str, dst: Path):
    print(f"downloading {url}", flush=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(tmp, dst)


def install_jplag(dest: Path):
    jar = dest / "jplag.jar"
    if not jar.exists():
        fetch(f"https://github.com/jplag/JPlag/releases/download/v{JPLAG_VERSION}/jplag-{JPLAG_VERSION}-jar-with-dependencies.jar", jar)
    if java_exe(dest) is None:
        osname = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}[platform.system()]
        arch = {"AMD64": "x64", "x86_64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine(), "x64")
        ext = "zip" if osname == "windows" else "tar.gz"
        arc = dest / f"jre.{ext}"
        fetch(f"https://api.adoptium.net/v3/binary/latest/{JAVA_VERSION}/ga/{osname}/{arch}/jre/hotspot/normal/eclipse", arc)
        if ext == "zip":
            with zipfile.ZipFile(arc) as z:
                z.extractall(dest / "jdk")
        else:
            with tarfile.open(arc) as t:
                t.extractall(dest / "jdk", filter="data")
        arc.unlink()
    print("JPlag ready", flush=True)


def install_scancode(dest: Path, source: str | None):
    if scancode_exe(dest).exists():
        print("ScanCode already installed", flush=True)
        return
    if not venv_python(dest).exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(dest / "venv")])
    target = "scancode-toolkit-mini"
    if source:
        src = Path(source).expanduser()
        if not src.exists():
            raise SystemExit(f"ScanCode source not found: {src}")
        if src.suffix.lower() == ".zip":
            # Extract into its own empty folder; the package is then built from there.
            out = dest / "scancode-src"
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            with zipfile.ZipFile(src) as z:
                z.extractall(out)
            roots = [p for p in out.iterdir() if p.is_dir()]
            target = str(roots[0] if len(roots) == 1 else out)
        else:
            target = str(src)
    print(f"installing ScanCode from {target}", flush=True)
    py = str(venv_python(dest))
    subprocess.check_call([py, "-m", "pip", "install", "--progress-bar", "off", target])
    # Development sources split the license data into a separate package (licensedcode-data) that the main
    # package doesn't pull in. Build it from the same source so no large download is needed.
    data_toml = Path(target) / "pyproject-licensedcode-data.toml"
    if data_toml.exists():
        print("building licensedcode-data from the same source", flush=True)
        subprocess.check_call([py, "-m", "pip", "install", "-q", "flot"])
        out = dest / "scancode-data-wheel"
        subprocess.check_call([py, "-m", "flot", "--pyproject", data_toml.name, "--wheel", "--output-dir", str(out)], cwd=target)
        subprocess.check_call([py, "-m", "pip", "install", "--no-deps", *map(str, out.glob("licensedcode_data-*.whl"))])
    print("ScanCode ready", flush=True)


def run_install(dest: Path, jplag: bool, scancode: bool, source: str | None) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    lock = dest / "install.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 3 * 3600:
            print("another add-on install is running; see install.log")
            return 0
        lock.unlink()
        return run_install(dest, jplag, scancode, source)
    failed = []
    try:
        for name, wanted, fn in (("jplag", jplag, lambda: install_jplag(dest)),
                                 ("scancode", scancode, lambda: install_scancode(dest, source))):
            if not wanted:
                continue
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - report and continue with the next add-on
                failed.append(name)
                print(f"{name} install FAILED: {e}", flush=True)
    finally:
        lock.unlink(missing_ok=True)
    (dest / "status.json").write_text(json.dumps({**status(dest), "failed": failed, "ts": time.time()}, indent=2), encoding="utf-8")
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", default=None)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--jplag", action="store_true")
    ap.add_argument("--scancode", action="store_true")
    ap.add_argument("--scancode-source")
    ap.add_argument("--from-plugin-options", action="store_true")
    ap.add_argument("--background", action="store_true")
    args = ap.parse_args(argv)
    dest = Path(args.dest) if args.dest else default_dest()

    if args.status:
        print(json.dumps(status(dest), indent=2))
        return 0
    jplag, scancode, source = args.jplag, args.scancode, args.scancode_source
    if args.from_plugin_options:
        jplag = truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_INSTALL_JPLAG", "true"))
        scancode = truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_INSTALL_SCANCODE", "true"))
        source = os.environ.get("CLAUDE_PLUGIN_OPTION_SCANCODE_SOURCE") or None
    st = status(dest)
    jplag = jplag and not st["jplag"]
    scancode = scancode and not st["scancode"]
    if not (jplag or scancode):
        if not args.from_plugin_options:
            print("nothing to install: " + json.dumps(st))
        return 0
    if args.background:
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(Path(__file__).resolve()), "--dest", str(dest)]
        cmd += ["--jplag"] if jplag else []
        cmd += ["--scancode"] if scancode else []
        cmd += ["--scancode-source", source] if source else []
        log = open(dest / "install.log", "a", encoding="utf-8")
        flags = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **flags)
        names = [n for n, w in (("JPlag", jplag), ("ScanCode", scancode)) if w]
        print(f"cleanroom: installing add-ons in the background ({', '.join(names)}); log: {dest / 'install.log'}")
        return 0
    return run_install(dest, jplag, scancode, source)


if __name__ == "__main__":
    sys.exit(main())
