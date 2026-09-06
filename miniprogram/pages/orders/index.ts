import { getApiErrorMessage, getToken } from "../../services/api";
import { Order, ORDER_LABELS, getOrders } from "../../services/orders";
import { PRODUCTS } from "../../data/products";
type OrderView = Order & { statusLabel: string; amount: string; dateLabel: string; thumbnail: string; itemLabel: string; quantity: number };
let requestVersion = 0;
Page({
  data: {
    status: "all", loggedIn: false, loading: false, error: "", orders: [] as OrderView[], hasMore: false,
    tabs: [{ id: "all", label: "全部" }, { id: "pending", label: "待付款" }, { id: "paid", label: "待发货" }, { id: "shipped", label: "待收货" }, { id: "completed", label: "已完成" }, { id: "after_sale", label: "售后" }, { id: "cancelled", label: "已取消" }],
    selected: null as OrderView | null,
  },
  onLoad(options: Record<string, string>) {
    if (options.status && this.data.tabs.some(item => item.id === options.status)) this.setData({ status: options.status });
  },
  onShow() { this.setData({ loggedIn: !!getToken(), selected: null, orders: [] }); void this.loadOrders(); },
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
        ...item, statusLabel: ORDER_LABELS[item.status], amount: (item.total_fen / 100).toFixed(2),
        dateLabel: item.created_at.slice(0, 10), thumbnail: PRODUCTS.find(p => p.id === item.items[0]?.product_id)?.image || "/assets/brand/gift.jpg",
        itemLabel: item.items.map(p => p.name).join("、"), quantity: item.items.reduce((n, p) => n + p.quantity, 0),
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
  noop() {},
});
