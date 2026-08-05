import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App.jsx";

describe("门店端财务流程", () => {
  it("分别展示推广服务费和管理服务费确认状态", () => {
    render(<App />);

    expect(screen.getAllByText("推广服务费").length).toBeGreaterThan(0);
    expect(screen.getAllByText("管理服务费").length).toBeGreaterThan(0);
    expect(screen.getAllByText("已确认").length).toBeGreaterThanOrEqual(2);
  });

  it("只在账单详情中显示异议入口", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.queryByRole("button", { name: "发起账单异议" })).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "查看账单详情" })[0]);
    expect(screen.getByRole("button", { name: "发起账单异议" })).toBeInTheDocument();
  });

  it("提交前显示购买方和税率强校验原文", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);

    await user.clear(screen.getByLabelText("购买方"));
    await user.type(screen.getByLabelText("购买方"), "其他公司");
    await user.selectOptions(screen.getByLabelText("税率"), "3");
    await user.click(screen.getByRole("button", { name: "校验并提交发票" }));

    expect(
      screen.getByText("发票对象开具错误，请检查开具至【比亚迪汽车销售有限公司】发票"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("发票税率错误，请开具6%税率的推广服务费发票至比亚迪汽车销售有限公司"),
    ).toBeInTheDocument();
  });
});

describe("财务端财务流程", () => {
  it("一级页只提供入口，金额指标进入推广服务费二级页后展示", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" />);

    expect(screen.queryByText("审核未通过金额")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "推广服务费" }));
    expect(screen.getByText("审核未通过金额")).toBeInTheDocument();
  });

  it("导入任一行失败时整批零写入", async () => {
    const user = userEvent.setup();
    render(<App initialRole="finance" initialPage="finance-imports" />);

    await user.click(screen.getByRole("button", { name: "演示含错误批次" }));
    expect(screen.getByText("整批校验失败，未写入任何记录")).toBeInTheDocument();
  });

  it("SAP 异议主列表只展示处理后的有效 SAP", () => {
    render(<App initialRole="finance" initialPage="finance-disputes" />);

    expect(screen.getByRole("columnheader", { name: "有效 SAP" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "门店 SAP" })).not.toBeInTheDocument();
  });
});
