"""Shared helpers for cleanroom scripts. Standard library only."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

STATE_DIRNAME = ".cleanroom"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "upstream": None,
    "harness": None,
    "languages": [],
    "test_command": None,
    "upstream_name": None,
    "project_name": None,
    "analyzer_model": "opus",
    "builder_model": "sonnet",
    "test_writer_model": "sonnet",
    "max_build_attempts": 3,
    "modules": {},
    "thresholds": {
        # k = 9 normalized tokens, the same minimum match length JPlag uses by default. Smaller k
        # makes common idioms (def f(a, b=""):, raise X(...)) collide in independently written code.
        "k": 9,
        "window": 4,
        "tainted_token_overlap": 0.30,
        "mixed_token_overlap": 0.10,
        "verify_max_overlap": 0.15,
        "jplag_max_similarity": 0.30,
        "nontrivial_string_len": 12,
        "comment_block_len": 30,
        "spec_max_literal_len": 20,
        "spec_verbatim_words": 8,
    },
    "exclude": [".git", ".cleanroom", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".pytest_cache"],
}

CODE_EXTS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".scala", ".sh", ".bash", ".lua",
}
TEXT_EXTS = CODE_EXTS | {".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".xml", ".html", ".css"}


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_text(path: Path) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def find_state_dir(start: Path | None = None) -> Path:
    """Locate .cleanroom/ from an explicit harness, $CLEANROOM_HARNESS, or by walking up from cwd."""
    env = os.environ.get("CLEANROOM_HARNESS")
    if start is None and env:
        start = Path(env)
    start = Path(start or os.getcwd()).resolve()
    for p in [start, *start.parents]:
        if (p / STATE_DIRNAME / "config.json").exists():
            return p / STATE_DIRNAME
    return start / STATE_DIRNAME


def load_config(state: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    user = read_json(state / "config.json", {}) or {}
    thresholds = {**cfg["thresholds"], **user.get("thresholds", {})}
    cfg.update(user)
    cfg["thresholds"] = thresholds
    return cfg


def iter_files(root: Path, exclude: list[str], exts: set[str] | None = None):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            if exts is None or p.suffix.lower() in exts or (exts is TEXT_EXTS and name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "README", "PATENTS"))):
                yield p


def rel(path: Path, root: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def run(cmd: list[str], cwd: Path | None = None, check: bool = False, env: dict | None = None, timeout: int | None = None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check, env=env, timeout=timeout)


def tools_dirs(cfg: dict | None = None) -> list[Path]:
    """Where add-ons (JPlag, Java, ScanCode) may be installed, most specific first.

    $CLAUDE_PLUGIN_DATA is only exported to hooks, not to commands Claude runs, so the plugin's
    data folder is also found by globbing ~/.claude/plugins/data/ (the add-on hook installs there).
    """
    out = []
    if cfg and cfg.get("tools_dir"):
        out.append(Path(cfg["tools_dir"]))
    if os.environ.get("CLAUDE_PLUGIN_DATA"):
        out.append(Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "tools")
    out += sorted((Path.home() / ".claude" / "plugins" / "data").glob("cleanroom*/tools"))
    out += [PLUGIN_ROOT / ".tools", PLUGIN_ROOT.parent / ".tools"]
    return out


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)
