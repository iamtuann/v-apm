"""Cline AI assistant implementation of MCP client adapter.

This adapter implements the Cline-specific handling of MCP server configuration,
targeting the global ~/.cline/mcp-servers.json file for MCP integration.

Note: Phase 2 will complete the full MCP server registration logic.
"""

import json
import os
from pathlib import Path
from .base import MCPClientAdapter


class ClineClientAdapter(MCPClientAdapter):
    """Cline implementation of MCP client adapter.
    
    This adapter handles Cline-specific configuration for MCP servers using
    a global ~/.cline/mcp-servers.json file, following the JSON format for
    MCP server configuration.
    
    The adapter is user-scope capable, allowing MCP servers to be registered
    globally for Cline across all projects.
    """
    supports_user_scope: bool = True

    def __init__(
        self,
        registry_url=None,
        project_root: Path | str | None = None,
        user_scope: bool = False,
    ):
        """Initialize the Cline client adapter.
        
        Args:
            registry_url (str, optional): URL of the MCP registry.
                If not provided, uses the MCP_REGISTRY_URL environment variable
                or falls back to the default GitHub registry.
            project_root: Project root context passed through to the base
                adapter for scope-aware operations.
            user_scope: Whether the adapter should resolve user-scope config
                paths instead of project-local paths when supported.
        """
        super().__init__(project_root=project_root, user_scope=user_scope)
        self.registry_url = registry_url or os.environ.get("MCP_REGISTRY_URL", "")
    
    def get_config_path(self):
        """Get the path to the Cline MCP configuration file.
        
        Returns:
            str: Path to ~/.cline/mcp-servers.json
        """
        cline_dir = Path.home() / ".cline"
        return str(cline_dir / "mcp-servers.json")
    
    def update_config(self, config_updates) -> bool | None:
        """Update the Cline MCP configuration.
        
        Args:
            config_updates (dict): Configuration updates to apply.
        
        Returns:
            bool: True if successful, False otherwise.
        """
        current_config = self.get_current_config()
        
        # Ensure mcp section exists
        if "mcp" not in current_config:
            current_config["mcp"] = {}
        
        if "servers" not in current_config["mcp"]:
            current_config["mcp"]["servers"] = {}
        
        # Apply updates
        current_config["mcp"]["servers"].update(config_updates)
        
        # Write back to file
        config_path = Path(self.get_config_path())
        
        try:
            # Ensure directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, 'w') as f:
                json.dump(current_config, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error updating Cline MCP config: {e}")
            return False
    
    def get_current_config(self):
        """Get the current Cline MCP configuration.
        
        Returns:
            dict: Current configuration, or empty dict if file doesn't exist.
        """
        config_path = self.get_config_path()
        
        if not os.path.exists(config_path):
            return {}
        
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    
    def configure_mcp_server(self, server_url, server_name=None, enabled=True, env_overrides=None, server_info_cache=None, runtime_vars=None):
        """Configure an MCP server in Cline configuration.
        
        This method follows the Cline MCP configuration format with 
        mcp.servers object containing server configurations.
        
        Args:
            server_url (str): URL or identifier of the MCP server.
            server_name (str, optional): Name of the server. Defaults to None.
            enabled (bool, optional): Whether to enable the server. Defaults to True.
            env_overrides (dict, optional): Environment variable overrides. Defaults to None.
            server_info_cache (dict, optional): Pre-fetched server info to avoid duplicate registry calls.
            runtime_vars (dict, optional): Runtime variable values. Defaults to None.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        if not server_url:
            print("Error: server_url cannot be empty")
            return False
        
        try:
            # Phase 2: Implement full MCP server registration logic
            # For now, stub implementation that logs the configuration intent
            config_entry = {
                "enabled": enabled,
                "command": server_url,  # Placeholder for actual MCP command
                "args": [],
                "env": env_overrides or {},
            }
            
            server_key = server_name or server_url
            updates = {server_key: config_entry}
            
            return self.update_config(updates)
        
        except Exception as e:
            print(f"Error configuring MCP server in Cline: {e}")
            return False
