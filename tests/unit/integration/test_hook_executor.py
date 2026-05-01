"""Unit tests for HookExecutor.

Tests cover:
- Hook language detection (.js, .py, .sh, .json file extensions)
- Hook execution routing to language-specific handlers
- Hook contract validation (stdin/stdout JSON)
- Error handling (missing runtime, timeout, parse errors)
- Graceful degradation (proceed on hook failure)
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apm_cli.integration.hook_executor import (
    HookExecutor,
    HookLanguage,
    detect_hook_language,
)


class TestHookLanguageDetection:
    """Test detect_hook_language() extension mapping."""

    def test_detect_javascript(self):
        """Detect .js files as JavaScript."""
        hook_path = Path("/tmp/hook.js")
        lang = detect_hook_language(hook_path)
        assert lang == HookLanguage.JAVASCRIPT

    def test_detect_python(self):
        """Detect .py files as Python."""
        hook_path = Path("/tmp/hook.py")
        lang = detect_hook_language(hook_path)
        assert lang == HookLanguage.PYTHON

    def test_detect_shell(self):
        """Detect .sh files as Shell."""
        hook_path = Path("/tmp/hook.sh")
        lang = detect_hook_language(hook_path)
        assert lang == HookLanguage.SHELL

    def test_detect_json(self):
        """Detect .json files as JSON."""
        hook_path = Path("/tmp/hook.json")
        lang = detect_hook_language(hook_path)
        assert lang == HookLanguage.JSON

    def test_detect_bash_no_extension(self):
        """Files without extension default to Shell."""
        hook_path = Path("/tmp/hook")
        lang = detect_hook_language(hook_path)
        assert lang == HookLanguage.SHELL

    def test_detect_case_insensitive(self):
        """Extension detection is case-insensitive."""
        assert detect_hook_language(Path("/tmp/Hook.JS")) == HookLanguage.JAVASCRIPT
        assert detect_hook_language(Path("/tmp/Hook.PY")) == HookLanguage.PYTHON
        assert detect_hook_language(Path("/tmp/Hook.SH")) == HookLanguage.SHELL


class TestHookExecutorJavaScript:
    """Test JavaScript hook execution."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.hook_path = Path(self.temp_dir) / "hook.js"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_execute_javascript_success(self):
        """JavaScript hook executes and returns JSON response."""
        hook_content = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf-8'));
console.log(JSON.stringify({cancel: false, message: "OK"}));
"""
        self.hook_path.write_text(hook_content)

        hook_input = {"event": "PreToolUse", "context": {}}
        result = HookExecutor.execute(self.hook_path, hook_input)

        assert result["cancel"] is False
        assert "message" in result

    @patch("subprocess.run")
    def test_execute_javascript_calls_node(self, mock_run):
        """JavaScript execution routes to 'node' command."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"cancel": false}',
            stderr=""
        )

        hook_input = {"event": "PreToolUse"}
        HookExecutor._execute_javascript(self.hook_path, hook_input)

        # Verify node command was called
        call_args = mock_run.call_args
        assert "node" in call_args[0][0]

    @patch("subprocess.run")
    def test_execute_javascript_timeout_graceful_degradation(self, mock_run):
        """JavaScript timeout is handled gracefully."""
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("node", 5)

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor._execute_javascript(self.hook_path, hook_input)

        # Graceful degradation: return proceed flag
        assert result.get("cancel") is False


class TestHookExecutorPython:
    """Test Python hook execution."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.hook_path = Path(self.temp_dir) / "hook.py"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_execute_python_success(self):
        """Python hook executes and returns JSON response."""
        hook_content = """
import json
import sys
input_data = json.load(sys.stdin)
print(json.dumps({"cancel": False, "message": "OK"}))
"""
        self.hook_path.write_text(hook_content)

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor.execute(self.hook_path, hook_input)

        assert result["cancel"] is False

    @patch("subprocess.run")
    def test_execute_python_calls_python(self, mock_run):
        """Python execution routes to 'python' command."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"cancel": false}',
            stderr=""
        )

        hook_input = {"event": "PreToolUse"}
        HookExecutor._execute_python(self.hook_path, hook_input)

        # Verify python command was called
        call_args = mock_run.call_args
        assert "python" in call_args[0][0]

    @patch("subprocess.run")
    def test_execute_python_parse_error_graceful_degradation(self, mock_run):
        """Invalid JSON output is handled gracefully."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='not valid json',
            stderr=""
        )

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor._execute_python(self.hook_path, hook_input)

        # Graceful degradation: return proceed flag
        assert result.get("cancel") is False


class TestHookExecutorShell:
    """Test Shell hook execution."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.hook_path = Path(self.temp_dir) / "hook.sh"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_execute_shell_success(self):
        """Shell hook executes and returns JSON response."""
        hook_content = """#!/bin/bash
read input
echo '{"cancel": false, "message": "OK"}'
"""
        self.hook_path.write_text(hook_content)
        self.hook_path.chmod(0o755)

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor.execute(self.hook_path, hook_input)

        assert result["cancel"] is False

    @patch("subprocess.run")
    def test_execute_shell_calls_bash(self, mock_run):
        """Shell execution routes to bash command."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"cancel": false}',
            stderr=""
        )

        hook_input = {"event": "PreToolUse"}
        HookExecutor._execute_shell(self.hook_path, hook_input)

        # Verify bash command was called
        call_args = mock_run.call_args
        assert "bash" in call_args[0][0]

    @patch("subprocess.run")
    def test_execute_shell_nonzero_exit_graceful_degradation(self, mock_run):
        """Shell non-zero exit is handled gracefully."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='',
            stderr="error message"
        )

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor._execute_shell(self.hook_path, hook_input)

        # Graceful degradation: return proceed flag
        assert result.get("cancel") is False


class TestHookExecutorContract:
    """Test hook input/output contract (JSON stdin/stdout)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hook_receives_input_as_json_stdin(self):
        """Hook receives input JSON via stdin."""
        hook_path = Path(self.temp_dir) / "hook.py"
        hook_content = """
import json
import sys
data = json.load(sys.stdin)
assert "event" in data
print(json.dumps({"cancel": false}))
"""
        hook_path.write_text(hook_content)

        hook_input = {"event": "PreToolUse", "tool": "read_file"}
        result = HookExecutor.execute(hook_path, hook_input)

        assert result is not None

    def test_hook_output_must_have_cancel_field(self):
        """Hook output must include 'cancel' boolean."""
        hook_path = Path(self.temp_dir) / "hook.py"
        hook_content = """
import json
import sys
print(json.dumps({"cancel": true}))
"""
        hook_path.write_text(hook_content)

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor.execute(hook_path, hook_input)

        assert "cancel" in result
        assert isinstance(result["cancel"], bool)

    def test_hook_output_can_have_optional_message(self):
        """Hook output can include optional 'message' field."""
        hook_path = Path(self.temp_dir) / "hook.py"
        hook_content = """
import json
import sys
print(json.dumps({"cancel": false, "message": "custom message"}))
"""
        hook_path.write_text(hook_content)

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor.execute(hook_path, hook_input)

        assert result.get("message") == "custom message"


class TestHookExecutorDispatch:
    """Test HookExecutor.execute() language dispatch."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch.object(HookExecutor, "_execute_javascript")
    def test_execute_dispatches_js_correctly(self, mock_js):
        """JavaScript hooks routed to _execute_javascript()."""
        mock_js.return_value = {"cancel": False}

        hook_path = Path(self.temp_dir) / "hook.js"
        hook_path.write_text("console.log('test')")

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor.execute(hook_path, hook_input)

        mock_js.assert_called_once()
        assert result == {"cancel": False}

    @patch.object(HookExecutor, "_execute_python")
    def test_execute_dispatches_py_correctly(self, mock_py):
        """Python hooks routed to _execute_python()."""
        mock_py.return_value = {"cancel": False}

        hook_path = Path(self.temp_dir) / "hook.py"
        hook_path.write_text("print('test')")

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor.execute(hook_path, hook_input)

        mock_py.assert_called_once()
        assert result == {"cancel": False}

    @patch.object(HookExecutor, "_execute_shell")
    def test_execute_dispatches_sh_correctly(self, mock_sh):
        """Shell hooks routed to _execute_shell()."""
        mock_sh.return_value = {"cancel": False}

        hook_path = Path(self.temp_dir) / "hook.sh"
        hook_path.write_text("echo 'test'")

        hook_input = {"event": "PreToolUse"}
        result = HookExecutor.execute(hook_path, hook_input)

        mock_sh.assert_called_once()
        assert result == {"cancel": False}
