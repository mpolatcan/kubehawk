"""Release fetcher for charts controller - fetches Helm release data from cluster."""

from __future__ import annotations

import json
import logging
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ReleaseFetcher:
    """Fetches Helm release data from Kubernetes cluster."""

    def __init__(self, run_helm_func: Any, context: str | None = None) -> None:
        """Initialize release fetcher.

        Args:
            run_helm_func: Async function to run helm commands
            context: Kubernetes context to use
        """
        self._run_helm = run_helm_func
        self.context = context

    async def fetch_releases(self) -> list[dict[str, str]]:
        """Fetch list of Helm releases from the cluster.

        Returns:
            List of release dictionaries with name and namespace.
        """
        try:
            output = await self._run_helm(("list", "-A", "-o", "json"))
            if not output:
                return []

            releases_data = json.loads(output)
            return [
                {"name": r["name"], "namespace": r["namespace"]}
                for r in releases_data
                if "name" in r and "namespace" in r
            ]
        except json.JSONDecodeError:
            logger.exception("Error fetching Helm releases")
            return []

    async def fetch_release_values_with_output(
        self, release: str, namespace: str
    ) -> tuple[dict[str, Any], str | None]:
        """Fetch live values and raw values output for a specific release.

        Args:
            release: Release name
            namespace: Release namespace

        Returns:
            Tuple of parsed values dictionary and raw command output.
        """
        try:
            output = await self._run_helm(
                ("get", "values", "--all", release, "-n", namespace, "-o", "yaml")
            )
            if not output:
                return {}, None
            values = yaml.safe_load(output)
            if isinstance(values, dict):
                return values, output
            return {}, output
        except yaml.YAMLError:
            logger.exception("Error fetching live values for %s", release)
            return {}, None
