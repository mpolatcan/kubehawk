"""Tests for node parser."""

from __future__ import annotations

import pytest

from kubeagle.controllers.cluster.parsers.node_parser import NodeParser


class TestNodeParser:
    """Tests for NodeParser class."""

    @pytest.fixture
    def parser(self) -> NodeParser:
        """Create NodeParser instance."""
        return NodeParser()

    def test_parser_init(self, parser: NodeParser) -> None:
        """Test NodeParser initialization."""
        assert isinstance(parser, NodeParser)

    def test_get_label_value_found(self, parser: NodeParser) -> None:
        """Test _get_label_value returns value when found."""
        labels = {
            "eks.amazonaws.com/nodegroup": "my-nodegroup",
            "other-label": "other-value",
        }
        result = parser._get_label_value(
            labels, ("eks.amazonaws.com/nodegroup", "alpha.eksctl.io/nodegroup-name")
        )
        assert result == "my-nodegroup"

    def test_get_label_value_fallback(self, parser: NodeParser) -> None:
        """Test _get_label_value returns default when not found."""
        labels = {"other-label": "other-value"}
        result = parser._get_label_value(
            labels, ("eks.amazonaws.com/nodegroup", "alpha.eksctl.io/nodegroup-name")
        )
        assert result == "Unknown"

    def test_parse_node_info(self, parser: NodeParser) -> None:
        """Test parse_node_info creates NodeResourceInfo."""
        node = {
            "metadata": {
                "name": "ip-10-0-1-10.us-east-1.compute.internal",
                "labels": {
                    "eks.amazonaws.com/nodegroup": "default-worker",
                    "node.kubernetes.io/instance-type": "m5.large",
                    "topology.kubernetes.io/zone": "us-east-1a",
                },
            },
            "status": {
                "allocatable": {
                    "cpu": "2",
                    "memory": "8Gi",
                    "pods": "110",
                },
                "conditions": [
                    {"type": "Ready", "status": "True"},
                ],
                "nodeInfo": {
                    "kubeletVersion": "v1.28.0-eks-1234567",
                },
            },
            "spec": {},
        }

        result = parser.parse_node_info(node, cpu_requests=1000, memory_requests=4000000000)

        assert result.name == "ip-10-0-1-10.us-east-1.compute.internal"
        assert result.node_group == "default-worker"
        assert result.instance_type == "m5.large"
        assert result.availability_zone == "us-east-1a"
        assert result.kubelet_version == "v1.28.0-eks-1234567"
        assert result.pod_count == 0  # Not set in node info
        assert result.is_ready is True

    def test_parse_node_info_with_taints(self, parser: NodeParser) -> None:
        """Test parse_node_info handles taints."""
        node = {
            "metadata": {
                "name": "node-with-taints",
                "labels": {
                    "eks.amazonaws.com/nodegroup": "worker",
                },
            },
            "status": {
                "allocatable": {"cpu": "2", "memory": "8Gi", "pods": "110"},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
            "spec": {
                "taints": [
                    {"key": "spot", "value": "true", "effect": "NoSchedule"},
                    {"key": "gpu", "effect": "NoExecute"},
                ],
            },
        }

        result = parser.parse_node_info(node)

        assert len(result.taints) == 2
        assert result.taints[0]["key"] == "spot"
        assert result.taints[0]["effect"] == "NoSchedule"

    def test_parse_node_info_handles_conditions(self, parser: NodeParser) -> None:
        """Test parse_node_info extracts conditions."""
        node = {
            "metadata": {
                "name": "test-node",
                "labels": {},
            },
            "status": {
                "allocatable": {"cpu": "2", "memory": "8Gi", "pods": "110"},
                "conditions": [
                    {"type": "Ready", "status": "True"},
                    {"type": "MemoryPressure", "status": "True"},
                    {"type": "DiskPressure", "status": "False"},
                ],
            },
            "spec": {},
        }

        result = parser.parse_node_info(node)

        assert result.conditions["Ready"] == "True"
        assert result.conditions["MemoryPressure"] == "True"
        assert result.conditions["DiskPressure"] == "False"
        assert result.is_healthy is False  # Has MemoryPressure

    def test_parse_node_info_calculates_percentages(self, parser: NodeParser) -> None:
        """Test parse_node_info calculates resource percentages.

        parse_cpu returns cores (e.g. 2.0 for "2000m"), then * 1000 = 2000 millicores.
        memory values are converted to bytes.
        cpu_requests and memory_requests must match these units.
        """
        node = {
            "metadata": {
                "name": "test-node",
                "labels": {},
            },
            "status": {
                "allocatable": {"cpu": "2000m", "memory": "8Gi", "pods": "110"},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
            "spec": {},
        }

        # cpu_requests=1000 millicores, memory_requests=4Gi in bytes
        result = parser.parse_node_info(
            node,
            cpu_requests=1000,
            memory_requests=4 * 1024 * 1024 * 1024,
        )

        # CPU: 1000 / 2000 = 50%
        assert result.cpu_req_pct == 50.0
        # Memory: 4096 / 8192 = 50%
        assert result.mem_req_pct == 50.0

    def test_parse_node_info_handles_invalid_max_pods(self, parser: NodeParser) -> None:
        """Test parse_node_info handles invalid max_pods value."""
        node = {
            "metadata": {"name": "test-node", "labels": {}},
            "status": {
                "allocatable": {"cpu": "2", "memory": "8Gi", "pods": "invalid"},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
            "spec": {},
        }

        result = parser.parse_node_info(node)

        # Should fall back to default of 110
        assert result.max_pods == 110
