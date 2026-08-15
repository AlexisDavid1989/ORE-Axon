"""Audit which files in the Engine repo no chunk claims.

The original chunk map silently omitted `ql/processes`, every top-level
`ql/*.hpp`, `Examples/`, `ORE-SWIG/`, `Tools/` and all the test suites. Nothing
reported it, because a chunk map has no natural notion of "the rest". This
command is that notion: run it after any ORE upgrade and it will tell you what
moved out from under the map.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .chunks import ALL_CHUNKS, Chunk

CODE_EXTS = {".hpp", ".h", ".hxx", ".hh", ".inl", ".ipp", ".cpp", ".cc",
             ".cxx", ".c", ".py", ".ipynb", ".i", ".java"}
DATA_EXTS = {".xml", ".csv", ".xsd", ".tex", ".md", ".json", ".txt"}

IGNORE_DIRS = {".git", ".vs", "build", "node_modules", "__pycache__",
               ".github", "ThirdPartyLibs", "cmake", "Docker", ".graphify", ".ci"}

#: Project scaffolding: build config, licenses, changelogs, generated files.
#: No architectural signal, so `coverage` shouldn't ask for a chunk to claim
#: them. Matched case-insensitively against the file's basename.
IGNORE_FILENAMES = {
    "cmakelists.txt", "cmakepresets.json", "license.txt", "license",
    "licenseheader.txt", "changelog.txt", "news.txt", "news.md",
    "readme.md", "contributing.md", "contributors.txt", ".mcp.json",
    "version_number.txt", ".lsan.txt", "doxy-coverage.py",
}

#: Paths deliberately left out of the chunk map - a judgment call, not an
#: oversight. Each is a directory prefix or exact file, relative to the
#: Engine repo, matched on posix-style path segments (not a substring match,
#: so "tutorials" cannot accidentally swallow "tutorials_index.md"). Reported
#: separately by `format_report()` so `coverage` stays honest: these are not
#: claimed by any chunk and never will be, on purpose.
EXCLUDED: tuple[tuple[str, str], ...] = (
    ("Configurations/SIMM",
     "SIMM calibration XMLs (risk weights, bucket correlations) - no "
     "architectural signal; the code that consumes them is already covered "
     "in OREAnalytics' SIMM communities."),
    ("tutorials",
     "Engine-repo-root onboarding docs - build/install instructions, no "
     "architectural signal."),
    ("tutorials_index.md",
     "Index page for the tutorials/ directory above - same reasoning."),
    ("ORE-SWIG/tutorials.00.index.md", "SWIG install/build tutorial - build instructions."),
    ("ORE-SWIG/tutorials.01.install_windows.md", "SWIG install/build tutorial - build instructions."),
    ("ORE-SWIG/tutorials.02.install_posix.md", "SWIG install/build tutorial - build instructions."),
    ("ORE-SWIG/tutorials.03.build_windows.md", "SWIG install/build tutorial - build instructions."),
    ("ORE-SWIG/tutorials.04.build_posix.md", "SWIG install/build tutorial - build instructions."),
    ("ORE-SWIG/tutorials.06.notebooks.md", "SWIG install/build tutorial - build instructions."),
    ("ORE-SWIG/Docs/ore-swig.tex", "SWIG doc source - marginal architectural signal."),
)


def _excluded_reason(rel_posix: str) -> str | None:
    for prefix, reason in EXCLUDED:
        if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
            return reason
    return None


def _claimed(engine: Path, chunks: tuple[Chunk, ...]) -> set[Path]:
    out: set[Path] = set()
    for c in chunks:
        for p in c.resolve(engine):
            if p.is_file():
                out.add(p.resolve())
            else:
                for f in p.rglob("*"):
                    if f.is_file():
                        out.add(f.resolve())
    return out


def audit(engine: Path, chunks: tuple[Chunk, ...] = ALL_CHUNKS) -> dict:
    claimed = _claimed(engine, chunks)

    unclaimed_code: Counter = Counter()
    unclaimed_data: Counter = Counter()
    excluded_by_reason: Counter = Counter()
    n_code = n_data = n_excluded = 0
    for f in engine.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(engine)
        parts = set(rel.parts)
        if parts & IGNORE_DIRS:
            continue
        if f.resolve() in claimed:
            continue
        if f.name.lower() in IGNORE_FILENAMES:
            continue
        reason = _excluded_reason(rel.as_posix())
        if reason:
            excluded_by_reason[reason] += 1
            n_excluded += 1
            continue
        ext = f.suffix.lower()
        top = rel.parts[0]
        if ext in CODE_EXTS:
            unclaimed_code[top] += 1
            n_code += 1
        elif ext in DATA_EXTS:
            unclaimed_data[top] += 1
            n_data += 1

    return {
        "claimed_files": len(claimed),
        "unclaimed_code": n_code,
        "unclaimed_data": n_data,
        "unclaimed_code_by_dir": unclaimed_code.most_common(),
        "unclaimed_data_by_dir": unclaimed_data.most_common(),
        "excluded": n_excluded,
        "excluded_by_reason": excluded_by_reason.most_common(),
    }


def format_report(result: dict) -> str:
    lines = [
        f"Files claimed by the chunk map: {result['claimed_files']:,}",
        f"Unclaimed code files:           {result['unclaimed_code']:,}",
        f"Unclaimed data/doc files:       {result['unclaimed_data']:,}",
    ]
    if result["unclaimed_code_by_dir"]:
        lines.append("\nUnclaimed CODE by top-level dir:")
        for d, n in result["unclaimed_code_by_dir"]:
            lines.append(f"   {d:28s} {n:>6,}")
    if result["unclaimed_data_by_dir"]:
        lines.append("\nUnclaimed DATA/DOCS by top-level dir:")
        for d, n in result["unclaimed_data_by_dir"]:
            lines.append(f"   {d:28s} {n:>6,}")
    if not result["unclaimed_code"] and not result["unclaimed_data"]:
        lines.append("\nFull coverage - every file belongs to a chunk.")
    if result.get("excluded_by_reason"):
        lines.append(f"\nDeliberately excluded ({result['excluded']:,}, not in the graph on purpose):")
        for reason, n in result["excluded_by_reason"]:
            lines.append(f"   {n:>4,}  {reason}")
    return "\n".join(lines)
