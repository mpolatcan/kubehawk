"""Event fetcher for cluster controller - fetches event data from Kubernetes cluster."""

from __future__ import annotations

import json
import logging
import math
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from kubeagle.constants.timeouts import CLUSTER_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class EventFetcher:
    """Fetches event data from Kubernetes cluster."""

    _DEFAULT_EVENT_WINDOW_HOURS = 0.25  # 15 minutes
    _EVENT_QUERY_TIMEOUT = CLUSTER_REQUEST_TIMEOUT
    _RETRY_EVENT_QUERY_TIMEOUT = "45s"
    _EVENT_CHUNK_SIZE = 200
    _TIMEOUT_ERROR_TOKENS = (
        "timed out",
        "timeout",
        "deadline exceeded",
        "i/o timeout",
        "context deadline exceeded",
    )

    def __init__(self, run_kubectl_func: Any) -> None:
        """Initialize with kubectl runner function.

        Args:
            run_kubectl_func: Async function to run kubectl commands
        """
        self._run_kubectl = run_kubectl_func

    @staticmethod
    def _parse_iso_timestamp(timestamp: Any) -> datetime | None:
        """Parse kubernetes timestamp strings into aware datetimes."""
        if not isinstance(timestamp, str) or not timestamp:
            return None
        with suppress(ValueError, TypeError):
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return None

    @staticmethod
    def _parse_event_count(event: dict[str, Any]) -> int:
        """Parse event count across core/events.k8s.io shapes."""
        raw_value = (
            event.get("count")
            or event.get("deprecatedCount")
            or event.get("series", {}).get("count")
            or 1
        )
        with suppress(ValueError, TypeError):
            return max(1, int(raw_value))
        return 1

    @classmethod
    def _event_count_in_window(
        cls,
        event: dict[str, Any],
        *,
        now: datetime,
        max_age_seconds: float,
        event_datetime: datetime | None = None,
    ) -> int:
        """Estimate how many repeated occurrences happened within the lookback window."""
        total_count = cls._parse_event_count(event)
        if total_count <= 1:
            return total_count

        last_seen = event_datetime or cls._parse_iso_timestamp(
            event.get("series", {}).get("lastObservedTime")
            or event.get("lastTimestamp")
            or event.get("deprecatedLastTimestamp")
            or event.get("eventTime")
            or event.get("metadata", {}).get("creationTimestamp")
        )
        if last_seen is None:
            return total_count

        cutoff = now - timedelta(seconds=max_age_seconds)
        if last_seen < cutoff:
            return 0

        first_seen = cls._parse_iso_timestamp(
            event.get("firstTimestamp")
            or event.get("deprecatedFirstTimestamp")
            or event.get("eventTime")
            or event.get("metadata", {}).get("creationTimestamp")
        )
        if first_seen is None or last_seen <= first_seen:
            return total_count
        if first_seen >= cutoff:
            return total_count

        span_seconds = (last_seen - first_seen).total_seconds()
        if span_seconds <= 0:
            return total_count

        overlap_seconds = (last_seen - cutoff).total_seconds()
        scaled_count = math.ceil(total_count * (overlap_seconds / span_seconds))
        return max(1, min(total_count, scaled_count))

    @classmethod
    def _is_timeout_error(cls, error: Exception) -> bool:
        """Return True when error indicates timeout-like failure."""
        message = str(error).lower()
        return any(token in message for token in cls._TIMEOUT_ERROR_TOKENS)

    def _build_warning_events_args(self, request_timeout: str) -> tuple[str, ...]:
        """Build warning-only event query arguments."""
        return self._build_warning_events_args_for_scope(
            request_timeout=request_timeout,
            namespace=None,
        )

    def _build_warning_events_args_for_scope(
        self,
        *,
        request_timeout: str,
        namespace: str | None = None,
    ) -> tuple[str, ...]:
        """Build warning-only event query arguments for all namespaces or one namespace."""
        args: list[str] = [
            "get",
            "events",
        ]
        if namespace:
            args.extend(["-n", namespace])
        else:
            args.append("--all-namespaces")
        args.extend(
            [
                "--field-selector=type=Warning",
                f"--chunk-size={self._EVENT_CHUNK_SIZE}",
                "-o",
                "json",
                f"--request-timeout={request_timeout}",
            ]
        )
        return tuple(args)

    async def fetch_warning_events_raw(
        self,
        *,
        namespace: str | None = None,
        request_timeout: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw warning events for all namespaces or a single namespace."""
        timeout_plan: list[str] = []
        for timeout in (
            request_timeout or self._EVENT_QUERY_TIMEOUT,
            CLUSTER_REQUEST_TIMEOUT,
            self._RETRY_EVENT_QUERY_TIMEOUT,
        ):
            if timeout not in timeout_plan:
                timeout_plan.append(timeout)

        output = ""
        for attempt, timeout in enumerate(timeout_plan, start=1):
            try:
                output = await self._run_kubectl(
                    self._build_warning_events_args_for_scope(
                        request_timeout=timeout,
                        namespace=namespace,
                    )
                )
                break
            except Exception as exc:
                is_retryable = self._is_timeout_error(exc)
                has_next_attempt = attempt < len(timeout_plan)
                if is_retryable and has_next_attempt:
                    logger.warning(
                        "Event fetch timed out (attempt %s/%s with %s, namespace=%s), retrying",
                        attempt,
                        len(timeout_plan),
                        timeout,
                        namespace or "all",
                    )
                    continue
                raise

        if not output:
            return []

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            logger.exception("Error parsing events JSON")
            return []

        return data.get("items", [])

