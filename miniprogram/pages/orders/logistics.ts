import { getApiErrorMessage, getToken, isApiError } from "../../services/api";
import { contactAfterSales, prepareAfterSalesContact } from "../../services/after-sales";
import { getOrderLogistics, LogisticsEvent, logisticsTimeLabel, OrderLogistics } from "../../services/logistics";
import { ORDER_LABELS } from "../../services/orders";
import { getTheme } from "../../services/theme";

type EventView = LogisticsEvent & { timeLabel: string };

Page({
  _orderId: 0,
  _requestVersion: 0,
  data: {
    themeClass: "theme-" + getTheme(), loggedIn: false, loading: false, error: "",
    logistics: null as OrderLogistics | null, statusLabel: "", updatedLabel: "",
    orderEvents: [] as EventView[], trackingEvents: [] as EventView[],
  },
  onLoad(options: Record<string, string>) {
    const orderId = Number(options.id);
    this._orderId = Number.isSafeInteger(orderId) && orderId > 0 ? orderId : 0;
  },
  onShow() {
    this.setData({ themeClass: "theme-" + getTheme() });
    void prepareAfterSalesContact();
    void this.loadLogistics();
  },
  onHide() { this.clearView(); },
  onUnload() { this._requestVersion++; },
  onPullDownRefresh() { void this.loadLogistics().finally(() => wx.stopPullDownRefresh()); },
  clearView() {
    this._requestVersion++;
    this.setData({ logistics: null, orderEvents: [], trackingEvents: [], loading: false, statusLabel: "", updatedLabel: "" });
  },
  async loadLogistics() {
    this.clearView();
    const version = this._requestVersion;
    const token = getToken();
    this.setData({ loggedIn: !!token, error: "" });
    if (!token) return;
    if (!this._orderId) { this.setData({ error: "订单信息无效，请返回订单页重新进入" }); return; }
    this.setData({ loading: true });
    try {
      const result = await getOrderLogistics(this._orderId);
      if (version !== this._requestVersion || token !== getToken()) return;
      const toView = (event: LogisticsEvent): EventView => ({ ...event, timeLabel: logisticsTimeLabel(event.time) });
      this.setData({
        logistics: result, statusLabel: ORDER_LABELS[result.order_status],
        updatedLabel: logisticsTimeLabel(result.tracking_updated_at),
        orderEvents: result.order_events.map(toView), trackingEvents: result.tracking_events.map(toView),
      });
    } catch (error) {
      if (version !== this._requestVersion || token !== getToken()) return;
      if (isApiError(error, 401) || isApiError(error, 403)) {
        this.setData({ loggedIn: false });
      } else {
        this.setData({ error: getApiErrorMessage(error, "物流信息暂时无法读取，请稍后重试") });
      }
    } finally {
      if (version === this._requestVersion) this.setData({ loading: false });
    }
  },
  retry() { void this.loadLogistics(); },
  copyTracking() {
    if (this.data.logistics?.tracking_number) wx.setClipboardData({ data: this.data.logistics.tracking_number });
  },
  copyOrderNumber() {
    if (this.data.logistics) wx.setClipboardData({ data: this.data.logistics.order_number });
  },
  contactSupport() { contactAfterSales(this.data.logistics?.order_number); },
  toLogin() { wx.switchTab({ url: "/pages/settings/index" }); },
  toOrders() { wx.redirectTo({ url: "/pages/orders/index" }); },
});
