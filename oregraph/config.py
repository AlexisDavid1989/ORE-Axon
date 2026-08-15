"""Path and environment resolution.

Everything the pipeline needs to know about *this machine* is resolved here so
no other module contains a machine-specific path. Resolution order for every
setting is: explicit CLI flag > environment variable > oregraph.toml > autodetect.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:  # py311+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11
    tomllib = None

PKG_ROOT = Path(__file__).resolve().parent.parent

# Directories that must exist directly under a path for it to be the ORE Engine repo.
ENGINE_MARKERS = ("OREData", "OREAnalytics", "QuantExt", "QuantLib")


class ConfigError(RuntimeError):
    pass


def _read_toml() -> dict:
    path = PKG_ROOT / "oregraph.toml"
    if not path.exists() or tomllib is None:
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _looks_like_engine(path: Path) -> bool:
    return path.is_dir() and all((path / m).is_dir() for m in ENGINE_MARKERS)


def _autodetect_engine() -> Path | None:
    """Walk up from cwd, then try siblings of this package."""
    for base in (Path.cwd(), PKG_ROOT):
        for candidate in (base, *base.parents):
            if _looks_like_engine(candidate):
                return candidate
            sibling = candidate / "Engine"
            if _looks_like_engine(sibling):
                return sibling
    return None


def _default_out_dir() -> Path:
    """A writable cache dir that is NOT inside a cloud-synced folder.

    Graph builds write hundreds of MB of intermediate JSON. Putting that inside
    OneDrive/Dropbox makes every rebuild a sync storm, so the default lives in
    the OS cache location instead.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "ore-graphify"


SYNCED_MARKERS = ("onedrive", "dropbox", "google drive", "icloud", "box sync")


def warn_if_synced(path: Path) -> str | None:
    low = str(path).lower()
    for marker in SYNCED_MARKERS:
        if marker in low:
            return (
                f"WARNING: output dir is inside a cloud-synced folder ({marker}). "
                "Builds write hundreds of MB of intermediates; set ORE_GRAPH_OUT "
                "to a local path to avoid a sync storm."
            )
    return None


@dataclass(frozen=True)
class Config:
    engine: Path
    out: Path
    python: str
    graphify_cli: str | None
    package_root: Path = PKG_ROOT

    # ---- derived locations -------------------------------------------------
    @property
    def merged_graph(self) -> Path:
        return self.out / "merged" / "graph.json"

    @property
    def labels_dir(self) -> Path:
        return self.package_root / "labels"

    @property
    def semantic_chunks(self) -> Path:
        return self.package_root / "semantic-chunks"

    def module_out(self, name: str) -> Path:
        return self.out / name / "graphify-out"

    def module_graph(self, name: str) -> Path:
        return self.module_out(name) / "graph.json"

    def labels_for(self, name: str) -> Path | None:
        p = self.labels_dir / f"{name}.json"
        return p if p.exists() else None


def _resolve_graphify_cli() -> str | None:
    for name in ("graphify", "graphify.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def check_graphify_importable(python: str) -> bool:
    try:
        subprocess.run(
            [python, "-c", "import graphify"],
            check=True, capture_output=True, timeout=60,
        )
        return True
    except Exception:
        return False


def load(engine: str | None = None, out: str | None = None) -> Config:
    toml = _read_toml()
    paths = toml.get("paths", {})

    engine_raw = engine or os.environ.get("ORE_ENGINE") or paths.get("engine")
    engine_path = Path(engine_raw).expanduser().resolve() if engine_raw else _autodetect_engine()

    if engine_path is None:
        raise ConfigError(
            "Could not locate the ORE Engine repo.\n"
            "Set it one of these ways:\n"
            "  export ORE_ENGINE=/path/to/Engine     (Windows: set ORE_ENGINE=C:\\path\\to\\Engine)\n"
            "  or copy oregraph.toml.example to oregraph.toml and edit [paths].engine\n"
            "  or run this command from inside the Engine checkout."
        )
    if not _looks_like_engine(engine_path):
        missing = [m for m in ENGINE_MARKERS if not (engine_path / m).is_dir()]
        raise ConfigError(
            f"{engine_path} does not look like the ORE Engine repo "
            f"(missing: {', '.join(missing)})."
        )

    out_raw = out or os.environ.get("ORE_GRAPH_OUT") or paths.get("out")
    out_path = Path(out_raw).expanduser().resolve() if out_raw else _default_out_dir()

    return Config(
        engine=engine_path,
        out=out_path,
        python=sys.executable,
        graphify_cli=_resolve_graphify_cli(),
    )
