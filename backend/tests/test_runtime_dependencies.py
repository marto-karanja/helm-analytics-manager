"""The production image installs without the dev group (`uv sync --no-dev`). Code that imports a dev-only package
passes every test and then crashes at start-up in the container, so fail here instead."""
import ast
import importlib.metadata as metadata
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[ ]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def test_app_code_imports_nothing_that_only_the_dev_group_installs():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = {_name(r) for r in config["project"]["dependencies"]}
    dev_only = {_name(r) for r in config["dependency-groups"]["dev"]} - runtime
    modules_of = {dist: {m for m, dists in metadata.packages_distributions().items() if dist in {d.lower().replace("_", "-") for d in dists}} for dist in dev_only}
    forbidden = {m: dist for dist, mods in modules_of.items() for m in mods}

    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            for name in names:
                top = name.split(".")[0]
                if top in forbidden:
                    offenders.append(f"{path.relative_to(ROOT)} imports {top} (dev-only package {forbidden[top]})")
    assert not offenders, offenders


def test_httpx_is_a_runtime_dependency():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "httpx" in {_name(r) for r in config["project"]["dependencies"]}
