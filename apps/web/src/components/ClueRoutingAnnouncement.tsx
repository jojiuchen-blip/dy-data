import { useRef, useState } from "react";
import { Button } from "./Button";
import { Dialog } from "./Dialog";

const title = "精诚养车首批商品线索已正式开启流转";
const summary = `${title}。新线索到店后，请在24小时内完成首次跟进并提交结果。`;

export function ClueRoutingAnnouncement() {
  const [open, setOpen] = useState(false);
  const [paused, setPaused] = useState(false);
  const detailsButton = useRef<HTMLButtonElement>(null);

  return (
    <div className="workspace-announcement" role="group" aria-label="线索中心公告">
      <span className="workspace-announcement__label">公告</span>
      <div
        className="workspace-announcement__viewport"
        onDoubleClick={() => setOpen(true)}
        title="双击查看公告全文"
      >
        <div className="workspace-announcement__track" data-paused={paused}>
          <span>{summary}</span>
          <span aria-hidden="true">{summary}</span>
        </div>
      </div>
      <button
        aria-haspopup="dialog"
        aria-label="查看线索流转公告全文"
        className="ui-button ui-button--text ui-button--sm"
        ref={detailsButton}
        type="button"
        onClick={() => setOpen(true)}
      >
        <span className="ui-button__label">查看全文</span>
      </button>
      <Button
        aria-label={paused ? "继续滚动" : "暂停滚动"}
        className="workspace-announcement__pause"
        size="sm"
        variant="text"
        onClick={() => setPaused(!paused)}
      >
        {paused ? "继续" : "暂停"}
      </Button>
      <Dialog
        bodyClassName="workspace-announcement__body"
        onClose={() => setOpen(false)}
        open={open}
        panelClassName="workspace-announcement-dialog"
        returnFocusRef={detailsButton}
        title={title}
      >
        <p>各位门店同事，11月24日，经营引擎已正式开启首批9个精诚养车商品的线索流转。开启后首次入库的试点商品线索按新规则分配，已经进入引擎的线索沿用原规则。</p>
        <ul>
          <li><strong>首次跟进。</strong>收到新线索后，请在24小时内完成首次跟进，并在线索中心提交实际跟进结果。超时未提交，系统会尝试续派，最后一轮到期后关闭。</li>
          <li><strong>分配顺序。</strong>符合条件的销售店优先，其次为同城10公里内优选，最后为同城兜底。每轮只分配给一家商品适用门店。</li>
          <li><strong>保护期。</strong>已预约须填写预约日期和时间，保护期至预约时间后72小时。改为待进一步跟进或未联系上，从提交起保留168小时。实际改约请及时更新预约时间，重复提交同一状态只保留原截止时间。</li>
          <li><strong>关单。</strong>未联系上到期仍未联系上时关闭。提交战败、客户要求换店，或订单确认核销、全额退款、失效时关闭。</li>
        </ul>
      </Dialog>
    </div>
  );
}
