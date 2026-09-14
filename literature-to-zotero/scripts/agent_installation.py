"""Agent destinations shared by installation and verification.

Only explicitly selected or already present runtimes receive an installation.
Shared/Hermes locations are recognized for externally installed skills, but are
not silently populated by this installer.
"""
from __future__ import annotations

import os
from pathlib import Path

AGENTS = {"codex": ".codex", "claude-code": ".claude", "pi": ".pi/agent"}
CHOICES = ("auto", *AGENTS, "all")
SKILL_NAME = "literature-to-zotero"


def agent_roots(home: Path | None = None) -> dict[str, Path]:
    use_environment = home is None
    home = home if home is not None else Path.home()
    roots = {name: home / path / "skills" for name, path in AGENTS.items()}
    # Explicit home injection is isolated from the caller's custom runtime.
    if use_environment:
        if os.environ.get("CODEX_HOME"):
            roots["codex"] = Path(os.environ["CODEX_HOME"]).expanduser() / "skills"
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            roots["claude-code"] = Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser() / "skills"
    return roots


def selected_roots(agent: str = "auto") -> list[Path]:
    roots = agent_roots()
    if agent not in CHOICES:
        raise ValueError(f"未知安装目标：{agent}")
    if agent == "all":
        return list(roots.values())
    if agent != "auto":
        return [roots[agent]]
    return [root for root in roots.values() if root.parent.is_dir()]


def installed_paths(home: Path | None = None, agent: str = "auto") -> list[str]:
    from install import runtime_ready
    if agent not in CHOICES:
        raise ValueError(f"未知安装目标：{agent}")
    roots = agent_roots(home)
    if agent in AGENTS:
        candidates = [roots[agent]]
    else:
        base = home if home is not None else Path.home()
        candidates = list(roots.values()) + [base / ".agents/skills", base / ".hermes/skills"]
    return [str(root / SKILL_NAME) for root in candidates
            if runtime_ready(root / SKILL_NAME, (home / '.local/share/literature-to-zotero/skill') if home else None)]


def installation_ok(agent: str = "auto") -> bool:
    if agent == "all":
        return all(installed_paths(agent=name) for name in AGENTS)
    return bool(installed_paths(agent=agent))
