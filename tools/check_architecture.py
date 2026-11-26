"""Check static Python imports against the project's declared package boundaries."""

from __future__ import annotations

import ast
import json
import os
import stat
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ".app-steward/architecture/modules.json"


def is_link(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def python_sources(root: Path):
    def raise_walk_error(error: OSError) -> None:
        raise error

    for folder, directories, files in os.walk(root, onerror=raise_walk_error, followlinks=False):
        base = Path(folder)
        directories[:] = [
            name for name in sorted(directories)
            if name != "__pycache__" and not is_link(base / name)
        ]
        for name in sorted(files):
            path = base / name
            if path.suffix == ".py" and not is_link(path):
                yield path


def check(root: Path, config: dict | None = None) -> tuple[int, dict[tuple[str, str], int], list[str]]:
    if config is None:
        config = json.loads((root / MAP).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("expected a module map object")
    modules = config.get("modules", [])
    if not isinstance(modules, list) or not modules:
        raise ValueError("no module boundaries declared")

    by_id: dict[str, dict] = {}
    by_package: dict[str, str] = {}
    for module in modules:
        module_id, package = module["id"], module["path"]
        if not isinstance(module_id, str) or not module_id or module_id in by_id:
            raise ValueError(f"invalid or duplicate module ID: {module_id}")
        if not isinstance(package, str) or not package.isidentifier() or package in by_package:
            raise ValueError(f"expected unique top-level Python directory: {package}")
        folder = root / package
        if not folder.is_dir() or is_link(folder):
            raise ValueError(f"module must be an existing local directory: {package}")
        if type(module.get("layer")) is not int:
            raise ValueError(f"expected integer layer: {module_id}")
        by_id[module_id] = module
        by_package[package] = module_id

    allowed: dict[str, set[str]] = {}
    for module_id, module in by_id.items():
        deps = module["dependencies"]
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise ValueError(f"expected dependency ID list: {module_id}")
        for dep in deps:
            if dep not in by_id or by_id[dep]["layer"] >= module["layer"]:
                raise ValueError(f"{module_id} -> {dep}: expected a known, lower layer")
        allowed[module_id] = set(deps)

    legacy: dict[tuple[str, str], str] = {}
    for entry in config.get("legacy_imports", []):
        source, name, gap = entry["source"], entry["import"], entry["gap"]
        owner = by_package.get(source.partition("/")[0])
        target = by_package.get(name.partition(".")[0])
        key = (source, name)
        if not owner or not target or owner == target or target in allowed[owner] or not gap or key in legacy:
            raise ValueError(f"invalid legacy import entry: {entry}")
        legacy[key] = gap

    seen_legacy: set[tuple[str, str]] = set()
    count = 0
    edges: dict[tuple[str, str], int] = {}
    violations: list[str] = []
    for package, owner in sorted(by_package.items()):
        for path in python_sources(root / package):
            count += 1
            rel = path.relative_to(root).as_posix()
            with tokenize.open(path) as source:
                tree = ast.parse(source.read(), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue  # Relative imports stay within the owning top-level package.
                for name in names:
                    target = by_package.get(name.partition(".")[0])
                    if target is None or target == owner:
                        continue
                    edge = (owner, target)
                    edges[edge] = edges.get(edge, 0) + 1
                    if target not in allowed[owner]:
                        key = (rel, name)
                        if key in legacy:
                            seen_legacy.add(key)
                        else:
                            violations.append(f"{rel}:{node.lineno}: {owner} -> {target} is not declared")
    for rel, name in sorted(legacy.keys() - seen_legacy):
        violations.append(f"{rel}: stale legacy import for {name}; remove the entry ({legacy[rel, name]})")
    return count, edges, sorted(set(violations))


def main() -> int:
    try:
        config = json.loads((ROOT / MAP).read_text(encoding="utf-8"))
        count, edges, violations = check(ROOT, config)
    except (OSError, KeyError, TypeError, ValueError, SyntaxError) as exc:
        print(f"Architecture check could not run: {exc}")
        return 2
    for (owner, target), imports in sorted(edges.items()):
        print(f"{owner} -> {target}: {imports} import(s)")
    for entry in config.get("legacy_imports", []):
        print(f"Legacy edge ({entry['gap']}): {entry['source']} imports {entry['import']}")
    for violation in violations:
        print(violation)
    print(f"Architecture: {'FAIL' if violations else 'PASS'} ({count} Python files, {len(edges)} package edges)")
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
