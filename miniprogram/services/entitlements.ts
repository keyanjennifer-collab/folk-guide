/** 个人五色与测一测共用的权益文案、购买引导。权限仍由后端逐次校验。 */
import { AIQuota, getAIQuota } from "./ai";
import { getApiErrorMessage, getToken } from "./api";

export function entitlementPresentation(quota: Pick<AIQuota, "active" | "plan" | "expires_at">): { title: string; description: string } {
  if (!quota.active) return {
    title: "7天体验已结束",
    description: "购买268元五色套装，赠送小程序全部功能永久使用权。",
  };
  if (quota.plan === "gift_lifetime") return {
    title: "全部功能 · 永久使用",
    description: "五色套装赠送权益已开通，可使用个人五色与测一测全部功能。",
  };
  const raw = quota.expires_at || "";
  const expiry = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`;
  const days = Math.max(0, Math.ceil((new Date(expiry).getTime() - Date.now()) / 86_400_000)) || 0;
  return {
    title: quota.plan === "new_user_7_days" ? "新用户7天体验" : "个人服务已开通",
    description: `剩余${days}天，可使用个人五色与测一测全部功能。`,
  };
}

export function showFeatureAccessRequired(): void {
  wx.showModal({
    title: "7天体验已结束",
    content: "购买268元五色套装，即可获赠小程序全部功能的永久使用权。订单成功退款后，对应赠送权益将撤销。",
    confirmText: "查看套装", cancelText: "暂不购买",
    success: result => { if (result.confirm) wx.navigateTo({ url: "/pages/product/index?id=gift" }); },
  });
}

export async function ensureFeatureAccess(): Promise<boolean> {
  if (!getToken()) {
    wx.switchTab({ url: "/pages/settings/index" });
    return false;
  }
  try {
    if ((await getAIQuota()).active) return true;
    showFeatureAccessRequired();
  } catch (error) {
    wx.showToast({ title: getApiErrorMessage(error, "权益暂时无法读取，请重试"), icon: "none" });
  }
  return false;
}
