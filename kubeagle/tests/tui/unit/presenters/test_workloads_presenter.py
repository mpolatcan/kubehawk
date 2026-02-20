"""Unit tests for WorkloadsPresenter resource-table helpers."""

from __future__ import annotations

from types import SimpleNamespace

from kubeagle.screens.workloads.config import (
    TAB_WORKLOADS_ALL,
    TAB_WORKLOADS_NODE_ANALYSIS,
    WORKLOADS_RESOURCE_NODE_ANALYSIS_COLUMNS,
    WORKLOADS_SORT_OPTIONS,
    WORKLOADS_TABLE_COLUMNS_BY_TAB,
)
from kubeagle.screens.workloads.presenter import WorkloadsPresenter


def _make_workload(
    *,
    name: str,
    kind: str,
    namespace: str = "default",
    desired_replicas: int | None = 1,
    ready_replicas: int | None = 1,
    cpu_request: float = 0.0,
    cpu_limit: float = 0.0,
    memory_request: float = 0.0,
    memory_limit: float = 0.0,
    restart_count: int = 0,
    restart_reason_counts: dict[str, int] | None = None,
    has_pdb: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        namespace=namespace,
        kind=kind,
        name=name,
        desired_replicas=desired_replicas,
        ready_replicas=ready_replicas,
        helm_release=f"{name}-rel",
        has_pdb=has_pdb,
        status="Ready",
        cpu_request=cpu_request,
        cpu_limit=cpu_limit,
        memory_request=memory_request,
        memory_limit=memory_limit,
        restart_count=restart_count,
        restart_reason_counts=restart_reason_counts or {},
    )


def test_resource_rows_can_filter_by_workload_kind() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(name="api", kind="Deployment"),
        _make_workload(name="db", kind="StatefulSet"),
    ]

    rows = presenter.get_resource_rows(workload_kind="Deployment")

    assert len(rows) == 1
    assert rows[0][1] == "Deployment"
    assert "api" in rows[0][2]
    assert "[1/1]" in rows[0][2]


def test_resource_rows_show_ratio_markup() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(
            name="api",
            kind="Deployment",
            cpu_request=200.0,
            cpu_limit=800.0,
            memory_request=256 * 1024 * 1024,
            memory_limit=1024 * 1024 * 1024,
        )
    ]

    columns = WORKLOADS_TABLE_COLUMNS_BY_TAB[TAB_WORKLOADS_ALL]
    column_index = {name: index for index, (name, _) in enumerate(columns)}
    rows = presenter.get_resource_rows(columns=columns)

    assert len(rows) == 1
    assert "200m / 800m" in rows[0][column_index["CPU R/L"]]
    assert "4.0" in rows[0][column_index["CPU R/L"]]
    assert "256.0Mi / 1.0Gi" in rows[0][column_index["Mem R/L"]]
    assert "4.0" in rows[0][column_index["Mem R/L"]]


def test_build_resource_summary_counts_missing_and_extreme() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(
            name="api",
            kind="Deployment",
            cpu_request=200.0,
            cpu_limit=500.0,
            memory_request=256 * 1024 * 1024,
            memory_limit=512 * 1024 * 1024,
            has_pdb=True,
        ),
        _make_workload(
            name="worker",
            kind="Deployment",
            cpu_request=0.0,
            cpu_limit=500.0,
            memory_request=0.0,
            memory_limit=512 * 1024 * 1024,
            has_pdb=False,
        ),
        _make_workload(
            name="cron",
            kind="CronJob",
            cpu_request=50.0,
            cpu_limit=250.0,
            memory_request=128 * 1024 * 1024,
            memory_limit=1024 * 1024 * 1024,
            has_pdb=False,
        ),
    ]

    filtered = presenter.get_filtered_workloads(workload_kind="Deployment")
    scoped_total = presenter.get_scoped_workload_count(workload_kind="Deployment")
    summary = presenter.build_resource_summary_from_filtered(
        filtered_workloads=filtered,
        scoped_total=scoped_total,
    )

    assert summary["shown_total"] == "2/2"
    assert summary["missing_cpu_request"] == "1"
    assert summary["missing_memory_request"] == "1"
    assert summary["extreme_ratios"] == "0"


def test_prefiltered_summary_helpers_reuse_existing_results() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(name="api", kind="Deployment", has_pdb=True),
        _make_workload(name="worker", kind="Deployment", has_pdb=False),
        _make_workload(name="cron", kind="CronJob", has_pdb=False),
    ]

    filtered = presenter.get_filtered_workloads(
        workload_kind="Deployment",
        search_query="api",
    )
    scoped_total = presenter.get_scoped_workload_count(
        workload_kind="Deployment",
    )
    summary = presenter.build_resource_summary_from_filtered(
        filtered_workloads=filtered,
        scoped_total=scoped_total,
    )

    assert summary["shown_total"] == "1/2"
    assert summary["missing_cpu_request"] == "1"
    assert summary["missing_memory_request"] == "1"
    assert summary["pdb_coverage"] == "100%"


def test_resource_rows_apply_namespace_status_and_pdb_filters() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(
            name="api",
            kind="Deployment",
            namespace="team-a",
            has_pdb=True,
        ),
        _make_workload(
            name="worker",
            kind="Deployment",
            namespace="team-b",
            has_pdb=False,
        ),
    ]
    presenter._data["all_workloads"][0].status = "Ready"
    presenter._data["all_workloads"][1].status = "Pending"

    rows = presenter.get_resource_rows(
        namespace_filter_values={"team-b"},
        status_filter_values={"Pending"},
        pdb_filter_values={"without_pdb"},
    )

    assert len(rows) == 1
    assert rows[0][0] == "team-b"
    assert "worker" in rows[0][2]


def test_resource_rows_apply_name_kind_and_helm_release_filters() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(
            name="api",
            kind="Deployment",
            namespace="team-a",
        ),
        _make_workload(
            name="worker",
            kind="StatefulSet",
            namespace="team-b",
        ),
    ]
    presenter._data["all_workloads"][0].helm_release = "platform-api"
    presenter._data["all_workloads"][1].helm_release = "platform-worker"

    rows = presenter.get_resource_rows(
        name_filter_values={"worker"},
        kind_filter_values={"StatefulSet"},
        helm_release_filter_values={"platform-worker"},
    )

    assert len(rows) == 1
    assert rows[0][1] == "StatefulSet"
    assert "worker" in rows[0][2]
    assert "⎈" in rows[0][2]


def test_resource_rows_apply_with_helm_without_helm_filters() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(name="api", kind="Deployment"),
        _make_workload(name="worker", kind="Deployment"),
    ]
    presenter._data["all_workloads"][0].helm_release = "platform-api"
    presenter._data["all_workloads"][1].helm_release = ""

    with_helm_rows = presenter.get_resource_rows(
        helm_release_filter_values={"with_helm"},
    )
    without_helm_rows = presenter.get_resource_rows(
        helm_release_filter_values={"without_helm"},
    )

    assert len(with_helm_rows) == 1
    assert "api" in with_helm_rows[0][2]
    assert "⎈" in with_helm_rows[0][2]
    assert "[#30d158]⎈[/#30d158]" in with_helm_rows[0][2]

    assert len(without_helm_rows) == 1
    assert "worker" in without_helm_rows[0][2]
    assert "⎈" not in without_helm_rows[0][2]


def test_resource_rows_compact_req_lim_columns_sort_by_cpu_request_left_value() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(name="small-req", kind="Deployment", cpu_request=100.0, cpu_limit=800.0),
        _make_workload(name="big-req", kind="Deployment", cpu_request=400.0, cpu_limit=500.0),
    ]

    columns = WORKLOADS_TABLE_COLUMNS_BY_TAB[TAB_WORKLOADS_ALL]
    column_index = {name: index for index, (name, _) in enumerate(columns)}
    rows = presenter.get_resource_rows(
        columns=columns,
        sort_by="cpu_request",
        descending=True,
    )

    assert len(rows) == 2
    assert "big-req" in rows[0][2]
    assert "400m / 500m" in rows[0][column_index["CPU R/L"]]
    assert "small-req" in rows[1][2]
    assert "100m / 800m" in rows[1][column_index["CPU R/L"]]


def test_resource_rows_include_restart_counts_and_sort_by_restarts() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(
            name="api",
            kind="Deployment",
            restart_count=6,
            restart_reason_counts={"CrashLoopBackOff": 4, "OOMKilled": 2},
        ),
        _make_workload(name="worker", kind="Deployment", restart_count=0),
    ]

    columns = WORKLOADS_TABLE_COLUMNS_BY_TAB[TAB_WORKLOADS_ALL]
    column_index = {name: index for index, (name, _) in enumerate(columns)}
    rows = presenter.get_resource_rows(
        columns=columns,
        sort_by="restarts",
        descending=True,
    )

    assert len(rows) == 2
    assert "api" in rows[0][2]
    assert rows[0][column_index["Restarts"]] == (
        "[bold #ff3b30]6[/bold #ff3b30] [dim](CrashLoopBackOff:4, OOMKilled:2)[/dim]"
    )
    assert "worker" in rows[1][2]
    assert rows[1][column_index["Restarts"]] == "0"


def test_resource_rows_sort_usage_metrics_with_split_sort_options() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    sort_by_label = dict(WORKLOADS_SORT_OPTIONS)
    sort_cases = [
        ("Node CPU Usage Avg", "node_real_cpu_avg", "1200m (75%)", "600m (20%)"),
        ("Node CPU Req Avg", "cpu_req_util_avg", "82%", "30%"),
        ("Node CPU Lim Avg", "cpu_lim_util_avg", "65%", "25%"),
        ("Node CPU Usage Max", "node_real_cpu_max", "1800m (85%)", "900m (35%)"),
        ("Node CPU Req Max", "cpu_req_util_max", "110%", "40%"),
        ("Node CPU Lim Max", "cpu_lim_util_max", "88%", "38%"),
        ("Node CPU Usage P95", "node_real_cpu_p95", "1500m (70%)", "700m (22%)"),
        ("Node CPU Req P95", "cpu_req_util_p95", "95%", "28%"),
        ("Node CPU Lim P95", "cpu_lim_util_p95", "70%", "20%"),
        ("Node Mem Usage Avg", "node_real_memory_avg", "5.5Gi (68%)", "2.0Gi (25%)"),
        ("Node Mem Req Avg", "mem_req_util_avg", "90%", "35%"),
        ("Node Mem Lim Avg", "mem_lim_util_avg", "62%", "22%"),
        ("Node Mem Usage Max", "node_real_memory_max", "7.2Gi (82%)", "2.9Gi (31%)"),
        ("Node Mem Req Max", "mem_req_util_max", "120%", "45%"),
        ("Node Mem Lim Max", "mem_lim_util_max", "85%", "30%"),
        ("Node Mem Usage P95", "node_real_memory_p95", "6.3Gi (74%)", "2.5Gi (29%)"),
        ("Node Mem Req P95", "mem_req_util_p95", "98%", "33%"),
        ("Node Mem Lim P95", "mem_lim_util_p95", "73%", "24%"),
        ("Workload CPU Usage Avg", "pod_real_cpu_avg", "800m (42%)", "200m (8%)"),
        ("Workload CPU Usage Max", "pod_real_cpu_max", "1400m (66%)", "500m (18%)"),
        ("Workload CPU Usage P95", "pod_real_cpu_p95", "1200m (58%)", "380m (14%)"),
        ("Workload Mem Usage Avg", "pod_real_memory_avg", "2.1Gi (44%)", "600Mi (10%)"),
        ("Workload Mem Usage Max", "pod_real_memory_max", "3.2Gi (61%)", "1.0Gi (16%)"),
        ("Workload Mem Usage P95", "pod_real_memory_p95", "2.8Gi (53%)", "900Mi (13%)"),
    ]

    for label, attribute_name, high_value, low_value in sort_cases:
        high = _make_workload(name="high", kind="Deployment")
        low = _make_workload(name="low", kind="Deployment")
        setattr(high, attribute_name, high_value)
        setattr(low, attribute_name, low_value)
        presenter._data["all_workloads"] = [low, high]

        rows_desc = presenter.get_resource_rows(
            columns=WORKLOADS_RESOURCE_NODE_ANALYSIS_COLUMNS,
            sort_by=sort_by_label[label],
            descending=True,
        )
        rows_asc = presenter.get_resource_rows(
            columns=WORKLOADS_RESOURCE_NODE_ANALYSIS_COLUMNS,
            sort_by=sort_by_label[label],
            descending=False,
        )

        assert "high" in rows_desc[0][2], label
        assert "low" in rows_asc[0][2], label


def test_resource_rows_apply_extreme_ratios_view_filter() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(
            name="api",
            kind="Deployment",
            cpu_request=200.0,
            cpu_limit=900.0,
        ),
        _make_workload(
            name="worker",
            kind="Deployment",
            cpu_request=200.0,
            cpu_limit=300.0,
        ),
    ]

    rows = presenter.get_resource_rows(workload_view_filter="extreme_ratios")

    assert len(rows) == 1
    assert "api" in rows[0][2]


def test_resource_rows_apply_single_replica_view_filter() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(name="api", kind="Deployment", desired_replicas=1),
        _make_workload(name="worker", kind="Deployment", desired_replicas=3),
    ]

    rows = presenter.get_resource_rows(workload_view_filter="single_replica")

    assert len(rows) == 1
    assert "api" in rows[0][2]


def test_resource_rows_apply_missing_pdb_view_filter() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    presenter._data["all_workloads"] = [
        _make_workload(name="api", kind="Deployment", has_pdb=False),
        _make_workload(name="worker", kind="Deployment", has_pdb=True),
    ]

    rows = presenter.get_resource_rows(workload_view_filter="missing_pdb")

    assert len(rows) == 1
    assert "api" in rows[0][2]


def test_resource_rows_include_runtime_utilization_columns() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    row = _make_workload(name="api", kind="Deployment")
    row.assigned_nodes = "2"
    row.node_real_cpu_avg = "900m (32%)"
    row.node_real_cpu_max = "1400m (50%)"
    row.node_real_cpu_p95 = "1200m (43%)"
    row.node_real_memory_avg = "3.8Gi (47%)"
    row.node_real_memory_max = "6.1Gi (76%)"
    row.node_real_memory_p95 = "5.2Gi (65%)"
    row.cpu_req_util_max = "110%"
    row.cpu_req_util_avg = "73%"
    row.cpu_req_util_p95 = "85%"
    row.cpu_lim_util_max = "60%"
    row.cpu_lim_util_avg = "38%"
    row.cpu_lim_util_p95 = "42%"
    row.mem_req_util_max = "120%"
    row.mem_req_util_avg = "80%"
    row.mem_req_util_p95 = "88%"
    row.mem_lim_util_max = "71%"
    row.mem_lim_util_avg = "48%"
    row.mem_lim_util_p95 = "55%"
    row.pod_real_cpu_avg = "400m (15%)"
    row.pod_real_cpu_max = "900m (33%)"
    row.pod_real_cpu_p95 = "1200m (44%)"
    row.pod_real_memory_avg = "1.0Gi (12%)"
    row.pod_real_memory_max = "2.3Gi (51%)"
    row.pod_real_memory_p95 = "2.0Gi (45%)"
    presenter._data["all_workloads"] = [row]

    columns = WORKLOADS_RESOURCE_NODE_ANALYSIS_COLUMNS
    rows = presenter.get_resource_rows(columns=columns)
    column_index = {name: index for index, (name, _) in enumerate(columns)}

    assert len(rows) == 1
    assert rows[0][column_index["Nodes"]] == "2"
    assert rows[0][column_index["Node CPU Usage/Req/Lim Avg"]] == (
        "[#30d158]900m (32%)[/#30d158] / [#ffd60a]73%[/#ffd60a]"
        " / [#30d158]38%[/#30d158]"
    )
    assert rows[0][column_index["Node CPU Usage/Req/Lim Max"]] == (
        "[#ffd60a]1400m (50%)[/#ffd60a] / [bold #ff3b30]110%[/bold #ff3b30]"
        " / [#ffd60a]60%[/#ffd60a]"
    )
    assert rows[0][column_index["Node CPU Usage/Req/Lim P95"]] == (
        "[#30d158]1200m (43%)[/#30d158] / [bold #ff9f0a]85%[/bold #ff9f0a]"
        " / [#30d158]42%[/#30d158]"
    )
    assert rows[0][column_index["Node Mem Usage/Req/Lim Avg"]] == (
        "[#30d158]3.8Gi (47%)[/#30d158] / [bold #ff9f0a]80%[/bold #ff9f0a]"
        " / [#30d158]48%[/#30d158]"
    )
    assert rows[0][column_index["Node Mem Usage/Req/Lim Max"]] == (
        "[#ffd60a]6.1Gi (76%)[/#ffd60a] / [bold #ff3b30]120%[/bold #ff3b30]"
        " / [#ffd60a]71%[/#ffd60a]"
    )
    assert rows[0][column_index["Node Mem Usage/Req/Lim P95"]] == (
        "[#ffd60a]5.2Gi (65%)[/#ffd60a] / [bold #ff9f0a]88%[/bold #ff9f0a]"
        " / [#ffd60a]55%[/#ffd60a]"
    )
    assert rows[0][column_index["Workload CPU Usage Avg/Max/P95"]] == (
        "[#30d158]400m (15%)[/#30d158] / [#30d158]900m (33%)[/#30d158]"
        " / [#30d158]1200m (44%)[/#30d158]"
    )
    assert rows[0][column_index["Workload Mem Usage Avg/Max/P95"]] == (
        "[#30d158]1.0Gi (12%)[/#30d158] / [#ffd60a]2.3Gi (51%)[/#ffd60a]"
        " / [#30d158]2.0Gi (45%)[/#30d158]"
    )


def test_non_node_tabs_do_not_include_node_analysis_columns() -> None:
    all_tab_columns = [name for name, _ in WORKLOADS_TABLE_COLUMNS_BY_TAB[TAB_WORKLOADS_ALL]]
    node_tab_columns = [
        name for name, _ in WORKLOADS_TABLE_COLUMNS_BY_TAB[TAB_WORKLOADS_NODE_ANALYSIS]
    ]

    assert "Nodes" not in all_tab_columns
    assert "Restarts" in all_tab_columns
    assert "PDB" in all_tab_columns
    assert "Node CPU Usage/Req/Lim Avg" not in all_tab_columns
    assert "Node CPU Usage/Req/Lim P95" not in all_tab_columns
    assert "Neighbor CPU Pressure Max/Avg" not in all_tab_columns
    assert "Neighbor CPU Req Pressure Max/Avg" not in all_tab_columns
    assert "Nodes" in node_tab_columns
    assert "Restarts" in node_tab_columns
    assert node_tab_columns.index("Restarts") > node_tab_columns.index("Mem R/L")
    assert "PDB" not in node_tab_columns
    assert "Node CPU Usage/Req/Lim Avg" in node_tab_columns
    assert "Node CPU Usage/Req/Lim P95" in node_tab_columns
    assert "Neighbor CPU Pressure Max/Avg" not in node_tab_columns
    assert "Neighbor CPU Req Pressure Max/Avg" not in node_tab_columns


def test_assigned_pod_detail_rows_format_node_relative_percentages() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    workload = SimpleNamespace(
        assigned_pod_details=[
            SimpleNamespace(
                namespace="team-a",
                pod_name="api-123",
                node_name="node-a",
                pod_phase="Running",
                pod_real_cpu_mcores=250.0,
                pod_real_memory_bytes=1024 * 1024 * 1024,
                node_cpu_allocatable_mcores=4000.0,
                node_memory_allocatable_bytes=8 * 1024 * 1024 * 1024,
                pod_cpu_pct_of_node_allocatable=6.25,
                pod_memory_pct_of_node_allocatable=12.0,
            )
        ]
    )

    rows = presenter.get_assigned_pod_detail_rows(workload)

    assert rows == [
        (
            "team-a",
            "api-123",
            "node-a",
            "Running",
            "250m (6.2%)",
            "1.0Gi (12%)",
            "4000m",
            "8.0Gi",
            "-",
            "-",
        )
    ]


def test_assigned_pod_detail_rows_include_restart_reason_and_exit_code() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    workload = SimpleNamespace(
        assigned_pod_details=[
            SimpleNamespace(
                namespace="team-a",
                pod_name="api-456",
                node_name="node-b",
                pod_phase="Running",
                pod_real_cpu_mcores=100.0,
                pod_real_memory_bytes=256 * 1024 * 1024,
                node_cpu_allocatable_mcores=2000.0,
                node_memory_allocatable_bytes=4 * 1024 * 1024 * 1024,
                pod_cpu_pct_of_node_allocatable=5.0,
                pod_memory_pct_of_node_allocatable=6.25,
                restart_reason="CrashLoopBackOff",
                last_exit_code=137,
            )
        ]
    )

    rows = presenter.get_assigned_pod_detail_rows(workload)

    assert rows == [
        (
            "team-a",
            "api-456",
            "node-b",
            "Running",
            "100m (5.0%)",
            "256.0Mi (6.2%)",
            "2000m",
            "4.0Gi",
            "CrashLoopBackOff",
            "137",
        )
    ]


def test_assigned_node_detail_rows_include_real_usage_percentages() -> None:
    presenter = WorkloadsPresenter(screen=SimpleNamespace())
    workload = SimpleNamespace(
        assigned_node_details=[
            SimpleNamespace(
                node_name="node-a",
                node_group="ng-a",
                workload_pod_count_on_node=2,
                node_cpu_req_pct=60.0,
                node_cpu_lim_pct=30.0,
                node_mem_req_pct=50.0,
                node_mem_lim_pct=25.0,
                node_real_cpu_mcores=1000.0,
                node_real_memory_bytes=2 * 1024 * 1024 * 1024,
                node_real_cpu_pct_of_allocatable=25.0,
                node_real_memory_pct_of_allocatable=25.0,
                workload_pod_real_cpu_mcores_on_node=250.0,
                workload_pod_real_memory_bytes_on_node=1024 * 1024 * 1024,
                workload_pod_real_cpu_pct_of_node_allocatable=6.25,
                workload_pod_real_memory_pct_of_node_allocatable=12.5,
            )
        ]
    )

    rows = presenter.get_assigned_node_detail_rows(workload)

    assert rows == [
        (
            "node-a",
            "ng-a",
            "2",
            "60%",
            "30%",
            "50%",
            "25%",
            "1000m (25%)",
            "2.0Gi (25%)",
            "250m (6.2%)",
            "1.0Gi (12%)",
        )
    ]
