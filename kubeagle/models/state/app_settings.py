"""Application settings models."""

from pydantic import BaseModel, ConfigDict

from kubeagle.constants.defaults import THEME_DEFAULT
from kubeagle.constants.screens.common import LIGHT_THEME


class ThemePreference(str):
    """Theme preference values persisted in settings."""

    DARK = THEME_DEFAULT
    LIGHT = LIGHT_THEME


class AppSettings(BaseModel):
    """Application settings model with validation."""

    model_config = ConfigDict(populate_by_name=True)

    # Paths
    charts_path: str = ""
    active_charts_path: str = ""
    codeowners_path: str = ""
    export_path: str = "./reports"

    # UI preferences
    theme: str = ThemePreference.DARK
    refresh_interval: int = 30  # seconds
    auto_refresh: bool = False

    # Cluster mode for Helm analysis
    use_cluster_values: bool = False
    use_cluster_mode: bool = False

    # Event and resource thresholds
    event_age_hours: float = 1.0
    high_cpu_threshold: int = 80
    high_memory_threshold: int = 80
    high_pod_threshold: int = 80
    limit_request_ratio_threshold: float = 2.0
    high_pod_percentage_threshold: int = 80

    # Optimizer verification settings
    optimizer_analysis_source: str = "auto"  # auto|rendered|values
    verify_fixes_with_render: bool = True
    helm_template_timeout_seconds: int = 30
    ai_fix_llm_provider: str = "codex"  # codex|claude
    ai_fix_codex_model: str = "auto"  # auto|gpt-5.3-codex|gpt-5.3-codex-spark|...
    ai_fix_claude_model: str = "auto"  # auto|default|sonnet|opus|haiku
    ai_fix_full_fix_system_prompt: str = ""
    ai_fix_bulk_parallelism: int = 2

    # Progressive loading
    progressive_parallelism: int = 2
    progressive_yield_interval: int = 2

    # Fixed resource fields - fields protected from optimizer modifications
    # Valid values: "cpu_request", "cpu_limit", "memory_request", "memory_limit"
    fixed_resource_fields: list[str] = ["cpu_limit", "memory_limit"]


class ConfigError(Exception):
    """Base exception for configuration errors."""


class ConfigLoadError(ConfigError):
    """Raised when settings fail to load."""


class ConfigSaveError(ConfigError):
    """Raised when settings fail to save."""
