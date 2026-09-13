from __future__ import annotations

import json

import pytest

from apps.ops_agent.resources import (
    GIB,
    CgroupMemory,
    HostMemory,
    PressureThresholds,
    ResourceAction,
    ResourcePressurePolicy,
    ResourceSnapshot,
    ResourceThresholds,
    evaluate_resource_guard,
)


def snapshot(
    *,
    available_gib: float = 4.0,
    cgroup_ratio: float = 0.50,
    rss_gib: float = 1.0,
    swap_used_gib: float = 0.0,
    swap_activity_bytes_per_second: float | None = None,
    host: bool = True,
    cgroup: bool = True,
) -> ResourceSnapshot:
    available = int(available_gib * GIB) if host else None
    host_memory = (
        HostMemory(
            total_bytes=8 * GIB,
            available_bytes=available,
            swap_total_bytes=2 * GIB,
            swap_free_bytes=2 * GIB - int(swap_used_gib * GIB),
        )
        if host
        else None
    )
    cgroup_memory = (
        CgroupMemory(
            current_bytes=int(cgroup_ratio * 3 * GIB),
            limit_bytes=3 * GIB,
            swap_current_bytes=int(swap_used_gib * GIB),
            swap_limit_bytes=2 * GIB,
        )
        if cgroup
        else None
    )
    return ResourceSnapshot(
        process_tree_rss_bytes=int(rss_gib * GIB),
        host=host_memory,
        cgroup=cgroup_memory,
        swap_activity_bytes_per_second=swap_activity_bytes_per_second,
    )


def policy_thresholds(**overrides: object) -> PressureThresholds:
    values: dict[str, object] = {
        "constrained_duration_seconds": 6.0,
        "protected_duration_seconds": 3.0,
        "recovery_duration_seconds": 18.0,
        "stable_duration_seconds": 60.0,
        "max_sample_gap_seconds": 5.0,
    }
    values.update(overrides)
    return PressureThresholds(**values)


def test_residual_swap_is_not_a_pressure_signal_or_legacy_drain() -> None:
    state = ResourcePressurePolicy().update(
        snapshot(swap_used_gib=1.0),
        now=0,
    )
    assert state.state == "normal"
    assert state.allow_daily is True
    assert state.allow_history is True

    decision = evaluate_resource_guard(snapshot(swap_used_gib=1.0), ResourceThresholds())
    assert decision.action is ResourceAction.ALLOW
    assert decision.reasons == ()


def test_active_swap_pressure_requires_low_host_memory_and_duration() -> None:
    policy = ResourcePressurePolicy(policy_thresholds(protected_duration_seconds=6.0))
    active = snapshot(
        available_gib=1.9,
        cgroup_ratio=0.50,
        swap_activity_bytes_per_second=64 * 1024**2,
    )
    high_memory_active = snapshot(
        available_gib=3.0,
        cgroup_ratio=0.50,
        swap_activity_bytes_per_second=64 * 1024**2,
    )

    assert policy.update(high_memory_active, 0).state == "normal"
    assert policy.update(active, 1).state == "normal"
    assert policy.update(active, 3).state == "normal"
    assert policy.update(active, 7).state == "protected"

    static_only = ResourcePressurePolicy().update(
        snapshot(available_gib=1.9, swap_used_gib=1.0),
        0,
    )
    assert static_only.state == "normal"


def test_pressure_bands_need_continuous_samples_and_escalate() -> None:
    policy = ResourcePressurePolicy(policy_thresholds())
    constrained = snapshot(available_gib=4.0, cgroup_ratio=0.85)
    protected = snapshot(available_gib=4.0, cgroup_ratio=0.95)

    assert policy.update(constrained, 0).state == "normal"
    assert policy.update(constrained, 5).state == "normal"
    constrained_state = policy.update(constrained, 6)
    assert constrained_state.state == "constrained"
    assert constrained_state.allow_daily is True
    assert constrained_state.allow_history is False

    assert policy.update(protected, 7).state == "constrained"
    protected_state = policy.update(protected, 10)
    assert protected_state.state == "protected"
    assert protected_state.allow_daily is False
    assert protected_state.allow_history is False
    assert "cgroup_usage_above_protected_ratio" in protected_state.reasons


def test_short_pressure_jitter_does_not_change_normal_state() -> None:
    policy = ResourcePressurePolicy(policy_thresholds())
    protected = snapshot(available_gib=4.0, cgroup_ratio=0.95)
    healthy = snapshot()

    assert policy.update(protected, 0).state == "normal"
    assert policy.update(protected, 2).state == "normal"
    assert policy.update(healthy, 3).state == "normal"
    assert policy.update(protected, 4).state == "normal"
    final = policy.update(healthy, 5)
    assert final.state == "normal"
    assert final.allow_history is True


def test_recovery_requires_healthy_window_then_stable_recovery() -> None:
    thresholds = policy_thresholds(max_sample_gap_seconds=5.0)
    policy = ResourcePressurePolicy(thresholds)
    protected = snapshot(available_gib=4.0, cgroup_ratio=0.95)
    healthy = snapshot(available_gib=3.0, cgroup_ratio=0.50)

    assert policy.update(protected, 0).state == "normal"
    assert policy.update(protected, 3).state == "protected"
    for now in (4, 9, 14, 19):
        assert policy.update(healthy, now).state == "protected"
    recovering = policy.update(healthy, 22)
    assert recovering.state == "recovering"
    assert recovering.allow_daily is True
    assert recovering.allow_history is False
    assert recovering.healthy_since == 4.0

    for now in (27, 32, 37, 42, 47, 52, 57, 62, 67, 72, 77):
        assert policy.update(healthy, now).state == "recovering"
    normal = policy.update(healthy, 82)
    assert normal.state == "normal"
    assert normal.allow_history is True


def test_reappearing_pressure_resets_recovery_stability() -> None:
    thresholds = policy_thresholds(
        recovery_duration_seconds=6.0,
        stable_duration_seconds=10.0,
        max_sample_gap_seconds=20.0,
    )
    policy = ResourcePressurePolicy(thresholds, initial_state="protected")
    healthy = snapshot()
    constrained = snapshot(available_gib=4.0, cgroup_ratio=0.85)

    for now in (0, 3, 6):
        state = policy.update(healthy, now)
    assert state.state == "recovering"
    assert policy.update(healthy, 9).state == "recovering"
    interrupted = policy.update(constrained, 10)
    assert interrupted.state == "recovering"
    assert interrupted.allow_history is False
    assert "pressure_reappeared" in interrupted.reasons
    assert policy.update(healthy, 13).state == "recovering"
    assert policy.update(healthy, 22).state == "recovering"
    assert policy.update(healthy, 23).state == "normal"


def test_missing_host_or_cgroup_cannot_be_used_as_safe_recovery() -> None:
    policy = ResourcePressurePolicy(initial_state="protected")
    missing_host = policy.update(snapshot(host=False), 0)
    assert missing_host.state == "protected"
    assert missing_host.allow_daily is False
    assert missing_host.allow_history is False
    assert "host_memory_unavailable" in missing_host.reasons
    assert missing_host.healthy_since is None

    # Supplying healthy metrics starts the recovery clock, but it does not
    # bypass the required recovery window after the missing sample.
    healthy = policy.update(snapshot(), 1)
    assert healthy.state == "protected"
    assert healthy.healthy_since == 1.0
    assert policy.update(snapshot(), 100).state == "protected"


def test_sample_gap_resets_continuous_pressure_timer() -> None:
    policy = ResourcePressurePolicy(
        policy_thresholds(
            constrained_duration_seconds=60.0,
            protected_duration_seconds=30.0,
            max_sample_gap_seconds=15.0,
        )
    )
    protected = snapshot(available_gib=4.0, cgroup_ratio=0.95)

    assert policy.update(protected, 0).state == "normal"
    assert policy.update(protected, 10).state == "normal"
    # The 20 second gap means the first pressure streak cannot reach 30s.
    assert policy.update(protected, 30).state == "normal"
    assert policy.update(protected, 31).state == "normal"
    assert policy.update(protected, 46).state == "normal"
    assert policy.update(protected, 61).state == "protected"


def test_hard_limits_protect_immediately_without_resetting_state_since() -> None:
    policy = ResourcePressurePolicy()
    hard_rss = snapshot(rss_gib=2.0)

    first = policy.update(hard_rss, 10)
    second = policy.update(hard_rss, 11)
    assert first.state == "protected"
    assert first.allow_daily is False
    assert "process_tree_rss_hard_limit" in first.reasons
    assert second.state == "protected"
    assert second.since == first.since == 10.0

    hard_cgroup = snapshot(rss_gib=1.0, cgroup_ratio=1.0)
    assert "cgroup_memory_hard_limit" in policy.update(hard_cgroup, 12).reasons


def test_pressure_threshold_env_is_namespaced_and_validated() -> None:
    thresholds = PressureThresholds.from_env(
        {
            "WORKER_RESOURCE_WARN_HOST_USED_BYTES": "1",
            "WORKER_RESOURCE_MAX_SWAP_USED_BYTES": "1",
            "WORKER_RESOURCE_PRESSURE_CONSTRAINED_DURATION_SECONDS": "12",
            "WORKER_RESOURCE_PRESSURE_PROTECTED_DURATION_SECONDS": "6",
            "WORKER_RESOURCE_PRESSURE_MAX_SAMPLE_GAP_SECONDS": "9",
            "WORKER_RESOURCE_PRESSURE_SWAP_ACTIVITY_THRESHOLD_BYTES_PER_SECOND": "123",
        }
    )
    assert thresholds.constrained_duration_seconds == 12.0
    assert thresholds.max_sample_gap_seconds == 9.0
    assert thresholds.constrained_available_bytes == 2 * GIB
    assert thresholds.protected_cgroup_ratio == 0.90
    assert thresholds.swap_activity_threshold_bytes_per_second == 123.0

    with pytest.raises(ValueError, match="protected < constrained < recovery"):
        PressureThresholds(
            protected_available_bytes=2 * GIB,
            constrained_available_bytes=1 * GIB,
        )
    with pytest.raises(ValueError, match="recovery < constrained < protected"):
        PressureThresholds(
            recovery_cgroup_ratio=0.90,
            constrained_cgroup_ratio=0.80,
            protected_cgroup_ratio=0.85,
        )


def test_pressure_state_serializes_to_json_compatible_mapping() -> None:
    state = ResourcePressurePolicy().update(snapshot(), 12)
    payload = state.to_dict()

    assert payload["state"] == "normal"
    assert payload["reasons"] == []
    json.dumps(payload)
