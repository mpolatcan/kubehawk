"""Controllers module for KubEagle TUI.

This module provides domain-driven controllers for fetching and analyzing
Kubernetes cluster data and Helm charts.
"""

from __future__ import annotations

# Base classes
from kubeagle.controllers.base import (
    AsyncControllerMixin,
    BaseController,
    LoadingProgress,
    WorkerResult,
)

# Charts domain
from kubeagle.controllers.charts.controller import ChartsController

# Cluster domain
from kubeagle.controllers.cluster.controller import (
    ClusterController,
    FetchStatus,
)

# Team domain
from kubeagle.controllers.team.mappers import TeamInfo, TeamMapper

# Optimizer (import from new location in models/optimization)
from kubeagle.models.optimization import OptimizerController

__all__ = [
    # Base
    "AsyncControllerMixin",
    "BaseController",
    # Domain Controllers
    "ChartsController",
    "ClusterController",
    # Cluster domain
    "FetchStatus",
    "LoadingProgress",
    # Optimizer
    "OptimizerController",
    # Team mappers
    "TeamInfo",
    "TeamMapper",
    "WorkerResult",
]
