import { getTheme, AppTheme } from "../../services/theme";
import { getApiErrorMessage, getToken } from "../../services/api";
import { Order, ORDER_LABELS, getOrders } from "../../services/orders";
import { PRODUCTS } from "../../data/products";
import { cancelOrder, completeOrder, payOrder, refundOrder } from "../../services/commerce";
type OrderView = Order & { statusLabel: string; amount: string; subtotal: string; shipping: string; dateLabel: string; thumbnail: string; itemLabel: string; quantity: number; preorder: boolean; shippingEta: string };
let requestVersion = 0;
Page({
  data: { themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    status: "all", loggedIn: false, loading: false, error: "", orders: [] as OrderView[], hasMore: false,
    tabs: [{ id: "all", label: "全部" }, { id: "pending", label: "待付款" }, { id: "paid", label: "待发货" }, { id: "shipped", label: "待收货" }, { id: "completed", label: "已完成" }, { id: "after_sale", label: "退款中" }, { id: "refunded", label: "已退款" }, { id: "cancelled", label: "已取消" }],
    selected: null as OrderView | null,
    actionLoading: false,
  },
  onLoad(options: Record<string, string>) {
    if (options.status && this.data.tabs.some(item => item.id === options.status)) this.setData({ status: options.status });
  },
  onShow() { const theme = getTheme(); this.setData({ theme, themeClass: `theme-${theme}` }); this.setData({ loggedIn: !!getToken(), selected: null, orders: [] }); void this.loadOrders(); },
  onHide() { requestVersion++; this.setData({ loading: false, selected: null, orders: [] }); },
  onUnload() { requestVersion++; },
  onPullDownRefresh() { void this.loadOrders().finally(() => wx.stopPullDownRefresh()); },
  onReachBottom() { if (this.data.hasMore && !this.data.loading && !this.data.error) void this.loadOrders(true); },
  async loadOrders(append = false) {
    const version = ++requestVersion;
    if (!getToken()) { this.setData({ loggedIn: false, orders: [], loading: false, hasMore: false }); return; }
    const previous = append ? this.data.orders : [];
    this.setData({ loading: true, error: "", orders: previous });
    try {
      const result = await getOrders(this.data.status, previous.length);
      if (version !== requestVersion) return;
      const orders = result.items.map(item => ({
        ...item, statusLabel: ORDER_LABELS[item.status], amount: (item.total_fen / 100).toFixed(2), subtotal: (item.subtotal_fen / 100).toFixed(2), shipping: (item.shipping_fee_fen / 100).toFixed(2),
        dateLabel: item.created_at.slice(0, 10), thumbnail: PRODUCTS.find(p => p.id === item.items[0]?.product_id)?.image || PRODUCTS[0].image,
        itemLabel: item.items.map(p => p.name).join("、"), quantity: item.items.reduce((n, p) => n + p.quantity, 0),
        preorder: item.items.some(p => p.sale_mode === "preorder"),
        shippingEta: item.items.find(p => p.shipping_eta)?.shipping_eta || "",
      }));
      this.setData({ orders: [...previous, ...orders], hasMore: result.has_more });
    } catch (error) {
      if (version === requestVersion) this.setData({ error: getApiErrorMessage(error, "订单暂时无法读取，请重试") });
    } finally { if (version === requestVersion) this.setData({ loading: false }); }
  },
  retry() { void this.loadOrders(); },
  selectTab(event: WechatMiniprogram.TouchEvent) { this.setData({ status: event.currentTarget.dataset.id, orders: [], selected: null }); void this.loadOrders(); },
  toLogin() { wx.switchTab({ url: "/pages/settings/index" }); },
  toShop() { wx.switchTab({ url: "/pages/caikuxiang/index" }); },
  showDetail(event: WechatMiniprogram.TouchEvent) { this.setData({ selected: this.data.orders.find(item => item.id === Number(event.currentTarget.dataset.id)) || null }); },
  closeDetail() { this.setData({ selected: null }); },
  copyTracking() { if (this.data.selected?.tracking_number) wx.setClipboardData({ data: this.data.selected.tracking_number }); },
  copyNumber() { if (this.data.selected) wx.setClipboardData({ data: this.data.selected.number }); },
  async paySelected() {
    const order = this.data.selected; if (!order || this.data.actionLoading) return;
    this.setData({ actionLoading: true });
    try { await payOrder(order.id); wx.showToast({ title: "支付已提交", icon: "success" }); this.setData({ selected: null }); setTimeout(() => void this.loadOrders(), 1200); }
    catch (error) { const raw = String((error as { errMsg?: unknown })?.errMsg || ""); if (raw.includes("cancel")) wx.showToast({ title: "已取消支付", icon: "none" }); }
    finally { this.setData({ actionLoading: false }); }
  },
  cancelSelected() { this.confirmAction("确定取消这张待付款订单吗？", id => cancelOrder(id)); },
  refundSelected() { this.confirmAction("确认申请整单原路退款吗？", id => refundOrder(id)); },
  completeSelected() { this.confirmAction("确认已经收到商品吗？", id => completeOrder(id)); },
  confirmAction(content: string, action: (id: number) => Promise<unknown>) {
    const order = this.data.selected; if (!order || this.data.actionLoading) return;
    wx.showModal({ title: "请确认", content, success: async result => {
      if (!result.confirm) return;
      this.setData({ actionLoading: true });
      try { await action(order.id); this.setData({ selected: null }); await this.loadOrders(); wx.showToast({ title: "操作成功", icon: "success" }); }
      catch (_) { /* 请求层已展示错误 */ }
      finally { this.setData({ actionLoading: false }); }
    } });
  },
  noop() {},
});


