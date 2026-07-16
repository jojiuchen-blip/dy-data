from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-16-dydata-21-admin-commission-rules.md"
)


def test_admin_commission_rules_spec_locks_confirmed_decisions() -> None:
    source = SPEC.read_text(encoding="utf-8")

    for required in (
        "【管理后台】分佣规则修改",
        "产品范围＋商品类型＋生效月份",
        "推广费比例",
        "应收推广费",
        "管理服务费比例",
        "应扣管理服务费",
        "比例为 0% 视为已配置",
        "管理服务费比例是否配置，不影响销售总金额是否计入",
        "本轮不预设精诚养车",
        "不配置系统角色、财务角色、账号或权限矩阵",
        "codex/dydata-21-admin-commission-rules",
    ):
        assert required in source


def test_admin_commission_rules_spec_separates_adjacent_work() -> None:
    source = SPEC.read_text(encoding="utf-8")

    assert "不修改订单分佣前端页面视觉" in source
    assert "批量导入是独立于 DYDATA-21" in source
    assert "不是订单、券或门店月度金额调整" in source
    assert "不默认写成 `10%＋10%`" in source
    assert "协作者启动提示" in source
