"""Workflow integration functionality for APM packages.

Deploys workflow files from APM packages to the appropriate
target directory. Currently only Cline supports workflows,
which are deployed to:
- Project scope: .clinerules/workflows/
- User scope: ~/Documents/Cline/Workflows/

Workflows are markdown files that define reusable task workflows
for AI assistants. They are discovered from:
- .apm/workflows/ subdirectory
- workflows/ subdirectory (no .apm prefix)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from apm_cli.integration.base_integrator import BaseIntegrator, IntegrationResult
from apm_cli.utils.paths import portable_relpath

if TYPE_CHECKING:
    from apm_cli.integration.targets import TargetProfile


class WorkflowIntegrator(BaseIntegrator):
    """Handles integration of APM package workflows.

    Workflows are markdown files that define reusable task workflows.
    Currently only Cline supports this primitive.
    """

    def find_workflow_files(self, package_path: Path) -> list[Path]:
        """Find all workflow files in a package.

        Searches in:
        - .apm/workflows/ subdirectory
        - workflows/ subdirectory (no .apm prefix)

        Args:
            package_path: Path to the package directory

        Returns:
            List[Path]: List of absolute paths to workflow files
        """
        workflow_files = []

        # Search in .apm/workflows/
        apm_workflows = package_path / ".apm" / "workflows"
        if apm_workflows.exists():
            for md_file in apm_workflows.rglob("*.md"):
                workflow_files.append(md_file)

        # Search in workflows/ (no .apm prefix)
        workflows_dir = package_path / "workflows"
        if workflows_dir.exists():
            for md_file in workflows_dir.rglob("*.md"):
                if md_file not in workflow_files:
                    workflow_files.append(md_file)

        return workflow_files

    def copy_workflow(self, source: Path, target: Path) -> int:
        """Copy workflow file with link resolution.

        Args:
            source: Source file path
            target: Target file path

        Returns:
            int: Number of links resolved
        """
        content = source.read_text(encoding="utf-8")
        content, links_resolved = self.resolve_links(content, source, target)
        target.write_text(content, encoding="utf-8")
        return links_resolved

    # ------------------------------------------------------------------
    # Target-driven API (data-driven dispatch)
    # ------------------------------------------------------------------

    def integrate_workflows_for_target(
        self,
        target: TargetProfile,
        package_info,
        project_root: Path,
        *,
        force: bool = False,
        managed_files: set = None,  # noqa: RUF013
        diagnostics=None,
    ) -> IntegrationResult:
        """Integrate workflows for a single *target*.

        Currently only Cline supports workflows. The target profile
        defines the deployment directory via the PrimitiveMapping.
        """
        mapping = target.primitives.get("workflows")
        if not mapping:
            return IntegrationResult(0, 0, 0, [])

        effective_root = mapping.deploy_root or target.root_dir
        target_root = project_root / effective_root
        
        # Cline global/user-scope routes workflows to ~/Documents/Cline/Workflows
        # (or ~/Cline/Workflows on Linux fallback).
        if target.name == "cline" and target.resolved_deploy_root is not None:
            target_root = target.resolved_deploy_root / "Workflows"
        
        if not target.auto_create and not (project_root / target.root_dir).is_dir():
            return IntegrationResult(0, 0, 0, [])

        self.init_link_resolver(package_info, project_root)
        workflow_files = self.find_workflow_files(package_info.install_path)
        
        if not workflow_files:
            return IntegrationResult(0, 0, 0, [])

        workflows_subdir = mapping.subdir if mapping.subdir else ""
        workflows_dir = target_root / workflows_subdir if workflows_subdir else target_root
        workflows_dir.mkdir(parents=True, exist_ok=True)

        files_integrated = 0
        files_skipped = 0
        target_paths: list[Path] = []
        total_links_resolved = 0

        for source_file in workflow_files:
            # Use the source filename with the target extension
            target_filename = source_file.stem + mapping.extension
            target_path = workflows_dir / target_filename
            rel_path = portable_relpath(target_path, project_root)

            if self.check_collision(
                target_path,
                rel_path,
                managed_files,
                force,
                diagnostics=diagnostics,
            ):
                files_skipped += 1
                continue

            links_resolved = self.copy_workflow(source_file, target_path)
            total_links_resolved += links_resolved
            files_integrated += 1
            target_paths.append(target_path)

        return IntegrationResult(
            files_integrated=files_integrated,
            files_updated=0,
            files_skipped=files_skipped,
            target_paths=target_paths,
            links_resolved=total_links_resolved,
        )

    def sync_for_target(
        self,
        target: TargetProfile,
        apm_package,
        project_root: Path,
        managed_files: set = None,  # noqa: RUF013
    ) -> dict[str, int]:
        """Remove APM-managed workflow files for a single *target*."""
        mapping = target.primitives.get("workflows")
        if not mapping:
            return {"files_removed": 0, "errors": 0}
        
        effective_root = mapping.deploy_root or target.root_dir
        prefix = f"{effective_root}/{mapping.subdir}/" if mapping.subdir else f"{effective_root}/"
        legacy_dir = project_root / effective_root / mapping.subdir if mapping.subdir else project_root / effective_root
        
        if target.name == "cline" and target.resolved_deploy_root is not None:
            workflows_dir = target.resolved_deploy_root / "Workflows"
            home_rel = workflows_dir.relative_to(Path.home())
            prefix = f"{home_rel.as_posix()}/"
            legacy_dir = workflows_dir
        
        legacy_pattern = "*-apm.md"
        return self.sync_remove_files(
            project_root,
            managed_files,
            prefix=prefix,
            legacy_glob_dir=legacy_dir,
            legacy_glob_pattern=legacy_pattern,
            targets=[target],
        )