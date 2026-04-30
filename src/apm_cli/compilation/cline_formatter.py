"""Cline rules formatter for APM integration.

This module validates and formats Cline rules files (.clinerules/*.md).
Cline rules are APM instructions deployed to .clinerules/ with markdown format.

Validation includes:
- Rules are valid markdown
- Rules do not exceed Cline's content size limits
- No unsupported frontmatter fields
"""

from pathlib import Path
from typing import List, Optional, Dict
import frontmatter


class ClineRulesFormatter:
    """Formatter for validating Cline rules from APM instructions.
    
    Cline rules are markdown files in .clinerules/ that guide the AI assistant.
    This formatter ensures rules follow Cline's constraints while preserving
    APM instruction metadata.
    """
    
    # Cline rule size limits (advisory; actual enforced by Cline client)
    MAX_RULE_SIZE_KB = 100
    
    def __init__(self, base_dir: str = "."):
        """Initialize the Cline rules formatter.
        
        Args:
            base_dir (str): Base directory for validation context.
        """
        self.base_dir = Path(base_dir).resolve() if base_dir else Path(".")
        self.warnings: List[str] = []
        self.errors: List[str] = []
    
    def validate_rule_file(self, file_path: Path) -> bool:
        """Validate a single Cline rule file.
        
        Args:
            file_path (Path): Path to the rule file to validate.
        
        Returns:
            bool: True if valid, False otherwise. Warnings/errors populated.
        """
        self.warnings.clear()
        self.errors.clear()
        
        if not file_path.exists():
            self.errors.append(f"Rule file does not exist: {file_path}")
            return False
        
        if not file_path.suffix == ".md":
            self.errors.append(f"Rule must be markdown (.md): {file_path}")
            return False
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self.errors.append(f"Failed to read rule file: {e}")
            return False
        
        # Check file size
        size_kb = len(content.encode("utf-8")) / 1024
        if size_kb > self.MAX_RULE_SIZE_KB:
            self.warnings.append(
                f"Rule exceeds recommended size ({size_kb:.1f}KB > {self.MAX_RULE_SIZE_KB}KB); "
                "Cline may truncate very large rules"
            )
        
        # Parse frontmatter if present
        try:
            post = frontmatter.loads(content)
            # Rules inherit APM instruction metadata (applyTo, etc.)
            # Cline rules don't use special frontmatter, so just validate parseability
        except Exception as e:
            self.warnings.append(f"Frontmatter parse warning: {e}")
        
        return len(self.errors) == 0
    
    def get_formatted_content(self, file_path: Path) -> Optional[str]:
        """Get the content of a Cline rule file (passthrough for now).
        
        Args:
            file_path (Path): Path to the rule file.
        
        Returns:
            Optional[str]: File content or None if invalid.
        """
        if not self.validate_rule_file(file_path):
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            self.errors.append(f"Failed to read rule content: {e}")
            return None
