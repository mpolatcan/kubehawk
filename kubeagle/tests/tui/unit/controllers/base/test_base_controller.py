"""Tests for base controller module."""

from __future__ import annotations

import pytest

from kubeagle.controllers.base.base_controller import (
    AsyncControllerMixin,
    BaseController,
    WorkerResult,
)


class TestWorkerResult:
    """Tests for WorkerResult dataclass."""

    def test_worker_result_success(self) -> None:
        """Test successful worker result."""
        result = WorkerResult(success=True, data={"key": "value"}, duration_ms=100.0)
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None
        assert result.duration_ms == 100.0

    def test_worker_result_error(self) -> None:
        """Test error worker result."""
        result = WorkerResult(success=False, error="Something went wrong", duration_ms=50.0)
        assert result.success is False
        assert result.data is None
        assert result.error == "Something went wrong"
        assert result.duration_ms == 50.0

    def test_worker_result_defaults(self) -> None:
        """Test WorkerResult default values."""
        result = WorkerResult(success=True)
        assert result.data is None
        assert result.error is None
        assert result.duration_ms == 0.0


class TestAsyncControllerMixin:
    """Tests for AsyncControllerMixin class."""

    @pytest.fixture
    def mixin(self) -> AsyncControllerMixin:
        """Create mixin instance for testing."""
        return AsyncControllerMixin()

    def test_mixin_init(self, mixin: AsyncControllerMixin) -> None:
        """Test AsyncControllerMixin initialization."""
        assert mixin._load_start_time is None


class TestBaseController:
    """Tests for BaseController abstract class."""

    def test_base_controller_is_abstract(self) -> None:
        """Test that BaseController is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseController()

    def test_base_controller_inherits_from_async_mixin(self) -> None:
        """Test that BaseController inherits from AsyncControllerMixin."""

        class ConcreteController(BaseController):
            async def check_connection(self) -> bool:
                return True

            async def fetch_all(self) -> dict:
                return {}

        controller = ConcreteController()
        assert isinstance(controller, AsyncControllerMixin)
