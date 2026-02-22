"""Default values for settings.

All default values used in AppSettings model and validation fallback values.
"""

from typing import Final

# ============================================================================
# UI defaults
# ============================================================================

THEME_DEFAULT: Final = "InsiderOne-Dark"
REFRESH_INTERVAL_DEFAULT: Final = 30

# ============================================================================
# Threshold defaults
# ============================================================================

EVENT_AGE_HOURS_DEFAULT: Final = 1.0
LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT: Final = 2.0

# ============================================================================
# Optimizer verification defaults
# ============================================================================

OPTIMIZER_ANALYSIS_SOURCE_DEFAULT: Final = "auto"
HELM_TEMPLATE_TIMEOUT_SECONDS_DEFAULT: Final = 30
AI_FIX_LLM_PROVIDER_DEFAULT: Final = "codex"
AI_FIX_CODEX_MODEL_DEFAULT: Final = "auto"
AI_FIX_CLAUDE_MODEL_DEFAULT: Final = "auto"
AI_FIX_FULL_FIX_SYSTEM_PROMPT_DEFAULT: Final = ""
AI_FIX_BULK_PARALLELISM_DEFAULT: Final = 2

__all__ = [
    "AI_FIX_BULK_PARALLELISM_DEFAULT",
    "AI_FIX_CLAUDE_MODEL_DEFAULT",
    "AI_FIX_CODEX_MODEL_DEFAULT",
    "AI_FIX_FULL_FIX_SYSTEM_PROMPT_DEFAULT",
    "AI_FIX_LLM_PROVIDER_DEFAULT",
    "EVENT_AGE_HOURS_DEFAULT",
    "HELM_TEMPLATE_TIMEOUT_SECONDS_DEFAULT",
    "LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT",
    "OPTIMIZER_ANALYSIS_SOURCE_DEFAULT",
    "REFRESH_INTERVAL_DEFAULT",
    "THEME_DEFAULT",
]
