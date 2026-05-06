"""Utility helpers for APM dependency commands."""

import json
from pathlib import Path
from typing import Any, Dict  # noqa: F401, UP035

from ...constants import APM_DIR, APM_YML_FILENAME, SKILL_MD_FILENAME
from ...core.scope import InstallScope, ensure_user_dirs, get_modules_dir
from ...models.apm_package import APMPackage
from ...utils.yaml_io import load_yaml


def _scan_installed_packages(apm_modules_dir: Path) -> list:
    """Scan *apm_modules_dir* for installed package paths.

    Walks the tree to find directories containing ``apm.yml`` or ``.apm``,
    supporting GitHub (2-level), ADO (3-level), and subdirectory packages.

    Returns:
        List of ``"owner/repo"`` or ``"org/project/repo"`` path keys.
    """
    installed: list = []
    if not apm_modules_dir.exists():
        return installed
    for candidate in apm_modules_dir.rglob("*"):
        if not candidate.is_dir() or candidate.name.startswith("."):
            continue
        if not ((candidate / APM_YML_FILENAME).exists() or (candidate / APM_DIR).exists()):
            continue
        rel_parts = candidate.relative_to(apm_modules_dir).parts
        if len(rel_parts) >= 2:
            installed.append("/".join(rel_parts))
    return installed


def _scan_installed_package_paths(apm_modules_dir: Path) -> list[Path]:
    """Scan *apm_modules_dir* for installed package root directories."""
    installed: list[Path] = []
    if not apm_modules_dir.exists():
        return installed

    for candidate in sorted(apm_modules_dir.rglob("*")):
        if not candidate.is_dir() or candidate.name.startswith("."):
            continue

        has_apm_yml = (candidate / APM_YML_FILENAME).exists()
        has_skill_md = (candidate / SKILL_MD_FILENAME).exists()
        if not has_apm_yml and not has_skill_md:
            continue

        rel_parts = candidate.relative_to(apm_modules_dir).parts
        if len(rel_parts) < 2:
            continue

        if ".apm" in rel_parts:
            continue

        if has_skill_md and not has_apm_yml and _is_nested_under_package(candidate, apm_modules_dir):
            continue

        installed.append(candidate)
    return installed


def _get_package_bp_id(package_path: Path, apm_modules_dir: Path | None = None) -> str:
    """Return the package bpId from apm.yml, or a fallback identifier."""
    apm_yml_path = package_path / APM_YML_FILENAME
    if apm_yml_path.exists():
        try:
            data = load_yaml(apm_yml_path)
            if isinstance(data, dict) and isinstance(data.get("bpId"), str):
                return data["bpId"]
        except Exception:
            pass

    if apm_modules_dir is not None:
        try:
            return package_path.relative_to(apm_modules_dir).as_posix()
        except Exception:
            pass

    return package_path.name


def _get_package_primitives(package_path: Path) -> dict[str, list[str]]:
    """Return primitive names grouped by type for a package.
    
    Scans for primitives that will be deployed to Cline.
    """
    primitives = {"skills": [], "rules": [], "workflows": [], "hooks": []}
    apm_dir = package_path / APM_DIR

    if apm_dir.exists():
        # Skills: .apm/skills/<name>/SKILL.md
        skills_path = apm_dir / "skills"
        if skills_path.exists() and skills_path.is_dir():
            for child in sorted(skills_path.iterdir()):
                if child.is_dir() and (child / SKILL_MD_FILENAME).exists():
                    primitives["skills"].append(child.name)

        # Rules/Instructions: .apm/instructions/*.instructions.md
        instructions_path = apm_dir / "instructions"
        if instructions_path.exists() and instructions_path.is_dir():
            for instruction_file in sorted(instructions_path.glob("*.instructions.md")):
                primitives["rules"].append(instruction_file.stem)

        # Workflows/Agents: .apm/agents/*.agent.md
        agents_path = apm_dir / "agents"
        if agents_path.exists() and agents_path.is_dir():
            for agent_file in sorted(agents_path.glob("*.agent.md")):
                primitives["workflows"].append(agent_file.stem)

        # Hooks in .apm/hooks/*.json
        hooks_path = apm_dir / "hooks"
        if hooks_path.exists() and hooks_path.is_dir():
            for hook_file in sorted(hooks_path.glob("*.json")):
                hook_name = hook_file.stem
                if hook_name not in primitives["hooks"]:
                    primitives["hooks"].append(hook_name)

    # Root-level SKILL.md
    if (package_path / SKILL_MD_FILENAME).exists():
        skill_name = package_path.name
        if skill_name not in primitives["skills"]:
            primitives["skills"].append(skill_name)

    # Root-level hooks/*.json
    hooks_root = package_path / "hooks"
    if hooks_root.exists() and hooks_root.is_dir():
        for hook_file in sorted(hooks_root.glob("*.json")):
            hook_name = hook_file.stem
            if hook_name not in primitives["hooks"]:
                primitives["hooks"].append(hook_name)

    return primitives


def _build_scope_primitives(package_paths: list[Path], apm_modules_dir: Path) -> dict[str, dict[str, str]]:
    """Build a JSON-friendly primitive map for a scope."""
    result = {"skills": {}, "rules": {}, "workflows": {}, "hooks": {}}
    for package_path in package_paths:
        bp_id = _get_package_bp_id(package_path, apm_modules_dir)
        package_primitives = _get_package_primitives(package_path)
        for primitive_type, names in package_primitives.items():
            for name in names:
                if name not in result[primitive_type]:
                    result[primitive_type][name] = bp_id
    return result


def _workspace_key(project_root: Path) -> str:
    """Compute the workspace key from a project root or fallback to directory name."""
    try:
        apm_yml_path = project_root / APM_YML_FILENAME
        if apm_yml_path.exists():
            package = APMPackage.from_apm_yml(apm_yml_path)
            if package.name:
                return package.name
    except Exception:
        pass
    if project_root.name == "global":
        return f"workspace-{project_root.name}"
    return project_root.name


def _remove_from_primitives_snapshot(removed_packages: list[str], scope: InstallScope = InstallScope.PROJECT) -> Path:
    """Remove package entries from the primitives snapshot JSON.
    
    Args:
        removed_packages: List of package keys (e.g., "org/repo") to remove
        scope: PROJECT or USER scope
    
    Returns:
        Path to the updated JSON file
    """
    output_path = ensure_user_dirs() / "primitives.json"
    if not output_path.exists():
        return output_path
    
    try:
        snapshot = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict):
            return output_path
    except Exception:
        return output_path
    
    # Get the workspace key for this scope
    if scope is InstallScope.PROJECT:
        workspace_key = _workspace_key(Path.cwd())
    else:
        workspace_key = "global"
    
    # Remove primitives from packages that were uninstalled
    if workspace_key in snapshot:
        scope_data = snapshot[workspace_key]
        for primitive_type in ["skills", "rules", "workflows", "hooks"]:
            if primitive_type in scope_data:
                # Remove entries whose bpId matches removed packages
                to_remove = []
                for prim_name, bp_id in scope_data[primitive_type].items():
                    if bp_id in removed_packages:
                        to_remove.append(prim_name)
                for prim_name in to_remove:
                    del scope_data[primitive_type][prim_name]
    
    output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return output_path


def update_primitives_snapshot(project_root: Path | None = None) -> Path:
    """Write installed primitive metadata to ~/.apm/primitives.json."""
    output_path = ensure_user_dirs() / "primitives.json"
    snapshot: dict[str, Any] = {}
    if output_path.exists():
        try:
            snapshot = json.loads(output_path.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                snapshot = {}
        except Exception:
            snapshot = {}

    if project_root is not None:
        snapshot[_workspace_key(project_root)] = _build_scope_primitives(
            _scan_installed_package_paths(get_modules_dir(InstallScope.PROJECT)),
            get_modules_dir(InstallScope.PROJECT),
        )

    snapshot["global"] = _build_scope_primitives(
        _scan_installed_package_paths(get_modules_dir(InstallScope.USER)),
        get_modules_dir(InstallScope.USER),
    )

    output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return output_path


def _is_nested_under_package(candidate: Path, apm_modules_path: Path) -> bool:
    """Check if *candidate* is a sub-directory of another installed package.

    When a plugin ships ``skills/*/SKILL.md`` at its root (outside ``.apm/``),
    the ``rglob`` scan would otherwise treat each skill sub-directory as an
    independent package.  This helper walks up from *candidate* towards
    *apm_modules_path* and returns ``True`` if any intermediate parent already
    contains ``apm.yml``  -- meaning the candidate is a deployment artifact, not
    a standalone package.
    """
    parent = candidate.parent
    while parent != apm_modules_path and parent != parent.parent:  # noqa: PLR1714
        if (parent / APM_YML_FILENAME).exists():
            return True
        parent = parent.parent
    return False


def _count_primitives(package_path: Path) -> dict[str, int]:
    """Count primitives by type in a package.

    Returns:
        dict: Counts for 'prompts', 'instructions', 'agents', 'skills'
    """
    counts = {"prompts": 0, "instructions": 0, "agents": 0, "skills": 0, "hooks": 0}

    apm_dir = package_path / APM_DIR
    if apm_dir.exists():
        for subdir, key, pattern in [
            ("prompts", "prompts", "*.prompt.md"),
            ("instructions", "instructions", "*.md"),
            ("agents", "agents", "*.md"),
        ]:
            path = apm_dir / subdir
            if path.exists() and path.is_dir():
                counts[key] += len(list(path.glob(pattern)))

        skills_path = apm_dir / "skills"
        if skills_path.exists() and skills_path.is_dir():
            counts["skills"] += len(
                [
                    d
                    for d in skills_path.iterdir()
                    if d.is_dir() and (d / SKILL_MD_FILENAME).exists()
                ]
            )

    # Also count root-level .prompt.md files
    counts["prompts"] += len(list(package_path.glob("*.prompt.md")))

    # Count root-level SKILL.md as a skill
    if (package_path / SKILL_MD_FILENAME).exists():
        counts["skills"] += 1

    # Count hooks (.json files in hooks/ or .apm/hooks/)
    for hooks_dir in [package_path / "hooks", apm_dir / "hooks" if apm_dir.exists() else None]:
        if hooks_dir and hooks_dir.exists() and hooks_dir.is_dir():
            counts["hooks"] += len(list(hooks_dir.glob("*.json")))

    return counts


def _count_package_files(package_path: Path) -> tuple[int, int]:
    """Count context files and workflows in a package.

    Returns:
        tuple: (context_count, workflow_count)
    """
    apm_dir = package_path / APM_DIR
    if not apm_dir.exists():
        # Also check root directory for .prompt.md files
        workflow_count = len(list(package_path.glob("*.prompt.md")))
        return 0, workflow_count

    context_count = 0
    context_dirs = ["instructions", "chatmodes", "context"]

    for context_dir in context_dirs:
        context_path = apm_dir / context_dir
        if context_path.exists() and context_path.is_dir():
            context_count += len(list(context_path.glob("*.md")))

    # Count workflows in both .apm/prompts and root directory
    workflow_count = 0
    prompts_path = apm_dir / "prompts"
    if prompts_path.exists() and prompts_path.is_dir():
        workflow_count += len(list(prompts_path.glob("*.prompt.md")))

    # Also check root directory for .prompt.md files
    workflow_count += len(list(package_path.glob("*.prompt.md")))

    return context_count, workflow_count


def _count_workflows(package_path: Path) -> int:
    """Count agent workflows (.prompt.md files) in a package."""
    _, workflow_count = _count_package_files(package_path)
    return workflow_count


def _get_detailed_context_counts(package_path: Path) -> dict[str, int]:
    """Get detailed context file counts by type."""
    apm_dir = package_path / APM_DIR
    if not apm_dir.exists():
        return {"instructions": 0, "chatmodes": 0, "contexts": 0}

    counts = {}
    context_directories = {
        "instructions": "instructions",
        "chatmodes": "chatmodes",
        "contexts": "context",  # Note: directory is 'context', not 'contexts'
    }

    for context_type, directory_name in context_directories.items():
        count = 0
        context_path = apm_dir / directory_name
        if context_path.exists() and context_path.is_dir():
            # Count all .md files in the directory regardless of specific naming
            count = len(list(context_path.glob("*.md")))
        counts[context_type] = count

    return counts


def _get_package_display_info(package_path: Path) -> dict[str, str]:
    """Get package display information."""
    try:
        apm_yml_path = package_path / APM_YML_FILENAME
        if apm_yml_path.exists():
            package = APMPackage.from_apm_yml(apm_yml_path)
            version_info = f"@{package.version}" if package.version else "@unknown"
            return {
                "display_name": f"{package.name}{version_info}",
                "name": package.name,
                "version": package.version or "unknown",
            }
        else:
            return {
                "display_name": f"{package_path.name}@unknown",
                "name": package_path.name,
                "version": "unknown",
            }
    except Exception:
        return {
            "display_name": f"{package_path.name}@error",
            "name": package_path.name,
            "version": "error",
        }


def _get_detailed_package_info(package_path: Path) -> dict[str, Any]:
    """Get detailed package information for the info command."""
    try:
        apm_yml_path = package_path / APM_YML_FILENAME
        if apm_yml_path.exists():
            package = APMPackage.from_apm_yml(apm_yml_path)
            context_count, workflow_count = _count_package_files(package_path)
            primitives = _count_primitives(package_path)
            # HYBRID-aware description rendering: when apm.yml omits its
            # tagline but a SKILL.md sits alongside, surface the empty
            # apm.yml.description as `--` plus an inline annotation. The
            # SKILL.md description is intentionally NOT borrowed -- it is
            # an agent invocation matcher, not a human tagline.
            is_hybrid = (package_path / "SKILL.md").exists()
            if package.description:
                desc = package.description
            elif is_hybrid:
                desc = (
                    "--  (set 'description' in apm.yml; SKILL.md description is for agent runtime)"
                )
            else:
                desc = "No description"
            return {
                "name": package.name,
                "version": package.version or "unknown",
                "description": desc,
                "author": package.author or "Unknown",
                "source": package.source or "local",
                "install_path": str(package_path.resolve()),
                "context_files": _get_detailed_context_counts(package_path),
                "workflows": workflow_count,
                "hooks": primitives.get("hooks", 0),
            }
        else:
            context_count, workflow_count = _count_package_files(package_path)  # noqa: RUF059
            primitives = _count_primitives(package_path)
            return {
                "name": package_path.name,
                "version": "unknown",
                "description": "No apm.yml found",
                "author": "Unknown",
                "source": "unknown",
                "install_path": str(package_path.resolve()),
                "context_files": _get_detailed_context_counts(package_path),
                "workflows": workflow_count,
                "hooks": primitives.get("hooks", 0),
            }
    except Exception as e:
        return {
            "name": package_path.name,
            "version": "error",
            "description": f"Error loading package: {e}",
            "author": "Unknown",
            "source": "unknown",
            "install_path": str(package_path.resolve()),
            "context_files": {"instructions": 0, "chatmodes": 0, "contexts": 0},
            "workflows": 0,
            "hooks": 0,
        }
