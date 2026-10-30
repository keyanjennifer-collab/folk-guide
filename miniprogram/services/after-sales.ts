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
  if (typeof wx.getDeviceInfo === "function" && wx.getDeviceInfo().platform === "devtools") {
    wx.showModal({ title: "请用手机测试客服", content: "请使用微信扫描开发者工具的预览二维码，在手机小程序中点击客服。开发者工具中的打开结果不能用于确认客服是否接通。", showCancel: false });
    return;
  }
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
  const chatContact = contact;
  wx.openCustomerServiceChat({
    corpId: chatContact.corp_id, extInfo: { url: chatContact.url },
    showMessageCard: !!orderNumber,
    sendMessageTitle: orderNumber ? `订单售后咨询：${orderNumber}` : "五色知时售后咨询",
    sendMessagePath: "pages/orders/index",
    fail: error => {
      if (error.errMsg?.includes("cancel")) return;
      const detail = String(error.errMsg || "微信未提供失败原因").slice(0, 400);
      const errCode = (error as WechatMiniprogram.GeneralCallbackResult & { errCode?: number }).errCode;
      const diagnostic = `微信客服打开失败\n${detail}${errCode === undefined ? "" : `\n错误码：${errCode}`}\n企业ID：${chatContact.corp_id}\n客服链接：${chatContact.url}`;
      const hint = /devtools|simulator|开发者工具/i.test(detail)
        ? "请在手机微信中打开小程序后测试客服。"
        : "请复制错误信息交给商家核查微信客服的关联和接入配置。";
      wx.showModal({
        title: "暂时无法打开客服", content: `${hint}\n微信提示：${detail}\n${fallback}`,
        confirmText: "复制错误", cancelText: "关闭",
        success: result => { if (result.confirm) wx.setClipboardData({ data: diagnostic }); },
      });
    },
  });
}
