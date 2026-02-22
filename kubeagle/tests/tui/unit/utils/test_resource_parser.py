"""Tests for resource parser utilities."""

from __future__ import annotations

from kubeagle.utils.resource_parser import (
    memory_str_to_bytes,
    parse_cpu,
    parse_cpu_from_dict,
    parse_memory_from_dict,
)


class TestParseCpu:
    """Tests for parse_cpu function."""

    def test_parse_cpu_millicores(self) -> None:
        """Test parsing CPU in millicores."""
        assert parse_cpu("100m") == 0.1
        assert parse_cpu("500m") == 0.5
        assert parse_cpu("1000m") == 1.0

    def test_parse_cpu_micro_and_nano_cores(self) -> None:
        """Test parsing CPU in microcore/nanocore units."""
        assert parse_cpu("500000u") == 0.5
        assert parse_cpu("500000000n") == 0.5

    def test_parse_cpu_decimal(self) -> None:
        """Test parsing CPU in decimal."""
        assert parse_cpu("1.5") == 1.5
        assert parse_cpu("2") == 2.0
        assert parse_cpu("0.5") == 0.5

    def test_parse_cpu_empty_string(self) -> None:
        """Test parsing empty CPU string."""
        assert parse_cpu("") == 0.0
        assert parse_cpu(None) == 0.0  # type: ignore

    def test_parse_cpu_invalid(self) -> None:
        """Test parsing invalid CPU string."""
        assert parse_cpu("invalid") == 0.0

    def test_parse_cpu_with_whitespace(self) -> None:
        """Test parsing CPU string with whitespace."""
        assert parse_cpu(" 100m ") == 0.1


class TestMemoryStrToBytes:
    """Tests for memory_str_to_bytes function."""

    def test_memory_str_to_bytes_mebibytes(self) -> None:
        """Test converting Mi to bytes."""
        result = memory_str_to_bytes("512Mi")
        assert result == 512 * 1024 * 1024

    def test_memory_str_to_bytes_gibibytes(self) -> None:
        """Test converting Gi to bytes."""
        result = memory_str_to_bytes("1Gi")
        assert result == 1024 * 1024 * 1024

    def test_memory_str_to_bytes_kibibytes(self) -> None:
        """Test converting Ki to bytes."""
        result = memory_str_to_bytes("1024Ki")
        assert result == 1024 * 1024

    def test_memory_str_to_bytes_empty(self) -> None:
        """Test converting empty string."""
        assert memory_str_to_bytes("") == 0.0


class TestParseCpuFromDict:
    """Tests for parse_cpu_from_dict function."""

    def test_parse_cpu_from_dict(self) -> None:
        """Test parsing CPU from dictionary."""
        values = {
            "resources": {
                "requests": {"cpu": "100m"},
                "limits": {"cpu": "500m"},
            }
        }

        result = parse_cpu_from_dict(values, "requests", "cpu")
        assert result == 100.0

    def test_parse_cpu_from_dict_missing(self) -> None:
        """Test parsing CPU from dictionary with missing values."""
        values = {"resources": {"requests": {}}}

        result = parse_cpu_from_dict(values, "requests", "cpu")
        assert result == 0.0

    def test_parse_cpu_from_dict_no_resources(self) -> None:
        """Test parsing CPU from dictionary without resources."""
        values = {}

        result = parse_cpu_from_dict(values, "requests", "cpu")
        assert result == 0.0

    def test_parse_cpu_from_dict_null_resources(self) -> None:
        """Test parsing CPU when resources field is null."""
        values = {"resources": None}

        result = parse_cpu_from_dict(values, "requests", "cpu")
        assert result == 0.0

    def test_parse_cpu_from_dict_invalid(self) -> None:
        """Test parsing CPU from dictionary with invalid data."""
        values = {
            "resources": {
                "requests": {"cpu": "invalid"},
            }
        }

        result = parse_cpu_from_dict(values, "requests", "cpu")
        assert result == 0.0


class TestParseMemoryFromDict:
    """Tests for parse_memory_from_dict function."""

    def test_parse_memory_from_dict(self) -> None:
        """Test parsing memory from dictionary."""
        values = {
            "resources": {
                "requests": {"memory": "128Mi"},
                "limits": {"memory": "256Mi"},
            }
        }

        result = parse_memory_from_dict(values, "requests", "memory")
        assert result > 0

    def test_parse_memory_from_dict_missing(self) -> None:
        """Test parsing memory from dictionary with missing values."""
        values = {"resources": {"requests": {}}}

        result = parse_memory_from_dict(values, "requests", "memory")
        assert result == 0.0

    def test_parse_memory_from_dict_no_resources(self) -> None:
        """Test parsing memory from dictionary without resources."""
        values = {}

        result = parse_memory_from_dict(values, "requests", "memory")
        assert result == 0.0

    def test_parse_memory_from_dict_null_resources(self) -> None:
        """Test parsing memory when resources field is null."""
        values = {"resources": None}

        result = parse_memory_from_dict(values, "requests", "memory")
        assert result == 0.0
