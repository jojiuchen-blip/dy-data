import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App.jsx";
import { managementInvoices, promotionInvoices } from "./data/financeData.js";

describe("需求讨论原型边界", () => {
  it.each([
    ["store", "store-bills"],
    ["finance", "finance-promotion"],
  ])("%s 端首屏持续展示非生产边界", (initialRole, initialPage) => {
    render(<App initialRole={initialRole} initialPage={initialPage} />);

    const boundary = screen.getByRole("note", { name: "原型边界" });
    expect(boundary).toHaveTextContent("需求讨论原型");
    expect(boundary).toHaveTextContent("非生产能力");
    expect(boundary).toHaveTextContent("非权威契约");
    expect(boundary).toHaveTextContent("不会提交、审核、打款或修改业务状态");
  });

  it("状态变更控件明确标记为演示动作，且状态仅存在于当前挂载周期", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<App />);

    await user.click(screen.getByRole("button", { name: "演示动作：确认推广服务费金额" }));
    expect(screen.getByRole("button", { name: "进入推广费开票" })).toBeInTheDocument();

    unmount();
    render(<App />);
    expect(screen.getByRole("button", { name: "演示动作：确认推广服务费金额" })).toBeInTheDocument();
  });

  it("发票提交与财务导入均明确标记为演示动作", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<App initialPage="store-invoices" />);

    expect(screen.getByRole("button", { name: "演示动作：校验并提交发票" })).toBeInTheDocument();

    unmount();
    render(<App initialRole="finance" initialPage="finance-promotion" />);
    await user.click(screen.getByRole("button", { name: "演示动作：导入推广费厂家信息" }));
    expect(screen.getByRole("button", { name: "演示动作：模拟校验并导入" })).toBeInTheDocument();
  });

  it("导入记录不再宣称已确定原文件留存政策", () => {
    render(<App initialRole="finance" initialPage="finance-imports" />);

    expect(screen.getByText("留存政策待 DYDATA-19 财务与审计决策", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText("不保存原始上传文件", { exact: false })).not.toBeInTheDocument();
  });
});

describe("门店端财务流程", () => {
  it("门店可分别确认推广服务费和管理服务费", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getAllByText("推广服务费").length).toBeGreaterThan(0);
    expect(screen.getAllByText("管理服务费").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "演示动作：确认推广服务费金额" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "演示动作：确认管理服务费金额" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "演示动作：确认推广服务费金额" }));
    expect(screen.getByRole("button", { name: "进入推广费开票" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "演示动作：确认管理服务费金额" }));
    expect(screen.getAllByText("已确认").length).toBeGreaterThanOrEqual(2);
  });

  it("账单卡只显示账单总额和确认状态，不展示确认金额拆分", () => {
    render(<App />);

    expect(screen.getAllByText("账单总额")).toHaveLength(2);
    expect(screen.queryByText("已确认金额")).not.toBeInTheDocument();
    expect(screen.queryByText("待确认金额")).not.toBeInTheDocument();
    expect(screen.getAllByText("待确认").length).toBeGreaterThanOrEqual(2);
  });

  it("账单详情默认展开且可以收起", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("button", { name: "演示动作：发起账单异议" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "收起账单详情" }));
    expect(screen.queryByRole("button", { name: "演示动作：发起账单异议" })).not.toBeInTheDocument();
  });

  it("发起账单异议前二次确认，确认后才进入异议详情", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "演示动作：发起账单异议" }));
    expect(screen.getByRole("dialog", { name: "确认发起账单异议" })).toBeInTheDocument();
    expect(screen.getByText("发起异议前请准备充分资料，是否发起？")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "发起推广服务费账单异议" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "演示动作：确认发起" }));
    expect(screen.getByRole("heading", { name: "发起推广服务费账单异议" })).toBeInTheDocument();
  });

  it("推广服务费明细在账单详情内默认展开且不展示原型解释文案", () => {
    render(<App />);

    expect(screen.getByRole("table", { name: "门店推广服务费明细" })).toBeInTheDocument();
    expect(screen.getByText("DY20260719000842")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "查看推广服务费明细" })).not.toBeInTheDocument();
    expect(screen.getByText("核对后再确认")).toBeInTheDocument();
    expect(screen.queryByText("异议入口放在详情内部，避免未核对订单就直接发起。")).not.toBeInTheDocument();
  });

  it("账单详情展开订单核算字段", () => {
    render(<App />);

    const table = screen.getByRole("table", { name: "门店推广服务费明细" });
    for (const header of ["订单号", "商品", "销售渠道", "核销时间", "实收金额", "有效费率", "推广服务费"]) {
      expect(within(table).getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
  });

  it("账单异议入口使用小尺寸弱化样式", () => {
    render(<App />);

    expect(screen.getByRole("button", { name: "演示动作：发起账单异议" })).toHaveClass(
      "text-button--compact",
      "text-button--quiet",
    );
  });

  it("单店分账页面提示月末先确认金额再去开票", () => {
    render(<App />);

    expect(screen.getByRole("button", { name: "单店分账" })).toBeInTheDocument();
    expect(screen.getByText("月度结束后，请先确认账单金额，再前往推广服务费开票页面完成操作。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发票状态查看" })).toBeInTheDocument();
  });

  it("开票页面展示完整收票信息并支持一键复制全部", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);

    expect(screen.getByText("914403007604674476")).toBeInTheDocument();
    expect(screen.getByText("深圳市坪山新区坪山街道比亚迪路3005号")).toBeInTheDocument();
    expect(screen.getByText("农行龙岗支行 41022900040008463")).toBeInTheDocument();
    expect(screen.getByText("3079900000000000000")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "一键复制全部开票信息" }));
    expect(screen.getByText("已复制全部开票信息")).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "填写数电专票信息" })).toHaveFocus();
  });

  it("开票后填写发票信息区域显示厂端打款强提醒", () => {
    render(<App initialPage="store-invoices" />);

    expect(screen.getAllByText("历史讨论场景：开票后需回原系统提交")).toHaveLength(2);
    expect(screen.getAllByText("本原型不会上传发票、触发审核或打款。")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "门店前往开票系统开具数电专票，再将发票信息上传系统，否则将无法收款。" })).toBeInTheDocument();
    expect(screen.getAllByText("当月10号前开票提交，当月结算；10号后开票提交将在下月结算。")).toHaveLength(1);
    expect(screen.queryByText("下方提供收票方与开票信息，可一键复制；开票完成后必须返回系统提交发票信息。")).not.toBeInTheDocument();
    expect(screen.queryByText("仅看系统提交成功时间")).not.toBeInTheDocument();
  });

  it("提交前显示购买方和税率强校验原文", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);

    await user.clear(screen.getByLabelText("购买方"));
    await user.type(screen.getByLabelText("购买方"), "其他公司");
    await user.clear(screen.getByLabelText("税率"));
    await user.type(screen.getByLabelText("税率"), "3");
    await user.click(screen.getByRole("button", { name: "演示动作：校验并提交发票" }));

    expect(
      screen.getByText("发票对象开具错误，请检查开具至【比亚迪汽车销售有限公司】发票"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("发票税率错误，请开具6%税率的推广服务费发票至比亚迪汽车销售有限公司"),
    ).toBeInTheDocument();
  });

  it("购买方与税率由门店填写，税率仅接受数字并显示百分号", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);

    expect(screen.getByLabelText("购买方")).toHaveValue("");
    const rate = screen.getByLabelText("税率");
    expect(rate).toHaveValue("");
    await user.type(rate, "6abc");
    expect(rate).toHaveValue("6");
    expect(screen.getByText("%", { selector: ".input-suffix" })).toBeInTheDocument();
  });

  it("金额关系校验错误时显示两条强校验结果", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);

    await user.type(screen.getByLabelText("购买方"), "比亚迪汽车销售有限公司");
    await user.type(screen.getByLabelText("税率"), "6");
    await user.type(screen.getByLabelText("数电专票号码"), "25322000000178435216");
    await user.clear(screen.getByLabelText("不含税金额"));
    await user.type(screen.getByLabelText("不含税金额"), "100");
    await user.clear(screen.getByLabelText("税额"));
    await user.type(screen.getByLabelText("税额"), "5");
    await user.clear(screen.getByLabelText("价税合计"));
    await user.type(screen.getByLabelText("价税合计"), "128640.50");
    await user.click(screen.getByRole("button", { name: "演示动作：校验并提交发票" }));

    expect(screen.getByText("不含税金额 + 税额必须等于价税合计")).toBeInTheDocument();
    expect(screen.getByText("不含税金额 × 6% 与税额差异必须小于0.01元")).toBeInTheDocument();
  });

  it("页面真实提交路径拒绝已存在的发票号码", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);

    await user.type(screen.getByLabelText("购买方"), "比亚迪汽车销售有限公司");
    await user.type(screen.getByLabelText("税率"), "6");
    await user.type(screen.getByLabelText("数电专票号码"), promotionInvoices[0].invoiceNumber);
    await user.click(screen.getByRole("button", { name: "演示动作：校验并提交发票" }));

    expect(screen.getByText("该发票号码已提交，请检查后更换发票号码")).toBeInTheDocument();
  });

  it("门店历史汇总只使用当前门店记录", () => {
    const otherPromotion = promotionInvoices.find((invoice) => invoice.store !== "深圳龙岗比亚迪王朝店");
    const otherManagement = managementInvoices.find((invoice) => invoice.store !== "深圳龙岗比亚迪王朝店");
    const previousPromotion = { total: otherPromotion.total, confirmedAmount: otherPromotion.confirmedAmount };
    const previousManagement = { invoiceAmount: otherManagement.invoiceAmount };
    otherPromotion.total = 999999999;
    otherPromotion.confirmedAmount = 999999999;
    otherManagement.invoiceAmount = 999999999;

    try {
      render(<App initialPage="store-history" />);

      const metricStrip = screen.getByLabelText("推广服务费金额汇总");
      expect(within(metricStrip).getAllByText("¥128,640.50")).toHaveLength(3);
      expect(within(metricStrip).getAllByText("¥0.00")).toHaveLength(2);
      expect(screen.queryByText("¥999,999,999.00")).not.toBeInTheDocument();
    } finally {
      Object.assign(otherPromotion, previousPromotion);
      Object.assign(otherManagement, previousManagement);
    }
  });

  it("审核不通过的红冲重开动作只在门店端提醒", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);

    await user.selectOptions(screen.getByLabelText("选择场景"), "F07");
    await user.click(screen.getByRole("button", { name: "跳转到场景页面" }));
    expect(screen.getByText("发票审核不通过，请查看原因，红冲后重新开票上传")).toBeInTheDocument();
  });

  it("重新开票后审核未通过金额归零并展示最新状态", () => {
    render(<App initialPage="store-history" initialScenario="F07" />);

    expect(screen.getByText("发票审核通过已结算金额")).toBeInTheDocument();
    const failedAmountMetric = screen.getByText("发票审核未通过金额").closest("div");
    expect(within(failedAmountMetric).getByText("¥0.00")).toBeInTheDocument();
    expect(screen.getAllByText("已重新开具")).toHaveLength(2);
    expect(screen.getByText("差异金额将在下个账期调整")).toBeInTheDocument();
  });

  it("推广服务费按账期平铺最新发票状态且多账期重复显示发票数据", () => {
    render(<App initialPage="store-history" initialScenario="F07" />);

    const table = screen.getByRole("table", { name: "推广服务费发票记录" });
    for (const header of ["账期", "是否多账期开票", "金额", "发票号", "开票日期", "提交时间", "审核状态"]) {
      expect(within(table).getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(within(table).getAllByText("25322000000178435216")).toHaveLength(2);
    expect(within(table).getAllByText("¥128,640.50")).toHaveLength(2);
    expect(within(table).getAllByText("是")).toHaveLength(2);
    expect(within(table).getAllByText("已重新开具")).toHaveLength(2);
  });

  it("管理服务费按账期平铺并展示财务上传生成的提交时间", () => {
    render(<App initialPage="store-history" />);

    const table = screen.getByRole("table", { name: "管理服务费发票信息" });
    for (const header of ["账期", "金额", "发票号", "开票日期", "提交时间", "审核状态"]) {
      expect(within(table).getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(within(table).queryByRole("columnheader", { name: "是否多账期开票" })).not.toBeInTheDocument();
    expect(within(table).getByText("2026-08-08 11:25")).toBeInTheDocument();
  });

  it("时间线按当前场景点亮对应节点且采用确认后的文案", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByText("门店无确认，系统自动确认")).toBeInTheDocument();
    expect(screen.queryByText(/节假日不顺延/)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("选择场景"), "F06");
    await user.click(screen.getByRole("button", { name: "跳转到场景页面" }));
    const timelineInvoiceStep = screen.getAllByText("发票提交").find((node) => node.closest("li"));
    expect(timelineInvoiceStep.closest("li")).toHaveAttribute("aria-current", "step");
  });
});

describe("财务端财务流程", () => {
  it("财务端取消总览并默认直接进入推广服务费", () => {
    render(<App initialRole="finance" />);

    expect(screen.getByRole("heading", { name: "推广服务费" })).toBeInTheDocument();
    expect(screen.getByText("审核未通过金额")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "财务" })).not.toBeInTheDocument();
  });

  it("财务主导航按六个业务页面平铺", () => {
    render(<App initialRole="finance" />);

    const nav = screen.getByRole("navigation", { name: "财务管理页面" });
    expect(within(nav).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "推广服务费",
      "管理服务费",
      "订单明细",
      "门店基础信息",
      "账单异议",
      "导入记录",
    ]);
  });

  it("门店基础信息作为一级页面提供导入导出和SAP异议子页面", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" />);

    await user.click(screen.getByRole("button", { name: "门店基础信息" }));
    expect(screen.getByRole("heading", { name: "门店基础信息" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载基础信息导入模板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "演示动作：导入门店基础信息" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出门店基础信息" })).toBeInTheDocument();
    const tabs = screen.getByRole("tablist", { name: "门店基础信息页面" });
    expect(within(tabs).getByRole("tab", { name: "基础信息" })).toBeInTheDocument();
    expect(within(tabs).getByRole("tab", { name: "SAP异议处理" })).toBeInTheDocument();
    for (const header of ["门店ID（所属账户关联poi-id）", "服务店名称", "有效SAP编码", "最近导入时间", "SAP确认状态"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
  });

  it("财务端使用审核不通过状态且不展示账单版本", () => {
    render(<App initialRole="finance" initialPage="finance-promotion" />);

    expect(screen.getByRole("option", { name: "审核不通过，请重新上传" })).toBeInTheDocument();
    expect(screen.queryByText("审核不通过，请红冲重开")).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "账期" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "账期 / 版本" })).not.toBeInTheDocument();
    expect(screen.queryByText("2026-07 / V1")).not.toBeInTheDocument();
  });

  it("推广服务费可按账期筛选，并以筛选结果导出", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-promotion" />);

    await user.selectOptions(screen.getByLabelText("筛选账期"), "2026-06");
    expect(screen.getByText("杭州滨江海洋网店")).toBeInTheDocument();
    expect(screen.queryByText("深圳龙岗比亚迪王朝店")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "导出当前筛选结果" }));
    expect(screen.getByText("已按当前筛选导出 1 条记录")).toBeInTheDocument();
  });

  it("管理服务费可按账期筛选，并进入订单明细的管理服务费标签", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-management" />);

    await user.selectOptions(screen.getByLabelText("筛选账期"), "2026-06");
    expect(screen.getByText("杭州滨江海洋网店")).toBeInTheDocument();
    expect(screen.queryByText("深圳龙岗比亚迪王朝店")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看管理服务费订单明细" }));
    expect(screen.getByRole("heading", { name: "管理服务费订单明细" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "管理服务费明细" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "订单明细" })).toHaveAttribute("aria-current", "page");
  });

  it("财务主导航提供订单明细入口并可切换两类明细", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" />);

    await user.click(screen.getByRole("button", { name: "订单明细" }));
    expect(screen.getByRole("heading", { name: "推广服务费订单明细" })).toBeInTheDocument();
    const tabs = screen.getByRole("tablist", { name: "订单明细类型" });
    await user.click(within(tabs).getByRole("tab", { name: "管理服务费明细" }));
    expect(screen.getByRole("heading", { name: "管理服务费订单明细" })).toBeInTheDocument();
  });

  it("推广服务费订单明细展示退款负数行和最新财务字段", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-promotion" />);

    await user.click(screen.getByRole("button", { name: "查看推广服务费订单明细" }));
    expect(screen.getByRole("heading", { name: "推广服务费订单明细" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "推广服务费明细" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "订单明细" })).toHaveAttribute("aria-current", "page");
    for (const header of ["账期", "账单归属门店", "服务店名称", "有效 SAP", "销售渠道", "退款时间", "实收金额", "对应发票号码", "发票提交时间", "发票审核状态", "发票结算日期", "审核不通过原因"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    for (const removedHeader of ["认证主体", "退款金额", "调整后净基数", "调整后净费用", "历史账期补充金额", "调整来源账期"]) {
      expect(screen.queryByRole("columnheader", { name: removedHeader })).not.toBeInTheDocument();
    }
    expect(screen.getByText("-¥420.00")).toBeInTheDocument();
    expect(screen.getByText("2026-07-03 09:20")).toBeInTheDocument();
    const submittedRange = screen.getByRole("group", { name: "发票提交日期范围" });
    expect(within(submittedRange).getByLabelText("开始日期")).toBeInTheDocument();
    expect(within(submittedRange).getByLabelText("结束日期")).toBeInTheDocument();
    const verifiedRange = screen.getByRole("group", { name: "核销日期范围" });
    expect(within(verifiedRange).getByLabelText("开始日期")).toBeInTheDocument();
    expect(within(verifiedRange).getByLabelText("结束日期")).toBeInTheDocument();
    expect(screen.queryByText("发票提交开始日期")).not.toBeInTheDocument();
    expect(screen.queryByText("核销开始日期")).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索门店、SAP、发票号码、订单ID或SKU ID" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "直播" })).toBeInTheDocument();
    expect(screen.getByText("导出文件包含全部底层字段")).toBeInTheDocument();
  });

  it("财务订单明细将订单券状态及商品SKU分别展示为独立列", () => {
    render(<App initialRole="finance" initialPage="finance-orders" />);

    for (const header of ["订单", "券", "状态", "商品", "SKU ID", "原始费用"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    const table = screen.getByRole("table");
    for (const amount of ["¥1,027.20", "¥580.80", "-¥25.20"]) {
      expect(within(table).getByText(amount)).toBeInTheDocument();
    }
    expect(screen.queryByRole("columnheader", { name: "订单 / 券 / 状态" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "商品 / SKU" })).not.toBeInTheDocument();
  });

  it("推广与管理服务费在各自业务页发起厂家信息导入", async () => {
    const { unmount } = render(<App initialRole="finance" initialPage="finance-promotion" />);

    expect(screen.getByRole("button", { name: "下载推广费厂家导入模板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "演示动作：导入推广费厂家信息" })).toBeInTheDocument();

    unmount();
    render(<App initialRole="finance" initialPage="finance-management" />);
    expect(screen.getByRole("button", { name: "下载管理服务费厂家导入模板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "演示动作：导入管理服务费厂家信息" })).toBeInTheDocument();
  });

  it("SAP 异议主列表只展示处理后的有效 SAP", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-base-info" />);

    await user.click(screen.getByRole("tab", { name: "SAP异议处理" }));
    expect(screen.queryByText("门店基础信息 · 子页面")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "SAP异议处理" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "有效 SAP" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "门店 SAP" })).not.toBeInTheDocument();
  });

  it("订单明细按是否筛选提示导出范围", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-orders" />);

    const exportButton = screen.getByRole("button", { name: "导出数据" });
    expect(screen.queryByRole("button", { name: "导出全部底层字段" })).not.toBeInTheDocument();
    await user.click(exportButton);
    expect(screen.getByText("已导出全部数据，共 3 条")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("筛选账期"), "2026-06");
    await user.click(exportButton);
    expect(screen.getByText("已导出符合当前筛选条件的数据，共 1 条")).toBeInTheDocument();
  });

  it("门店基础信息的SAP异议子页面可导出差异并导入厂家最终编码", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-base-info" />);

    await user.click(screen.getByRole("tab", { name: "SAP异议处理" }));
    expect(screen.getByRole("button", { name: "导出 SAP 编码差异清单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载 SAP 编码确认模板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "演示动作：导入最终确认 SAP 编码" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "演示动作：导入最终确认 SAP 编码" }));
    for (const header of ["门店ID（所属账户关联poi-id）", "服务店名称", "财务初始导入SAP编码（若纯数字格式需为10位，不足前面需加0补、非纯数字无需修改）", "服务店编码", "厂家确认结果", "确认时间"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(screen.getByText("0010052209")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "演示动作：确认导入并更新有效SAP编码" }));
    expect(screen.getByText("广州番禺方程豹中心").closest("tr")).toHaveTextContent("已确认");
  });

  it("账单异议页面只显示金额费率异议", () => {
    render(<App initialRole="finance" initialPage="finance-disputes" />);

    expect(screen.getByRole("heading", { name: "账单异议" })).toBeInTheDocument();
    expect(screen.getByText("账单金额异议")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出账单异议" })).toBeInTheDocument();
    expect(screen.queryByText("SAP 差异")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /SAP/ })).not.toBeInTheDocument();
  });

  it("导入记录只保留日志且不再承担业务导入入口", () => {
    render(<App initialRole="finance" initialPage="finance-imports" />);

    expect(screen.getByText("留存政策待 DYDATA-19 财务与审计决策。", { exact: false })).toBeInTheDocument();
    expect(within(screen.getByRole("main")).queryByRole("button", { name: /导入/ })).not.toBeInTheDocument();
    for (const type of ["基础信息导入", "推广费厂家导入信息", "管理服务费厂家导入信息", "SAP编码确认"]) {
      expect(screen.getByText(type)).toBeInTheDocument();
    }
  });
});

describe("DYDATA-19 页面设计回环", () => {
  it("财务导航写入稳定业务路由并支持订单费用子路由", async () => {
    window.history.replaceState({}, "", "/finance/promotion");
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("heading", { name: "推广服务费" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "管理服务费" }));
    expect(window.location.pathname).toBe("/finance/management");
    await user.click(screen.getByRole("button", { name: "查看管理服务费订单明细" }));
    expect(window.location.pathname).toBe("/finance/orders/management");
  });

  it("财务指标可在单月与累计之间切换并说明累计起算月", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-promotion" />);

    expect(screen.getByRole("button", { name: "单月" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "累计" }));
    expect(screen.getByText("累计自 2026 年 8 月起，不含 2026 年 7 月演示数据")).toBeInTheDocument();
    expect(screen.getByText("已确认金额（仅单月）")).toBeInTheDocument();
  });

  it("推广费展示完整状态链并明确系统内不审核", () => {
    render(<App initialRole="finance" initialPage="finance-promotion" />);

    for (const label of ["待开票", "提交成功，待厂端审核", "审核通过，已结算", "审核不通过，请重新上传"]) {
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText("审核在系统外完成；管理员只导入结果，系统内不创建待审核任务。", { exact: false })).toBeInTheDocument();
  });

  it("导入原型覆盖无变化、差异覆盖、整批失败和版本冲突", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-management" />);
    await user.click(screen.getByRole("button", { name: "演示动作：导入管理服务费厂家信息" }));

    for (const status of ["首次成功", "无变化", "差异待确认", "整批失败", "版本冲突"]) {
      expect(screen.getByRole("option", { name: status })).toBeInTheDocument();
    }
    await user.selectOptions(screen.getByRole("combobox", { name: "导入结果场景" }), "整批失败");
    expect(screen.getByText("整批未写入")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载全部错误" })).toBeInTheDocument();
  });
});
