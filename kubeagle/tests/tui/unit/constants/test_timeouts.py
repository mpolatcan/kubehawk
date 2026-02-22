"""Unit tests for timeout constants in constants/timeouts.py.

Tests cover:
- All timeout values
- Correct types (float or str)
- Positive values for numeric timeouts
- Logical relationships between timeout magnitudes
"""

from __future__ import annotations

from kubeagle.constants.timeouts import (
    CHART_ANALYSIS_TIMEOUT,
    CLUSTER_CHECK_TIMEOUT,
    CLUSTER_REQUEST_TIMEOUT,
    HELM_COMMAND_TIMEOUT,
    KUBECTL_COMMAND_TIMEOUT,
)

# =============================================================================
# API/Cluster timeouts (string format)
# =============================================================================


class TestClusterRequestTimeout:
    """Test CLUSTER_REQUEST_TIMEOUT constant."""

    def test_type(self) -> None:
        assert isinstance(CLUSTER_REQUEST_TIMEOUT, str)

    def test_value(self) -> None:
        assert CLUSTER_REQUEST_TIMEOUT == "30s"

    def test_ends_with_s(self) -> None:
        assert CLUSTER_REQUEST_TIMEOUT.endswith("s")


# =============================================================================
# Command-level process timeouts
# =============================================================================


class TestCommandTimeouts:
    """Test subprocess-level command timeout constants."""

    def test_kubectl_command_timeout_type(self) -> None:
        assert isinstance(KUBECTL_COMMAND_TIMEOUT, int)

    def test_kubectl_command_timeout_value(self) -> None:
        assert KUBECTL_COMMAND_TIMEOUT == 45

    def test_helm_command_timeout_type(self) -> None:
        assert isinstance(HELM_COMMAND_TIMEOUT, int)

    def test_helm_command_timeout_value(self) -> None:
        assert HELM_COMMAND_TIMEOUT == 30

# =============================================================================
# Async operation timeouts
# =============================================================================


class TestAsyncTimeouts:
    """Test async operation timeout constants."""

    def test_cluster_check_timeout_type(self) -> None:
        assert isinstance(CLUSTER_CHECK_TIMEOUT, float)

    def test_cluster_check_timeout_value(self) -> None:
        assert CLUSTER_CHECK_TIMEOUT == 12.0

    def test_cluster_check_timeout_positive(self) -> None:
        assert CLUSTER_CHECK_TIMEOUT > 0

    def test_chart_analysis_timeout_type(self) -> None:
        assert isinstance(CHART_ANALYSIS_TIMEOUT, float)

    def test_chart_analysis_timeout_value(self) -> None:
        assert CHART_ANALYSIS_TIMEOUT == 180.0

    def test_chart_analysis_timeout_positive(self) -> None:
        assert CHART_ANALYSIS_TIMEOUT > 0


# =============================================================================
# __all__ exports
# =============================================================================


class TestTimeoutsExports:
    """Test that __all__ exports are correct."""

    def test_all_exports_importable(self) -> None:
        import kubeagle.constants.timeouts as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not defined"
