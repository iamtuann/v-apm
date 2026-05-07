"""Cline AI assistant implementation of MCP client adapter.

This adapter implements the Cline-specific handling of MCP server configuration,
targeting the VS Code globalStorage path for Cline MCP settings.

Config location by platform:
- Linux: ~/.config/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json
- Windows: %APPDATA%/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json
- macOS: ~/Library/Application Support/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from .base import MCPClientAdapter


def _get_cline_mcp_settings_path() -> Path:
    """Get the Cline MCP settings path for the current platform.
    
    Returns:
        Path to cline_mcp_settings.json
    """
    if os.name == 'nt':  # Windows
        base = Path(os.environ.get('APPDATA', ''))
        return base / 'Code' / 'User' / 'globalStorage' / 'cline-sr.cline-sr' / 'settings' / 'cline_mcp_settings.json'
    elif sys.platform == 'darwin':  # macOS
        return Path.home() / 'Library' / 'Application Support' / 'Code' / 'User' / 'globalStorage' / 'cline-sr.cline-sr' / 'settings' / 'cline_mcp_settings.json'
    else:  # Linux and others
        return Path.home() / '.config' / 'Code' / 'User' / 'globalStorage' / 'cline-sr.cline-sr' / 'settings' / 'cline_mcp_settings.json'


class ClineClientAdapter(MCPClientAdapter):
    """Cline implementation of MCP client adapter.
    
    This adapter handles Cline-specific configuration for MCP servers using
    the VS Code globalStorage path for Cline settings.
    
    The adapter is user-scope capable, allowing MCP servers to be registered
    globally for Cline across all projects.
    """
    supports_user_scope: bool = True
    mcp_servers_key: str = "mcpServers"

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
    
    def get_config_path(self) -> str:
        """Get the path to the Cline MCP configuration file.
        
        Returns:
            str: Path to cline_mcp_settings.json
        """
        return str(_get_cline_mcp_settings_path())
    
    def get_current_config(self) -> dict[str, Any]:
        """Get the current Cline MCP configuration.
        
        Returns:
            dict: Current configuration, or empty dict with mcpServers if file doesn't exist.
        """
        config_path = Path(self.get_config_path())
        
        if not config_path.exists():
            return {"mcpServers": {}}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Ensure mcpServers key exists
                if "mcpServers" not in config:
                    config["mcpServers"] = {}
                return config
        except (json.JSONDecodeError, IOError):
            return {"mcpServers": {}}
    
    def update_config(self, config_updates: dict[str, Any]) -> bool:
        """Update the Cline MCP configuration.
        
        Args:
            config_updates (dict): Configuration updates to apply to mcpServers.
        
        Returns:
            bool: True if successful, False otherwise.
        """
        current_config = self.get_current_config()
        
        # Apply updates to mcpServers
        if "mcpServers" not in current_config:
            current_config["mcpServers"] = {}
        
        current_config["mcpServers"].update(config_updates)
        
        # Write back to file
        config_path = Path(self.get_config_path())
        
        try:
            # Ensure directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(current_config, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error updating Cline MCP config: {e}")
            return False
    
    def configure_mcp_server(
        self,
        server_url: str,
        server_name: str | None = None,
        enabled: bool = True,
        env_overrides: dict | None = None,
        server_info_cache: dict | None = None,
        runtime_vars: dict | None = None,
    ) -> bool:
        """Configure an MCP server in Cline configuration.
        
        This method writes the MCP server config to cline_mcp_settings.json
        in the standard Cline format.
        
        Args:
            server_url: URL or identifier of the MCP server.
            server_name: Name of the server. Defaults to None.
            enabled: Whether to enable the server. Defaults to True.
            env_overrides: Environment variable overrides. Defaults to None.
            server_info_cache: Pre-fetched server info to avoid duplicate registry calls.
            runtime_vars: Runtime variable values. Defaults to None.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        if not server_url:
            print("Error: server_url cannot be empty")
            return False
        
        server_key = server_name or server_url
        
        try:
            # Build the config entry for Cline
            # Cline uses the standard MCP format:
            # {
            #   "mcpServers": {
            #     "server-name": {
            #       "command": "npx",
            #       "args": ["-y", "@org/server"],
            #       "env": {...}
            #     }
            #   }
            # }
            
            # Parse server info if available
            config_entry = self._build_server_config(
                server_url=server_url,
                server_info_cache=server_info_cache,
                env_overrides=env_overrides,
                runtime_vars=runtime_vars,
                server_name=server_key,
            )
            
            updates = {server_key: config_entry}
            
            return self.update_config(updates)
        
        except Exception as e:
            print(f"Error configuring MCP server in Cline: {e}")
            return False
    
    def _build_server_config(
        self,
        server_url: str,
        server_info_cache: dict | None = None,
        env_overrides: dict | None = None,
        runtime_vars: dict | None = None,
        server_name: str | None = None,
    ) -> dict[str, Any]:
        """Build the MCP server config entry for Cline.
        
        Args:
            server_url: Server URL or identifier.
            server_info_cache: Pre-fetched server info from registry (dict keyed by server name).
            env_overrides: Environment variable overrides.
            runtime_vars: Runtime variable values.
            server_name: Server name to look up in cache.
            
        Returns:
            dict: Server configuration entry.
        """
        env = {}
        
        # If we have server info from registry, use it
        # server_info_cache is keyed by server name, so look up the specific server
        info = None
        if server_info_cache:
            # Look up by server_name if provided, otherwise by server_url
            lookup_key = server_name or server_url
            info = server_info_cache.get(lookup_key) if isinstance(server_info_cache, dict) else None
            if not info and isinstance(server_info_cache, dict):
                # Try server_url as fallback
                info = server_info_cache.get(server_url)
            # Legacy: if cache is the info dict directly (not keyed by name)
            if not info and isinstance(server_info_cache, dict):
                # Check if the cache itself is the info (not keyed by name)
                if server_info_cache.get("name") == lookup_key or server_info_cache.get("packages") or server_info_cache.get("_raw_stdio"):
                    info = server_info_cache
        
        # Process the info if found
        if info:
            # Check for raw stdio config (self-defined servers)
            if "_raw_stdio" in info:
                raw = info["_raw_stdio"]
                config = {
                    "command": raw.get("command", server_url),
                    "args": raw.get("args", []),
                }
                env = dict(raw.get("env", {}))
            # Check for packages (stdio from registry)
            elif info.get("packages"):
                pkg = info["packages"][0]  # Use first package
                registry_name = pkg.get("registry_name", "npm")
                
                # Build command based on registry
                if registry_name.lower() in ("npm", "npx"):
                    config = {
                        "command": "npx",
                        "args": ["-y", pkg.get("name", server_url)],
                    }
                elif registry_name.lower() in ("pypi", "pip", "uv"):
                    config = {
                        "command": "uvx",
                        "args": [pkg.get("name", server_url)],
                    }
                elif registry_name.lower() in ("oci", "docker"):
                    config = {
                        "command": "docker",
                        "args": ["run", "--rm", "-i", pkg.get("name", server_url)],
                    }
                else:
                    # Fallback to npx
                    config = {
                        "command": "npx",
                        "args": ["-y", pkg.get("name", server_url)],
                    }
                
                # Add runtime arguments
                runtime_args = pkg.get("runtime_arguments", [])
                for arg in runtime_args:
                    if arg.get("value_hint"):
                        config["args"].append(arg["value_hint"])
                
                # Collect required env vars
                for env_var in pkg.get("environment_variables", []):
                    var_name = env_var.get("name", "")
                    if var_name:
                        env[var_name] = env_overrides.get(var_name, "") if env_overrides else ""
            
            # Check for remotes (HTTP/SSE servers)
            elif info.get("remotes"):
                remote = info["remotes"][0]  # Use first remote
                transport = remote.get("transport_type", "http")
                
                # For HTTP/SSE remotes, we need to use a different config format
                # Cline supports HTTP MCP servers
                config = {
                    "url": remote.get("url", server_url),
                    "transport": transport,
                }
                
                # Add headers if present
                headers = remote.get("headers", [])
                if headers:
                    config["headers"] = {h["name"]: h["value"] for h in headers}
            
            else:
                # Fallback: treat as command
                config = {
                    "command": server_url,
                    "args": [],
                }
        else:
            # No server info - treat as command
            config = {
                "command": server_url,
                "args": [],
            }
        
        # Apply env overrides
        if env_overrides:
            env.update(env_overrides)
        
        # Apply runtime vars
        if runtime_vars:
            for key, value in runtime_vars.items():
                env[key] = value
        
        # Add env to config if non-empty
        if env:
            config["env"] = env
        
        return config
    
    def get_mcp_servers(self) -> dict[str, Any]:
        """Get configured MCP servers.
        
        Returns:
            dict: MCP server configurations.
        """
        config = self.get_current_config()
        return config.get("mcpServers", {})
    
    def remove_mcp_server(self, server_name: str) -> bool:
        """Remove an MCP server from configuration.
        
        Args:
            server_name: Name of the server to remove.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        current_config = self.get_current_config()
        
        if "mcpServers" not in current_config:
            return True
        
        if server_name in current_config["mcpServers"]:
            del current_config["mcpServers"][server_name]
            
            # Write back to file
            config_path = Path(self.get_config_path())
            
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(current_config, f, indent=2)
                
                return True
            except Exception as e:
                print(f"Error removing MCP server from Cline: {e}")
                return False
        
        return True