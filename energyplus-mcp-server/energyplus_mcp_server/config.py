"""
Configuration management for EnergyPlus MCP Server

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

import os
import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Soft-load .env for local development convenience.
# Production (Cloud Run, etc.) sets env vars directly — no .env needed.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class EnergyPlusConfig:
    """EnergyPlus-specific configuration"""
    idd_path: str = ""
    installation_path: str = ""
    executable_path: str = ""
    version: str = "26.1.0"
    weather_data_path: str = ""
    default_weather_file: str = ""
    example_files_path: str = ""


@dataclass
class PathConfig:
    """Path configuration"""
    workspace_root: str = "/workspace/energyplus-mcp-server"
    sample_files_path: str = ""
    temp_dir: str = "/tmp"
    output_dir: str = "/workspace/energyplus-mcp-server/outputs"
    
    def __post_init__(self):
        """Set default paths after initialization"""
        if not self.sample_files_path:
            self.sample_files_path = os.path.join(self.workspace_root, "sample_files")


@dataclass
class ServerConfig:
    """Server configuration"""
    name: str = "energyplus-mcp-server"
    version: str = "0.1.0"
    log_level: str = "INFO"
    simulation_timeout: int = 300  # seconds
    tool_timeout: int = 60  # seconds


@dataclass
class TransportConfig:
    """Transport-layer configuration (stdio vs streamable-http)"""
    transport: str = "stdio"          # "stdio" | "streamable-http"
    http_host: str = "0.0.0.0"
    http_port: int = 8000
    http_path: str = "/mcp"


@dataclass
class AuthConfig:
    """Bearer-token table for streamable-http transport.

    Internal shape: dict mapping raw token string → human label.
    Empty dict in stdio mode (no auth wired in).
    """
    tokens: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """Main configuration class"""
    energyplus: EnergyPlusConfig = field(default_factory=EnergyPlusConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    debug_mode: bool = False

    def __post_init__(self):
        """Set up configuration after initialization"""
        self._setup_transport()
        self._setup_auth()
        self._setup_energyplus_paths()
        self._setup_logging()
        self._validate_config()

    def _setup_transport(self):
        """Read transport env vars; fail-closed on unknown values."""
        valid = {"stdio", "streamable-http"}
        t = os.getenv("MCP_TRANSPORT", "stdio").strip()
        if t not in valid:
            raise ValueError(
                f"MCP_TRANSPORT must be one of {sorted(valid)}, got: {t!r}"
            )
        self.transport.transport = t
        self.transport.http_host = os.getenv("MCP_HTTP_HOST", self.transport.http_host)
        port_str = os.getenv("MCP_HTTP_PORT") or os.getenv("PORT")
        if port_str:
            try:
                self.transport.http_port = int(port_str)
            except ValueError:
                raise ValueError(f"MCP_HTTP_PORT/PORT must be an integer, got: {port_str!r}")
        self.transport.http_path = os.getenv("MCP_HTTP_PATH", self.transport.http_path)

    _LABEL_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
    _MIN_TOKEN_LEN = 32

    def _setup_auth(self):
        """Parse MCP_TOKENS JSON; fail-closed on validation errors."""
        raw = os.getenv("MCP_TOKENS", "").strip()
        if not raw:
            tokens = {}
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"MCP_TOKENS must be valid JSON: {e}") from e
            if not isinstance(parsed, list):
                raise ValueError("MCP_TOKENS must be a JSON array of objects")
            tokens = {}
            seen_labels = set()
            for i, entry in enumerate(parsed):
                if not isinstance(entry, dict) or "label" not in entry or "token" not in entry:
                    raise ValueError(
                        f"MCP_TOKENS[{i}] missing 'token' or 'label' key"
                    )
                label = entry["label"]
                token = entry["token"]
                if not isinstance(label, str) or not self._LABEL_RE.match(label):
                    raise ValueError(
                        f"MCP_TOKENS[{i}] invalid label {label!r}; must match "
                        f"[a-z0-9_-]{{1,32}}"
                    )
                if not isinstance(token, str) or len(token) < self._MIN_TOKEN_LEN:
                    raise ValueError(
                        f"MCP_TOKENS[{i}] token too short; min "
                        f"{self._MIN_TOKEN_LEN} characters"
                    )
                if label in seen_labels:
                    raise ValueError(f"MCP_TOKENS has duplicate label {label!r}")
                if token in tokens:
                    raise ValueError(
                        f"MCP_TOKENS has duplicate token: labels "
                        f"{tokens[token]!r} and {label!r} share the same token value"
                    )
                seen_labels.add(label)
                tokens[token] = label

        if self.transport.transport == "streamable-http" and not tokens:
            raise ValueError(
                "streamable-http transport requires non-empty MCP_TOKENS"
            )
        self.auth.tokens = tokens

    def _setup_energyplus_paths(self):
        """Set up EnergyPlus paths from environment variables or defaults"""
        # Get from environment variable or use default
        ep_idd_path = os.getenv('EPLUS_IDD_PATH')
        if ep_idd_path:
            self.energyplus.idd_path = ep_idd_path
            # Derive installation path from IDD path
            self.energyplus.installation_path = os.path.dirname(ep_idd_path)
            # Set executable path
            self.energyplus.executable_path = os.path.join(
                self.energyplus.installation_path, "energyplus"
            )
            # Set weather data path
            self.energyplus.weather_data_path = os.path.join(
                self.energyplus.installation_path, "WeatherData"
            )
            # Set example files path
            self.energyplus.example_files_path = os.path.join(
                self.energyplus.installation_path, "ExampleFiles"
            )
        else:
            # Default paths
            default_installation = "/app/software/EnergyPlusV26-1-0"
            self.energyplus.installation_path = default_installation
            self.energyplus.idd_path = os.path.join(default_installation, "Energy+.idd")
            self.energyplus.executable_path = os.path.join(default_installation, "energyplus")
            # Set weather data path
            self.energyplus.weather_data_path = os.path.join(default_installation, "WeatherData")
            # Set example files path
            self.energyplus.example_files_path = os.path.join(default_installation, "ExampleFiles")
        
        # Set default weather file
        self.energyplus.default_weather_file = os.path.join(
            self.energyplus.weather_data_path, 
            "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
        )

    def _setup_logging(self):
        """Configure logging based on configuration"""
        log_level = getattr(logging, self.server.log_level.upper(), logging.INFO)
        
        # Configure logging format
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        logger = logging.getLogger(__name__)
        logger.info(f"Logging configured: level={self.server.log_level}")

    def _validate_config(self):
        """Validate configuration and log warnings for missing components"""
        logger = logging.getLogger(__name__)
        
        # Check EnergyPlus installation
        if not os.path.exists(self.energyplus.idd_path):
            logger.warning(f"EnergyPlus IDD file not found: {self.energyplus.idd_path}")
        
        if not os.path.exists(self.energyplus.executable_path):
            logger.warning(f"EnergyPlus executable not found: {self.energyplus.executable_path}")
        
        # Check weather data
        if not os.path.exists(self.energyplus.weather_data_path):
            logger.warning(f"EnergyPlus weather data directory not found: {self.energyplus.weather_data_path}")
        
        if not os.path.exists(self.energyplus.default_weather_file):
            logger.warning(f"Default weather file not found: {self.energyplus.default_weather_file}")
        
        # Check example files
        if not os.path.exists(self.energyplus.example_files_path):
            logger.warning(f"EnergyPlus example files directory not found: {self.energyplus.example_files_path}")
        
        # Check sample files directory
        if not os.path.exists(self.paths.sample_files_path):
            logger.warning(f"Sample files directory not found: {self.paths.sample_files_path}")
        
        # Create output directory if it doesn't exist (tolerant in dev/test)
        try:
            os.makedirs(self.paths.output_dir, exist_ok=True)
        except OSError:
            logger.warning("Could not create output dir %s", self.paths.output_dir)

        logger.info("Configuration loaded and validated successfully")

    def _setup_logging(self):
        """Set up logging configuration with both console and file handlers"""
        import logging.handlers
        from pathlib import Path

        logger = logging.getLogger(__name__)

        # Create logs directory (tolerant of read-only/missing parent in dev/test)
        log_dir = Path(self.paths.workspace_root) / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning(
                "Could not create log directory %s; file logging disabled", log_dir
            )
            return  # file logging disabled; WARNING+ still visible via logging.lastResort
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.server.log_level))
        
        # Clear existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Console handler (for stdout/stderr)
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # File handler for all logs
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "energyplus_mcp_server.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        # Separate error log file
        error_handler = logging.handlers.RotatingFileHandler(
            log_dir / "energyplus_mcp_errors.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        root_logger.addHandler(error_handler)
        
        logger.info(f"Logging configured: level={self.server.log_level}")
        logger.info(f"Log files: {log_dir}")
        
        return log_dir


def get_config() -> Config:
    """Get the global configuration instance"""
    if not hasattr(get_config, '_config'):
        get_config._config = Config()
    
    return get_config._config


def reload_config() -> Config:
    """Reload configuration (useful for testing)"""
    if hasattr(get_config, '_config'):
        delattr(get_config, '_config')
    return get_config()
