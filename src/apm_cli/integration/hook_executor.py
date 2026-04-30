"""Hook execution for JS, Python, Shell, and JSON format hooks.

Cline supports multiple hook languages (.js, .py, .sh, .json).
This module provides unified execution routing and the hook contract.

Hook Contract:
    All hooks receive context via stdin as JSON:
        {
            "event": "PreToolUse",
            "tool": "read_file",
            "context": { ... }
        }

    All hooks must return JSON on stdout:
        {
            "cancel": false,
            "message": "optional message"
        }

Execution:
    - .json: Direct JSON merge (APM's existing pattern)
    - .js:   Node.js subprocess: node <path> (receives JSON via stdin)
    - .py:   Python subprocess: python <path> (receives JSON via stdin)
    - .sh:   Shell subprocess: bash <path> (receives JSON via stdin)
"""

import json
import logging
import subprocess
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Any

_log = logging.getLogger(__name__)


class HookLanguage(Enum):
    """Supported hook execution languages."""
    JSON = "json"       # APM's existing pattern (direct merge)
    JAVASCRIPT = "js"   # Node.js
    PYTHON = "py"       # Python
    SHELL = "sh"        # Bash/Shell


def detect_hook_language(hook_path: Path) -> HookLanguage:
    """Detect hook language from file extension.

    Args:
        hook_path: Path to the hook file

    Returns:
        HookLanguage enum value

    Raises:
        ValueError: If file extension is not recognized
    """
    ext = hook_path.suffix.lower()
    mapping = {
        ".json": HookLanguage.JSON,
        ".js": HookLanguage.JAVASCRIPT,
        ".py": HookLanguage.PYTHON,
        ".sh": HookLanguage.SHELL,
    }
    if ext not in mapping:
        raise ValueError(f"Unsupported hook format: {ext}")
    return mapping[ext]


class HookExecutor:
    """Execute hooks in various languages."""

    @staticmethod
    def execute(
        hook_path: Path,
        event: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Execute a hook file and return the result.

        Args:
            hook_path: Path to the hook file
            event: Event name (e.g., "PreToolUse", "TaskStart")
            context: Additional context dict to pass to the hook
            timeout: Execution timeout in seconds

        Returns:
            Dict with "cancel" (bool) and optional "message" (str)

        Raises:
            ValueError: If hook format is unsupported
            subprocess.TimeoutExpired: If hook execution times out
            Exception: Other execution errors (subprocess failures, etc.)
        """
        language = detect_hook_language(hook_path)

        # Prepare hook input context
        hook_input = {
            "event": event,
            "context": context or {},
        }

        if language == HookLanguage.JSON:
            # JSON hooks don't execute; they're merged directly
            # This method shouldn't be called for JSON hooks in normal flow
            _log.warning(f"Hook executor called for JSON hook {hook_path}; "
                        "JSON hooks should be merged, not executed")
            return {"cancel": False}

        elif language == HookLanguage.JAVASCRIPT:
            return HookExecutor._execute_javascript(
                hook_path, hook_input, timeout
            )
        elif language == HookLanguage.PYTHON:
            return HookExecutor._execute_python(
                hook_path, hook_input, timeout
            )
        elif language == HookLanguage.SHELL:
            return HookExecutor._execute_shell(
                hook_path, hook_input, timeout
            )

        raise ValueError(f"Unsupported hook language: {language}")

    @staticmethod
    def _execute_javascript(
        hook_path: Path,
        hook_input: Dict[str, Any],
        timeout: int,
    ) -> Dict[str, Any]:
        """Execute a JavaScript hook via Node.js.

        Args:
            hook_path: Path to the .js file
            hook_input: Input context dict
            timeout: Execution timeout in seconds

        Returns:
            Hook result dict
        """
        try:
            # Check if Node.js is available
            subprocess.run(
                ["node", "--version"],
                capture_output=True,
                timeout=5,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            _log.warning("Node.js not available; skipping JavaScript hook execution")
            return {"cancel": False}

        try:
            proc = subprocess.run(
                ["node", str(hook_path)],
                input=json.dumps(hook_input),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,  # Don't raise on non-zero exit
            )
            if proc.returncode != 0:
                _log.error(f"Hook {hook_path} failed: {proc.stderr}")
                return {"cancel": False}

            result = json.loads(proc.stdout)
            return result
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            _log.error(f"Hook {hook_path} error: {e}")
            return {"cancel": False}

    @staticmethod
    def _execute_python(
        hook_path: Path,
        hook_input: Dict[str, Any],
        timeout: int,
    ) -> Dict[str, Any]:
        """Execute a Python hook via Python interpreter.

        Args:
            hook_path: Path to the .py file
            hook_input: Input context dict
            timeout: Execution timeout in seconds

        Returns:
            Hook result dict
        """
        try:
            # Check if Python is available
            subprocess.run(
                ["python", "--version"],
                capture_output=True,
                timeout=5,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to python3
            try:
                subprocess.run(
                    ["python3", "--version"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                python_cmd = "python3"
            except (subprocess.CalledProcessError, FileNotFoundError):
                _log.warning("Python not available; skipping Python hook execution")
                return {"cancel": False}
            python_cmd = "python"
        else:
            python_cmd = "python"

        try:
            proc = subprocess.run(
                [python_cmd, str(hook_path)],
                input=json.dumps(hook_input),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode != 0:
                _log.error(f"Hook {hook_path} failed: {proc.stderr}")
                return {"cancel": False}

            result = json.loads(proc.stdout)
            return result
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            _log.error(f"Hook {hook_path} error: {e}")
            return {"cancel": False}

    @staticmethod
    def _execute_shell(
        hook_path: Path,
        hook_input: Dict[str, Any],
        timeout: int,
    ) -> Dict[str, Any]:
        """Execute a shell hook via bash.

        Args:
            hook_path: Path to the .sh file
            hook_input: Input context dict
            timeout: Execution timeout in seconds

        Returns:
            Hook result dict
        """
        try:
            proc = subprocess.run(
                ["bash", str(hook_path)],
                input=json.dumps(hook_input),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode != 0:
                _log.error(f"Hook {hook_path} failed: {proc.stderr}")
                return {"cancel": False}

            result = json.loads(proc.stdout)
            return result
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            _log.error(f"Hook {hook_path} error: {e}")
            return {"cancel": False}
