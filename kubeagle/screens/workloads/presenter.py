"""Workloads screen presenter - runtime workload inventory and coverage metrics."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

# Pre-compiled regex for _extract_percent — avoids re-compiling on every sort comparison.
_PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")

from textual.message import Message
from textual.worker import get_current_worker

from kubeagle.controllers import ClusterController
from kubeagle.models.core.workload_inventory_info import (
    WorkloadLiveUsageSampleInfo,
)
from kubeagle.screens.workloads.config import (
    SORT_BY_NODE_CPU_LIM_AVG,
    SORT_BY_NODE_CPU_LIM_MAX,
    SORT_BY_NODE_CPU_LIM_P95,
    SORT_BY_NODE_CPU_REQ_AVG,
    SORT_BY_NODE_CPU_REQ_MAX,
    SORT_BY_NODE_CPU_REQ_P95,
    SORT_BY_NODE_CPU_USAGE_AVG,
    SORT_BY_NODE_CPU_USAGE_MAX,
    SORT_BY_NODE_CPU_USAGE_P95,
    SORT_BY_NODE_MEM_LIM_AVG,
    SORT_BY_NODE_MEM_LIM_MAX,
    SORT_BY_NODE_MEM_LIM_P95,
    SORT_BY_NODE_MEM_REQ_AVG,
    SORT_BY_NODE_MEM_REQ_MAX,
    SORT_BY_NODE_MEM_REQ_P95,
    SORT_BY_NODE_MEM_USAGE_AVG,
    SORT_BY_NODE_MEM_USAGE_MAX,
    SORT_BY_NODE_MEM_USAGE_P95,
    SORT_BY_RESTARTS,
    SORT_BY_WORKLOAD_CPU_USAGE_AVG,
    SORT_BY_WORKLOAD_CPU_USAGE_MAX,
    SORT_BY_WORKLOAD_CPU_USAGE_P95,
    SORT_BY_WORKLOAD_MEM_USAGE_AVG,
    SORT_BY_WORKLOAD_MEM_USAGE_MAX,
    SORT_BY_WORKLOAD_MEM_USAGE_P95,
    WORKLOADS_RESOURCE_BASE_COLUMNS,
)

logger = logging.getLogger(__name__)


class WorkloadsSourceLoaded(Message):
    """Message indicating one workloads data source has completed."""

    def __init__(
        self,
        key: str,
        source_namespace: str | None = None,
        *,
        completed: int | None = None,
        total: int | None = None,
        row_count: int | None = None,
        has_new_rows: bool = False,
    ) -> None:
        super().__init__()
        self.key = key
        self.source_namespace = source_namespace
        self.completed = completed
        self.total = total
        self.row_count = row_count
        self.has_new_rows = has_new_rows


class WorkloadsDataLoaded(Message):
    """Message indicating workloads data finished loading."""


class WorkloadsDataLoadFailed(Message):
    """Message indicating workloads data loading failed."""

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


class WorkloadsPresenter:
    """Presenter for WorkloadsScreen data and row formatting."""

    # Class-level lookup for usage sort fields — avoids dict recreation on every sort call.
    _USAGE_SORT_FIELDS: dict[str, str] = {
        SORT_BY_NODE_CPU_USAGE_AVG: "node_real_cpu_avg",
        SORT_BY_NODE_CPU_REQ_AVG: "cpu_req_util_avg",
        SORT_BY_NODE_CPU_LIM_AVG: "cpu_lim_util_avg",
        SORT_BY_NODE_CPU_USAGE_MAX: "node_real_cpu_max",
        SORT_BY_NODE_CPU_REQ_MAX: "cpu_req_util_max",
        SORT_BY_NODE_CPU_LIM_MAX: "cpu_lim_util_max",
        SORT_BY_NODE_CPU_USAGE_P95: "node_real_cpu_p95",
        SORT_BY_NODE_CPU_REQ_P95: "cpu_req_util_p95",
        SORT_BY_NODE_CPU_LIM_P95: "cpu_lim_util_p95",
        SORT_BY_NODE_MEM_USAGE_AVG: "node_real_memory_avg",
        SORT_BY_NODE_MEM_REQ_AVG: "mem_req_util_avg",
        SORT_BY_NODE_MEM_LIM_AVG: "mem_lim_util_avg",
        SORT_BY_NODE_MEM_USAGE_MAX: "node_real_memory_max",
        SORT_BY_NODE_MEM_REQ_MAX: "mem_req_util_max",
        SORT_BY_NODE_MEM_LIM_MAX: "mem_lim_util_max",
        SORT_BY_NODE_MEM_USAGE_P95: "node_real_memory_p95",
        SORT_BY_NODE_MEM_REQ_P95: "mem_req_util_p95",
        SORT_BY_NODE_MEM_LIM_P95: "mem_lim_util_p95",
        SORT_BY_WORKLOAD_CPU_USAGE_AVG: "pod_real_cpu_avg",
        SORT_BY_WORKLOAD_CPU_USAGE_MAX: "pod_real_cpu_max",
        SORT_BY_WORKLOAD_CPU_USAGE_P95: "pod_real_cpu_p95",
        SORT_BY_WORKLOAD_MEM_USAGE_AVG: "pod_real_memory_avg",
        SORT_BY_WORKLOAD_MEM_USAGE_MAX: "pod_real_memory_max",
        SORT_BY_WORKLOAD_MEM_USAGE_P95: "pod_real_memory_p95",
    }

    def __init__(self, screen: Any) -> None:
        self._screen = screen
        self._is_loading = False
        self._error_message = ""
        self._force_refresh_next_load = False
        self._partial_errors: dict[str, str] = {}
        self._loaded_keys: set[str] = set()
        self._data: dict[str, Any] = {
            "all_workloads": [],
        }
        # Reusable controller instance — avoids re-creating ClusterController
        # (and re-resolving context) for each fetch_live_usage_sample call.
        self._cached_ctrl: ClusterController | None = None

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def error_message(self) -> str:
        return self._error_message

    @property
    def partial_errors(self) -> dict[str, str]:
        return self._partial_errors

    @property
    def loaded_keys(self) -> set[str]:
        return set(self._loaded_keys)

    def load_data(self, *, force_refresh: bool = False) -> None:
        """Start background workloads loading."""
        if force_refresh:
            self._force_refresh_next_load = True
        self._is_loading = True
        self._error_message = ""
        start_worker = getattr(self._screen, "start_worker", None)
        if callable(start_worker):
            start_worker(self._load_workloads_data_worker, name="workloads-data", exclusive=True)
            return
        self._screen.run_worker(
            self._load_workloads_data_worker,
            name="workloads-data",
            exclusive=True,
        )

    @staticmethod
    def _friendly_error(error: BaseException) -> str:
        msg = str(error)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            return "Connection timed out"
        if "connection refused" in msg.lower():
            return "Connection refused"
        if "not found" in msg.lower():
            return "Resource not found"
        if len(msg) > 80:
            return msg[:77] + "..."
        return msg or "Unknown error"

    async def _load_workloads_data_worker(self) -> None:
        """Worker: load workloads-related sources concurrently."""
        worker = get_current_worker()
        force_refresh = self._force_refresh_next_load
        self._force_refresh_next_load = False

        def msg(text: str) -> None:
            if not bool(getattr(self._screen, "is_current", True)):
                return
            self._screen.call_later(self._screen._update_loading_message, text)

        if worker.is_cancelled:
            self._is_loading = False
            return

        try:
            self._partial_errors.clear()
            self._loaded_keys.clear()
            self._data["all_workloads"] = []

            app = self._screen.app
            configured_context = (
                getattr(self._screen, "context", None)
                or getattr(app, "context", None)
            )
            current_context = await ClusterController.resolve_current_context_async()
            context = current_context or configured_context

            if force_refresh:
                ClusterController.clear_global_command_cache(context=context)
            ctrl = ClusterController(context=context)
            # Cache controller for reuse by fetch_live_usage_sample
            self._cached_ctrl = ctrl

            msg("Loading workloads...")
            streamed_row_count = 0

            def _on_namespace_update(
                partial_rows: list[Any],
                completed: int,
                total: int,
            ) -> None:
                nonlocal streamed_row_count
                current_row_count = len(partial_rows)
                has_new_rows = current_row_count > streamed_row_count
                if has_new_rows:
                    self._data["all_workloads"] = list(partial_rows)
                    streamed_row_count = current_row_count
                msg(
                    "Loading workloads "
                    f"({completed}/{total} namespaces, {current_row_count} workloads)..."
                )
                if has_new_rows and bool(getattr(self._screen, "is_current", True)):
                    self._screen.call_later(
                        lambda: self._screen.post_message(
                            WorkloadsSourceLoaded(
                                "all_workloads",
                                source_namespace=None,
                                completed=completed,
                                total=total,
                                row_count=current_row_count,
                                has_new_rows=has_new_rows,
                            )
                        )
                    )

            all_workloads = await ctrl.fetch_workload_inventory(
                on_namespace_update=_on_namespace_update,
                enrich_runtime_stats=True,
            )
            self._partial_errors.update(ctrl.get_last_nonfatal_warnings())
            self._data["all_workloads"] = all_workloads
            self._loaded_keys.add("all_workloads")
            msg("Loading workloads (1/1)...")
            if bool(getattr(self._screen, "is_current", True)):
                self._screen.call_later(
                    lambda: self._screen.post_message(
                        WorkloadsSourceLoaded(
                            "all_workloads",
                            source_namespace=None,
                            completed=1,
                            total=1,
                            row_count=len(all_workloads),
                            has_new_rows=len(all_workloads) > streamed_row_count,
                        )
                    )
                )
            self._screen.call_later(lambda: self._screen.post_message(WorkloadsDataLoaded()))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._error_message = self._friendly_error(exc)
            logger.exception("Failed to load workloads data")
            self._screen.call_later(
                lambda: self._screen.post_message(
                    WorkloadsDataLoadFailed(self._error_message)
                )
            )
        finally:
            self._is_loading = False

    def get_all_workloads(self) -> list:
        return self._data.get("all_workloads", [])

    async def fetch_live_usage_sample(self, workload: Any) -> WorkloadLiveUsageSampleInfo:
        """Fetch one targeted live usage sample for a selected workload.

        Reuses the controller instance from the last data load to avoid
        re-instantiation and redundant context resolution subprocess calls.
        """
        ctrl = self._cached_ctrl
        if ctrl is None:
            # Fallback: create a new controller if none cached yet
            app = getattr(self._screen, "app", None)
            configured_context = (
                getattr(self._screen, "context", None)
                or getattr(app, "context", None)
            )
            current_context = await ClusterController.resolve_current_context_async()
            context = current_context or configured_context
            ctrl = ClusterController(context=context)
            self._cached_ctrl = ctrl
        return await ctrl.fetch_workload_live_usage_sample(
            namespace=str(getattr(workload, "namespace", "") or ""),
            workload_kind=str(getattr(workload, "kind", "") or ""),
            workload_name=str(getattr(workload, "name", "") or ""),
        )

    @staticmethod
    def _ratio(request: float, limit: float) -> float | None:
        if request <= 0 or limit <= 0:
            return None
        return limit / request

    @staticmethod
    def _format_cpu(value: float) -> str:
        return f"{value:.0f}m" if value > 0 else "-"

    @staticmethod
    def _format_memory(value: float) -> str:
        if value <= 0:
            return "-"
        if value >= 1024 * 1024 * 1024:
            return f"{value / (1024 * 1024 * 1024):.1f}Gi"
        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.1f}Mi"
        if value >= 1024:
            return f"{value / 1024:.1f}Ki"
        return f"{value:.0f}B"

    @classmethod
    def _format_ratio(cls, request: float, limit: float) -> str:
        ratio = cls._ratio(request, limit)
        if ratio is None:
            return "-"
        if ratio >= 4.0:
            return f"[bold #ff3b30]{ratio:.1f}×[/bold #ff3b30]"
        if ratio >= 2.0:
            return f"[bold #ff9f0a]{ratio:.1f}×[/bold #ff9f0a]"
        return f"{ratio:.1f}×"

    @classmethod
    def _format_text_by_status(cls, text: str, status_text: str) -> str:
        lowered_status = status_text.lower()
        if lowered_status in {"ready", "running", "succeeded", "idle"}:
            return f"[#30d158]{text}[/#30d158]"
        if lowered_status in {"progressing", "pending", "scaledtozero", "suspended"}:
            return f"[#ff9f0a]{text}[/#ff9f0a]"
        if lowered_status in {"notready", "failed"}:
            return f"[bold #ff3b30]{text}[/bold #ff3b30]"
        return text

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _format_utilization_value(raw_value: Any) -> str:
        """Format utilization percentages with severity colors."""
        value = str(raw_value or "-").strip()
        if value == "-":
            return "-"
        try:
            numeric = float(value.rstrip("%").strip())
        except ValueError:
            return value

        if numeric >= 100:
            return f"[bold #ff3b30]{value}[/bold #ff3b30]"
        if numeric >= 80:
            return f"[bold #ff9f0a]{value}[/bold #ff9f0a]"
        if numeric >= 50:
            return f"[#ffd60a]{value}[/#ffd60a]"
        if numeric > 0:
            return f"[#30d158]{value}[/#30d158]"
        return f"[dim]{value}[/dim]"

    @staticmethod
    def _format_compact_pair(left: Any, right: Any) -> str:
        """Render compact pair text as left/right for table columns."""
        left_text = str(left or "-").strip()
        right_text = str(right or "-").strip()
        if left_text == "-" and right_text == "-":
            return "-"
        return f"{left_text} / {right_text}"

    @staticmethod
    def _format_restart_count(value: Any, restart_reason_counts: Any = None) -> str:
        """Render restart count and include reason breakdown in the same cell."""
        try:
            restart_count = int(value or 0)
        except (TypeError, ValueError):
            return "-"
        if restart_count <= 0:
            restart_text = "0"
        elif restart_count < 5:
            restart_text = f"[#ff9f0a]{restart_count}[/#ff9f0a]"
        else:
            restart_text = f"[bold #ff3b30]{restart_count}[/bold #ff3b30]"

        reason_text = WorkloadsPresenter._format_restart_reason_counts(restart_reason_counts)
        if reason_text == "-":
            return restart_text
        return f"{restart_text} [dim]({reason_text})[/dim]"

    @staticmethod
    def _format_restart_reason_counts(value: Any) -> str:
        """Render compact restart reason summary as `reason:count` entries."""
        if not isinstance(value, dict):
            return "-"

        normalized: list[tuple[str, int]] = []
        for reason, count in value.items():
            reason_text = str(reason or "").strip()
            if not reason_text:
                continue
            try:
                numeric_count = int(count)
            except (TypeError, ValueError):
                continue
            if numeric_count <= 0:
                continue
            normalized.append((reason_text, numeric_count))

        if not normalized:
            return "-"

        normalized.sort(key=lambda item: (-item[1], item[0].lower()))
        max_display = 3
        parts = [f"{reason}:{count}" for reason, count in normalized[:max_display]]
        if len(normalized) > max_display:
            parts.append(f"+{len(normalized) - max_display} more")
        return ", ".join(parts)

    @staticmethod
    def _format_desired_ready_badge(desired_raw: Any, ready_raw: Any) -> str:
        """Render desired/ready badge for the Name column."""
        desired_text = str(desired_raw) if desired_raw is not None else "-"
        ready_text = str(ready_raw) if ready_raw is not None else "-"
        badge_text = f"[{desired_text}/{ready_text}]"

        try:
            desired = int(desired_text)
            ready = int(ready_text)
        except (TypeError, ValueError):
            return f"[dim]{badge_text}[/dim]"

        if desired <= 0 and ready <= 0:
            return f"[dim]{badge_text}[/dim]"
        if desired > 0 and ready >= desired:
            return f"[#30d158]{badge_text}[/#30d158]"
        if ready > 0:
            return f"[#ff9f0a]{badge_text}[/#ff9f0a]"
        return f"[bold #ff3b30]{badge_text}[/bold #ff3b30]"

    @classmethod
    def _format_req_lim_with_ratio(cls, request_text: str, limit_text: str, ratio_text: str) -> str:
        """Render request/limit text with inline ratio for compact columns."""
        base_text = cls._format_compact_pair(request_text, limit_text)
        if ratio_text == "-" or base_text == "-":
            return base_text
        return f"{base_text} [dim]·[/dim] {ratio_text}"

    @staticmethod
    def _format_runtime_cpu(value: Any) -> str:
        """Format runtime CPU usage (millicores)."""
        if value is None:
            return "-"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "-"
        if numeric <= 0:
            return "0m"
        return f"{numeric:.0f}m"

    @staticmethod
    def _format_runtime_memory(value: Any) -> str:
        """Format runtime memory usage (bytes)."""
        if value is None:
            return "-"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "-"
        if numeric <= 0:
            return "0B"
        if numeric >= 1024 * 1024 * 1024:
            return f"{numeric / (1024 * 1024 * 1024):.1f}Gi"
        if numeric >= 1024 * 1024:
            return f"{numeric / (1024 * 1024):.1f}Mi"
        if numeric >= 1024:
            return f"{numeric / 1024:.1f}Ki"
        return f"{numeric:.0f}B"

    @classmethod
    def _format_percentage(cls, value: Any) -> str:
        if value is None:
            return "-"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "-"
        return cls._format_util_percentage(numeric)

    @classmethod
    def _format_util_percentage(cls, value: float) -> str:
        if value <= 0:
            return "0%"
        if value < 1:
            return f"{value:.2f}%"
        if value < 10:
            return f"{value:.1f}%"
        return f"{value:.0f}%"

    @staticmethod
    def _format_compact_triplet(avg_value: Any, max_value: Any, p95_value: Any) -> str:
        avg_text = str(avg_value or "-").strip()
        max_text = str(max_value or "-").strip()
        p95_text = str(p95_value or "-").strip()
        if avg_text == "-" and max_text == "-" and p95_text == "-":
            return "-"
        return f"{avg_text} / {max_text} / {p95_text}"

    @staticmethod
    def _extract_percent(raw_value: Any) -> float | None:
        value = str(raw_value or "-").strip()
        if value == "-":
            return None

        match = _PERCENT_RE.search(value)
        if not match:
            try:
                return float(value.rstrip("%").strip())
            except ValueError:
                return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _format_usage_value(raw_value: Any) -> str:
        """Format usage values with severity colors using the embedded percentage."""
        value = str(raw_value or "-").strip()
        if value == "-":
            return "-"

        numeric = WorkloadsPresenter._extract_percent(value)
        if numeric is None:
            return value

        if numeric >= 100:
            return f"[bold #ff3b30]{value}[/bold #ff3b30]"
        if numeric >= 80:
            return f"[bold #ff9f0a]{value}[/bold #ff9f0a]"
        if numeric >= 50:
            return f"[#ffd60a]{value}[/#ffd60a]"
        if numeric > 0:
            return f"[#30d158]{value}[/#30d158]"
        return f"[dim]{value}[/dim]"

    @staticmethod
    def _format_usage_with_percentage(usage_text: str, pct_text: str) -> str:
        usage = str(usage_text or "-").strip()
        pct = str(pct_text or "-").strip()
        if usage == "-" and pct == "-":
            return "-"
        if usage == "-":
            return f"- ({pct})"
        if pct == "-":
            return usage
        return f"{usage} ({pct})"

    def _filter_workloads(
        self,
        *,
        workload_kind: str | None,
        search_query: str,
        workload_view_filter: str | None = None,
        name_filter_values: set[str] | None = None,
        kind_filter_values: set[str] | None = None,
        helm_release_filter_values: set[str] | None = None,
        namespace_filter_values: set[str] | None = None,
        status_filter_values: set[str] | None = None,
        pdb_filter_values: set[str] | None = None,
    ) -> list[Any]:
        workloads = list(self.get_all_workloads())
        if workload_kind:
            expected = workload_kind.lower()
            workloads = [
                workload
                for workload in workloads
                if self._normalize_text(getattr(workload, "kind", "")) == expected
            ]
        view_filter = self._normalize_text(workload_view_filter)
        if view_filter in {"extreme_ratios", "extreme_ratio", "extreme"}:
            workloads = [workload for workload in workloads if self._is_extreme_ratio(workload)]
        elif view_filter in {"single_replica", "single"}:
            workloads = [workload for workload in workloads if self._is_single_replica(workload)]
        elif view_filter in {"missing_pdb", "no_pdb", "without_pdb"}:
            workloads = [
                workload
                for workload in workloads
                if not bool(getattr(workload, "has_pdb", False))
            ]

        name_filters = {self._normalize_text(value) for value in (name_filter_values or set())}
        if name_filters:
            workloads = [
                workload
                for workload in workloads
                if self._normalize_text(getattr(workload, "name", "")) in name_filters
            ]

        kind_filters = {self._normalize_text(value) for value in (kind_filter_values or set())}
        if kind_filters:
            workloads = [
                workload
                for workload in workloads
                if self._normalize_text(getattr(workload, "kind", "")) in kind_filters
            ]

        helm_release_filters = {
            self._normalize_text(value) for value in (helm_release_filter_values or set())
        }
        if helm_release_filters:
            include_with_helm = any(
                value in {"with_helm", "has_helm", "helm", "yes", "true"}
                for value in helm_release_filters
            )
            include_without_helm = any(
                value in {"without_helm", "no_helm", "no-helm", "no", "false"}
                for value in helm_release_filters
            )
            exact_release_filters = {
                value
                for value in helm_release_filters
                if value
                not in {
                    "with_helm",
                    "has_helm",
                    "helm",
                    "yes",
                    "true",
                    "without_helm",
                    "no_helm",
                    "no-helm",
                    "no",
                    "false",
                }
            }

            def _helm_release_key(workload: Any) -> str:
                return self._normalize_text(
                    str(getattr(workload, "helm_release", "") or "").strip() or "-"
                )

            def _has_helm_release(workload: Any) -> bool:
                return _helm_release_key(workload) != "-"

            if exact_release_filters:
                workloads = [
                    workload
                    for workload in workloads
                    if _helm_release_key(workload) in exact_release_filters
                ]

            if include_with_helm != include_without_helm:
                workloads = [
                    workload
                    for workload in workloads
                    if _has_helm_release(workload) == include_with_helm
                ]

        namespace_filters = {
            self._normalize_text(value) for value in (namespace_filter_values or set())
        }
        if namespace_filters:
            workloads = [
                workload
                for workload in workloads
                if self._normalize_text(getattr(workload, "namespace", "")) in namespace_filters
            ]

        status_filters = {
            self._normalize_text(value) for value in (status_filter_values or set())
        }
        if status_filters:
            workloads = [
                workload
                for workload in workloads
                if self._normalize_text(getattr(workload, "status", "")) in status_filters
            ]

        pdb_filters = {
            self._normalize_text(value) for value in (pdb_filter_values or set())
        }
        if pdb_filters:
            include_with_pdb = any(
                value in {"with_pdb", "yes", "true", "has_pdb"} for value in pdb_filters
            )
            include_without_pdb = any(
                value in {"without_pdb", "no", "false", "missing_pdb"} for value in pdb_filters
            )
            if include_with_pdb != include_without_pdb:
                workloads = [
                    workload
                    for workload in workloads
                    if bool(getattr(workload, "has_pdb", False)) == include_with_pdb
                ]

        query = search_query.strip().lower()
        if not query:
            return workloads

        filtered: list[Any] = []
        for workload in workloads:
            haystack = " ".join(
                [
                    self._normalize_text(getattr(workload, "namespace", "")),
                    self._normalize_text(getattr(workload, "kind", "")),
                    self._normalize_text(getattr(workload, "name", "")),
                    self._normalize_text(getattr(workload, "helm_release", "")),
                    self._normalize_text(getattr(workload, "status", "")),
                ]
            )
            if query in haystack:
                filtered.append(workload)
        return filtered

    def _sort_workloads(
        self,
        workloads: list[Any],
        *,
        sort_by: str,
        descending: bool,
    ) -> list[Any]:
        if not workloads:
            return []

        # Check class-level usage sort fields first to avoid repeated dict
        # lookups inside the per-workload closure.
        usage_attr = self._USAGE_SORT_FIELDS.get(sort_by)

        def _value(workload: Any) -> str | float | None:
            if sort_by == "namespace":
                return self._normalize_text(getattr(workload, "namespace", ""))
            if sort_by == "kind":
                return self._normalize_text(getattr(workload, "kind", ""))
            if sort_by == "cpu_request":
                cpu_request = float(getattr(workload, "cpu_request", 0.0) or 0.0)
                return cpu_request if cpu_request > 0 else None
            if sort_by == "cpu_limit":
                cpu_limit = float(getattr(workload, "cpu_limit", 0.0) or 0.0)
                return cpu_limit if cpu_limit > 0 else None
            if sort_by == "cpu_ratio":
                cpu_request = float(getattr(workload, "cpu_request", 0.0) or 0.0)
                cpu_limit = float(getattr(workload, "cpu_limit", 0.0) or 0.0)
                return self._ratio(cpu_request, cpu_limit)
            if sort_by == "memory_request":
                memory_request = float(getattr(workload, "memory_request", 0.0) or 0.0)
                return memory_request if memory_request > 0 else None
            if sort_by == "memory_limit":
                memory_limit = float(getattr(workload, "memory_limit", 0.0) or 0.0)
                return memory_limit if memory_limit > 0 else None
            if sort_by == "memory_ratio":
                memory_request = float(getattr(workload, "memory_request", 0.0) or 0.0)
                memory_limit = float(getattr(workload, "memory_limit", 0.0) or 0.0)
                return self._ratio(memory_request, memory_limit)
            if sort_by == SORT_BY_RESTARTS:
                try:
                    return float(int(getattr(workload, "restart_count", 0) or 0))
                except (TypeError, ValueError):
                    return None
            if sort_by == "status":
                return self._normalize_text(getattr(workload, "status", ""))
            if usage_attr is not None:
                return self._extract_percent(
                    getattr(workload, usage_attr, None)
                )
            return self._normalize_text(getattr(workload, "name", ""))

        present: list[tuple[Any, str | float]] = []
        missing: list[Any] = []

        for workload in workloads:
            value = _value(workload)
            if value is None:
                missing.append(workload)
            else:
                present.append((workload, value))

        present.sort(key=lambda item: item[1], reverse=descending)
        return [workload for workload, _ in present] + missing

    @classmethod
    def _is_extreme_ratio(cls, workload: Any) -> bool:
        cpu_request = float(getattr(workload, "cpu_request", 0.0) or 0.0)
        cpu_limit = float(getattr(workload, "cpu_limit", 0.0) or 0.0)
        memory_request = float(getattr(workload, "memory_request", 0.0) or 0.0)
        memory_limit = float(getattr(workload, "memory_limit", 0.0) or 0.0)

        cpu_ratio = cls._ratio(cpu_request, cpu_limit)
        memory_ratio = cls._ratio(memory_request, memory_limit)
        return bool(
            (cpu_ratio is not None and cpu_ratio >= 4.0)
            or (memory_ratio is not None and memory_ratio >= 4.0)
        )

    @staticmethod
    def _is_single_replica(workload: Any) -> bool:
        desired_raw = getattr(workload, "desired_replicas", None)
        if desired_raw is None:
            return False
        try:
            return int(desired_raw) == 1
        except (TypeError, ValueError):
            return False

    def _format_workload_row(
        self,
        workload: Any,
        *,
        columns: list[tuple[str, int]],
        _needed_columns: frozenset[str] | None = None,
    ) -> tuple[str, ...]:
        """Format a single workload into a row tuple, computing only needed columns.

        When ``_needed_columns`` is provided (a frozenset of column name strings),
        only columns present in that set are computed.  This avoids the cost of
        formatting expensive node/workload usage triplets for the 4 base-column
        tabs that never display them.
        """
        needed = _needed_columns
        cells: dict[str, str] = {}

        # --- Base columns (cheap, always computed) ---
        cells["Namespace"] = str(getattr(workload, "namespace", ""))
        cells["Kind"] = str(getattr(workload, "kind", ""))

        desired_raw = getattr(workload, "desired_replicas", None)
        ready_raw = getattr(workload, "ready_replicas", None)
        workload_name = str(getattr(workload, "name", "") or "")
        helm_release_raw = str(getattr(workload, "helm_release", "") or "").strip()
        has_helm_release = bool(helm_release_raw)
        status_text = str(getattr(workload, "status", "Unknown") or "Unknown")
        name_prefix = f"{self._format_text_by_status('⎈', status_text)} " if has_helm_release else ""
        styled_name = self._format_text_by_status(workload_name, status_text)
        desired_ready_badge = self._format_desired_ready_badge(desired_raw, ready_raw)
        cells["Name"] = f"{name_prefix}{styled_name} [dim]·[/dim] {desired_ready_badge}"

        cells["Restarts"] = self._format_restart_count(
            getattr(workload, "restart_count", 0),
            getattr(workload, "restart_reason_counts", {}),
        )

        cpu_request = float(getattr(workload, "cpu_request", 0.0) or 0.0)
        cpu_limit = float(getattr(workload, "cpu_limit", 0.0) or 0.0)
        memory_request = float(getattr(workload, "memory_request", 0.0) or 0.0)
        memory_limit = float(getattr(workload, "memory_limit", 0.0) or 0.0)
        cells["CPU R/L"] = self._format_req_lim_with_ratio(
            self._format_cpu(cpu_request),
            self._format_cpu(cpu_limit),
            self._format_ratio(cpu_request, cpu_limit),
        )
        cells["Mem R/L"] = self._format_req_lim_with_ratio(
            self._format_memory(memory_request),
            self._format_memory(memory_limit),
            self._format_ratio(memory_request, memory_limit),
        )

        has_pdb = bool(getattr(workload, "has_pdb", False))
        cells["PDB"] = "[#30d158]Yes[/#30d158]" if has_pdb else "[bold #ff3b30]No[/bold #ff3b30]"

        # --- Expensive node/workload usage columns (only for Node Analysis tab) ---
        if needed is None or "Nodes" in needed:
            cells["Nodes"] = str(getattr(workload, "assigned_nodes", "-") or "-")

        if needed is None or "Node CPU Usage/Req/Lim Avg" in needed:
            cells["Node CPU Usage/Req/Lim Avg"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "node_real_cpu_avg", "-")),
                self._format_utilization_value(getattr(workload, "cpu_req_util_avg", "-")),
                self._format_utilization_value(getattr(workload, "cpu_lim_util_avg", "-")),
            )
        if needed is None or "Node CPU Usage/Req/Lim Max" in needed:
            cells["Node CPU Usage/Req/Lim Max"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "node_real_cpu_max", "-")),
                self._format_utilization_value(getattr(workload, "cpu_req_util_max", "-")),
                self._format_utilization_value(getattr(workload, "cpu_lim_util_max", "-")),
            )
        if needed is None or "Node CPU Usage/Req/Lim P95" in needed:
            cells["Node CPU Usage/Req/Lim P95"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "node_real_cpu_p95", "-")),
                self._format_utilization_value(getattr(workload, "cpu_req_util_p95", "-")),
                self._format_utilization_value(getattr(workload, "cpu_lim_util_p95", "-")),
            )
        if needed is None or "Node Mem Usage/Req/Lim Avg" in needed:
            cells["Node Mem Usage/Req/Lim Avg"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "node_real_memory_avg", "-")),
                self._format_utilization_value(getattr(workload, "mem_req_util_avg", "-")),
                self._format_utilization_value(getattr(workload, "mem_lim_util_avg", "-")),
            )
        if needed is None or "Node Mem Usage/Req/Lim Max" in needed:
            cells["Node Mem Usage/Req/Lim Max"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "node_real_memory_max", "-")),
                self._format_utilization_value(getattr(workload, "mem_req_util_max", "-")),
                self._format_utilization_value(getattr(workload, "mem_lim_util_max", "-")),
            )
        if needed is None or "Node Mem Usage/Req/Lim P95" in needed:
            cells["Node Mem Usage/Req/Lim P95"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "node_real_memory_p95", "-")),
                self._format_utilization_value(getattr(workload, "mem_req_util_p95", "-")),
                self._format_utilization_value(getattr(workload, "mem_lim_util_p95", "-")),
            )
        if needed is None or "Workload CPU Usage Avg/Max/P95" in needed:
            cells["Workload CPU Usage Avg/Max/P95"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "pod_real_cpu_avg", "-")),
                self._format_usage_value(getattr(workload, "pod_real_cpu_max", "-")),
                self._format_usage_value(getattr(workload, "pod_real_cpu_p95", "-")),
            )
        if needed is None or "Workload Mem Usage Avg/Max/P95" in needed:
            cells["Workload Mem Usage Avg/Max/P95"] = self._format_compact_triplet(
                self._format_usage_value(getattr(workload, "pod_real_memory_avg", "-")),
                self._format_usage_value(getattr(workload, "pod_real_memory_max", "-")),
                self._format_usage_value(getattr(workload, "pod_real_memory_p95", "-")),
            )

        return tuple(cells.get(column_name, "-") for column_name, _ in columns)

    def get_resource_rows(
        self,
        *,
        workload_kind: str | None = None,
        search_query: str = "",
        workload_view_filter: str | None = None,
        columns: list[tuple[str, int]] | None = None,
        sort_by: str = "name",
        descending: bool = False,
        name_filter_values: set[str] | None = None,
        kind_filter_values: set[str] | None = None,
        helm_release_filter_values: set[str] | None = None,
        namespace_filter_values: set[str] | None = None,
        status_filter_values: set[str] | None = None,
        pdb_filter_values: set[str] | None = None,
    ) -> list[tuple[str, ...]]:
        effective_columns = columns or WORKLOADS_RESOURCE_BASE_COLUMNS
        workloads = self._filter_workloads(
            workload_kind=workload_kind,
            search_query=search_query,
            workload_view_filter=workload_view_filter,
            name_filter_values=name_filter_values,
            kind_filter_values=kind_filter_values,
            helm_release_filter_values=helm_release_filter_values,
            namespace_filter_values=namespace_filter_values,
            status_filter_values=status_filter_values,
            pdb_filter_values=pdb_filter_values,
        )
        workloads = self._sort_workloads(workloads, sort_by=sort_by, descending=descending)
        return self.format_workload_rows(workloads, columns=effective_columns)

    def format_workload_rows(
        self,
        workloads: list[Any],
        *,
        columns: list[tuple[str, int]] | None = None,
    ) -> list[tuple[str, ...]]:
        effective_columns = columns or WORKLOADS_RESOURCE_BASE_COLUMNS
        # Build a frozenset of needed column names so _format_workload_row
        # can skip computing expensive columns that aren't displayed.
        needed = frozenset(name for name, _ in effective_columns)
        return [
            self._format_workload_row(
                workload,
                columns=effective_columns,
                _needed_columns=needed,
            )
            for workload in workloads
        ]

    def get_filtered_workloads(
        self,
        *,
        workload_kind: str | None = None,
        search_query: str = "",
        workload_view_filter: str | None = None,
        sort_by: str = "name",
        descending: bool = False,
        name_filter_values: set[str] | None = None,
        kind_filter_values: set[str] | None = None,
        helm_release_filter_values: set[str] | None = None,
        namespace_filter_values: set[str] | None = None,
        status_filter_values: set[str] | None = None,
        pdb_filter_values: set[str] | None = None,
    ) -> list[Any]:
        workloads = self._filter_workloads(
            workload_kind=workload_kind,
            search_query=search_query,
            workload_view_filter=workload_view_filter,
            name_filter_values=name_filter_values,
            kind_filter_values=kind_filter_values,
            helm_release_filter_values=helm_release_filter_values,
            namespace_filter_values=namespace_filter_values,
            status_filter_values=status_filter_values,
            pdb_filter_values=pdb_filter_values,
        )
        return self._sort_workloads(workloads, sort_by=sort_by, descending=descending)

    def get_scoped_workload_count(
        self,
        *,
        workload_kind: str | None = None,
        workload_view_filter: str | None = None,
        name_filter_values: set[str] | None = None,
        kind_filter_values: set[str] | None = None,
        helm_release_filter_values: set[str] | None = None,
        namespace_filter_values: set[str] | None = None,
        status_filter_values: set[str] | None = None,
        pdb_filter_values: set[str] | None = None,
    ) -> int:
        """Return count after non-search filters to avoid unnecessary row formatting/sorting."""
        return len(
            self._filter_workloads(
                workload_kind=workload_kind,
                search_query="",
                workload_view_filter=workload_view_filter,
                name_filter_values=name_filter_values,
                kind_filter_values=kind_filter_values,
                helm_release_filter_values=helm_release_filter_values,
                namespace_filter_values=namespace_filter_values,
                status_filter_values=status_filter_values,
                pdb_filter_values=pdb_filter_values,
            )
        )

    def build_resource_summary_from_filtered(
        self,
        *,
        filtered_workloads: list[Any],
        scoped_total: int,
    ) -> dict[str, str]:
        """Build summary metrics from pre-filtered workloads to avoid duplicate filtering."""
        shown = len(filtered_workloads)
        total = max(scoped_total, shown)
        missing_cpu_request = sum(
            1
            for workload in filtered_workloads
            if float(getattr(workload, "cpu_request", 0.0) or 0.0) <= 0
        )
        missing_memory_request = sum(
            1
            for workload in filtered_workloads
            if float(getattr(workload, "memory_request", 0.0) or 0.0) <= 0
        )
        extreme_ratios = sum(
            1
            for workload in filtered_workloads
            if self._is_extreme_ratio(workload)
        )
        with_pdb = sum(
            1
            for workload in filtered_workloads
            if bool(getattr(workload, "has_pdb", False))
        )
        pdb_coverage = (with_pdb / shown * 100.0) if shown > 0 else 0.0
        return {
            "shown": str(shown),
            "total": str(total),
            "shown_total": f"{shown}/{total}",
            "missing_cpu_request": str(missing_cpu_request),
            "missing_memory_request": str(missing_memory_request),
            "extreme_ratios": str(extreme_ratios),
            "pdb_coverage": f"{pdb_coverage:.0f}%",
        }

    def get_assigned_node_detail_rows(self, workload: Any) -> list[tuple[str, ...]]:
        details = list(getattr(workload, "assigned_node_details", []) or [])
        return [
            (
                str(getattr(detail, "node_name", "-") or "-"),
                str(getattr(detail, "node_group", "Unknown") or "Unknown"),
                str(int(getattr(detail, "workload_pod_count_on_node", 0) or 0)),
                self._format_percentage(getattr(detail, "node_cpu_req_pct", None)),
                self._format_percentage(getattr(detail, "node_cpu_lim_pct", None)),
                self._format_percentage(getattr(detail, "node_mem_req_pct", None)),
                self._format_percentage(getattr(detail, "node_mem_lim_pct", None)),
                self._format_usage_with_percentage(
                    self._format_runtime_cpu(
                        getattr(detail, "node_real_cpu_mcores", None)
                    ),
                    self._format_percentage(
                        getattr(detail, "node_real_cpu_pct_of_allocatable", None)
                    ),
                ),
                self._format_usage_with_percentage(
                    self._format_runtime_memory(
                        getattr(detail, "node_real_memory_bytes", None)
                    ),
                    self._format_percentage(
                        getattr(detail, "node_real_memory_pct_of_allocatable", None)
                    ),
                ),
                self._format_usage_with_percentage(
                    self._format_runtime_cpu(
                        getattr(detail, "workload_pod_real_cpu_mcores_on_node", None)
                    ),
                    self._format_percentage(
                        getattr(
                            detail,
                            "workload_pod_real_cpu_pct_of_node_allocatable",
                            None,
                        )
                    ),
                ),
                self._format_usage_with_percentage(
                    self._format_runtime_memory(
                        getattr(detail, "workload_pod_real_memory_bytes_on_node", None)
                    ),
                    self._format_percentage(
                        getattr(
                            detail,
                            "workload_pod_real_memory_pct_of_node_allocatable",
                            None,
                        )
                    ),
                ),
            )
            for detail in details
        ]

    def get_assigned_pod_detail_rows(self, workload: Any) -> list[tuple[str, ...]]:
        details = list(getattr(workload, "assigned_pod_details", []) or [])
        rows: list[tuple[str, ...]] = []
        for detail in details:
            restart_reason = str(getattr(detail, "restart_reason", "-") or "-")
            last_exit_code = getattr(detail, "last_exit_code", None)
            rows.append(
                (
                    str(getattr(detail, "namespace", "-") or "-"),
                    str(getattr(detail, "pod_name", "-") or "-"),
                    str(getattr(detail, "node_name", "-") or "-"),
                    str(getattr(detail, "pod_phase", "Unknown") or "Unknown"),
                    self._format_usage_with_percentage(
                        self._format_runtime_cpu(
                            getattr(detail, "pod_real_cpu_mcores", None)
                        ),
                        self._format_percentage(
                            getattr(detail, "pod_cpu_pct_of_node_allocatable", None)
                        ),
                    ),
                    self._format_usage_with_percentage(
                        self._format_runtime_memory(
                            getattr(detail, "pod_real_memory_bytes", None)
                        ),
                        self._format_percentage(
                            getattr(detail, "pod_memory_pct_of_node_allocatable", None)
                        ),
                    ),
                    self._format_runtime_cpu(
                        getattr(detail, "node_cpu_allocatable_mcores", None)
                    ),
                    self._format_runtime_memory(
                        getattr(detail, "node_memory_allocatable_bytes", None)
                    ),
                    restart_reason,
                    str(last_exit_code) if last_exit_code is not None else "-",
                )
            )
        return rows

