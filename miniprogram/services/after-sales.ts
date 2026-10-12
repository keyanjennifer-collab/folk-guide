import { request } from "./api";

interface AfterSalesContact {
  available: boolean; corp_id: string; url: string; fallback_contact: string;
}

let contact: AfterSalesContact | null = null;

// 在页面显示时预载，点击处理函数直接调用微信客服，保留用户点击上下文。
export async function prepareAfterSalesContact(): Promise<void> {
  try {
    contact = await request<AfterSalesContact>({ path: "/api/after-sales/contact", auth: false, showError: false });
  } catch (_) { contact = null; }
}

export function contactAfterSales(orderNumber?: string): void {
  if (!contact) {
    void prepareAfterSalesContact().then(() => wx.showToast({
      title: contact ? "客服信息已更新，请再次点击" : "客服暂时无法连接，请稍后重试", icon: "none",
    }));
    return;
  }
  const fallback = contact.fallback_contact && !contact.fallback_contact.includes("请填写")
    ? `您也可以通过以下方式联系我们：${contact.fallback_contact}` : "客服正在准备中，请稍后再试。";
  if (!contact.available) {
    wx.showModal({ title: "售后客服", content: fallback, showCancel: false });
    return;
  }
  if (!wx.canIUse("openCustomerServiceChat")) {
    wx.showModal({ title: "请升级微信", content: "当前微信版本暂不支持微信客服，请更新后重试。" + fallback, showCancel: false });
    return;
  }
  wx.openCustomerServiceChat({
    corpId: contact.corp_id, extInfo: { url: contact.url },
    showMessageCard: !!orderNumber,
    sendMessageTitle: orderNumber ? `订单售后咨询：${orderNumber}` : "五色知时售后咨询",
    sendMessagePath: "pages/orders/index",
    fail: error => {
      if (error.errMsg?.includes("cancel")) return;
      wx.showModal({ title: "暂时无法打开客服", content: "请稍后重试。" + fallback, showCancel: false });
    },
  });
}
