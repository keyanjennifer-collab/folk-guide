import { getTheme, AppTheme } from "../../services/theme";
import { readCart, removeCartItems } from "../../services/cart";
import { getApiErrorMessage } from "../../services/api";
import { ShippingAddress, ShippingAddressInput, createAddress, createOrder, deleteAddress, getAddresses, getCatalog, payOrder, updateAddress } from "../../services/commerce";

type CheckoutItem = ReturnType<typeof readCart>[number] & { priceText: string; subtotalText: string; available: number };
const emptyAddress = (): ShippingAddressInput => ({ recipient_name: "", phone: "", province: "", city: "", district: "", detail: "", postal_code: "", is_default: true });
function key(): string { return `wx_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`; }

Page({
  data: {
    themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    loading: true, submitting: false, error: "", saleEnabled: false,
    items: [] as CheckoutItem[], addresses: [] as ShippingAddress[], selectedAddressId: 0,
    selectedAddress: null as ShippingAddress | null, showAddressForm: false, editingAddressId: 0,
    addressForm: emptyAddress(), region: [] as string[], regionText: "", remark: "", agreed: false,
    subtotalFen: 0, shippingFen: 0, totalFen: 0, subtotalText: "0.00", shippingText: "0.00", totalText: "0.00",
    freeShippingText: "", shippingEta: "", idempotencyKey: key(),
  },
  onLoad() { void this.loadCheckout(); },
  onShow() { const theme = getTheme(); this.setData({ theme, themeClass: `theme-${theme}` }); },
  async loadCheckout() {
    // 本机购物袋只保存选择；进入结算页后必须重新读取服务端价格和库存。
    const cart = readCart();
    if (!cart.length) { this.setData({ loading: false, error: "购物袋还是空的" }); return; }
    this.setData({ loading: true, error: "" });
    try {
      const [catalog, addresses] = await Promise.all([getCatalog(), getAddresses()]);
      const byId = new Map(catalog.items.map(item => [item.id, item]));
      const items = cart.map(item => {
        const live = byId.get(item.id);
        const price = live?.price_fen ?? Math.round(item.price * 100);
        return { ...item, price: price / 100, subtotal: price * item.quantity / 100,
          priceText: (price / 100).toFixed(2), subtotalText: (price * item.quantity / 100).toFixed(2),
          available: live?.available ?? 0 };
      });
      const unavailable = items.find(item => !byId.get(item.id)?.active || item.available < item.quantity);
      const subtotalFen = items.reduce((sum, item) => sum + Math.round(item.subtotal * 100), 0);
      const shippingFen = subtotalFen >= catalog.free_shipping_threshold_fen ? 0 : catalog.shipping_fee_fen;
      const selectedAddress = addresses.find(item => item.is_default) || addresses[0] || null;
      this.setData({
        loading: false, saleEnabled: catalog.sale_enabled, items, addresses,
        selectedAddress, selectedAddressId: selectedAddress?.id || 0, showAddressForm: !selectedAddress,
        subtotalFen, shippingFen, totalFen: subtotalFen + shippingFen,
        subtotalText: (subtotalFen / 100).toFixed(2), shippingText: (shippingFen / 100).toFixed(2),
        totalText: ((subtotalFen + shippingFen) / 100).toFixed(2),
        freeShippingText: `满 ¥${(catalog.free_shipping_threshold_fen / 100).toFixed(0)} 包邮`,
        shippingEta: catalog.shipping_eta,
        error: unavailable ? `${unavailable.name} 库存不足，请返回购物袋调整数量` : "",
      });
    } catch (error) {
      this.setData({ loading: false, error: getApiErrorMessage(error, "结算信息暂时无法读取") });
    }
  },
  selectAddress(event: WechatMiniprogram.TouchEvent) {
    const selectedAddressId = Number(event.currentTarget.dataset.id);
    this.setData({ selectedAddressId, selectedAddress: this.data.addresses.find(item => item.id === selectedAddressId) || null });
  },
  openAddressForm() { this.setData({ showAddressForm: true, editingAddressId: 0, addressForm: emptyAddress(), region: [], regionText: "" }); },
  closeAddressForm() { if (this.data.addresses.length) this.setData({ showAddressForm: false }); },
  editSelectedAddress() {
    const selected = this.data.selectedAddress; if (!selected) return;
    const region = [selected.province, selected.city, selected.district].filter(Boolean);
    this.setData({ showAddressForm: true, editingAddressId: selected.id, region, regionText: region.join(" / "),
      addressForm: { recipient_name: selected.recipient_name, phone: selected.phone, province: selected.province,
        city: selected.city, district: selected.district, detail: selected.detail,
        postal_code: selected.postal_code || "", is_default: true } });
  },
  inputAddress(event: WechatMiniprogram.Input) {
    const field = String(event.currentTarget.dataset.field) as keyof ShippingAddressInput;
    this.setData({ [`addressForm.${field}`]: event.detail.value } as WechatMiniprogram.Page.DataOption);
  },
  changeRegion(event: WechatMiniprogram.PickerChange) {
    const region = event.detail.value as string[];
    this.setData({ region, regionText: region.join(" / "), "addressForm.province": region[0] || "", "addressForm.city": region[1] || "", "addressForm.district": region[2] || "" });
  },
  useWechatAddress() {
    const editingAddressId = this.data.showAddressForm ? this.data.editingAddressId : 0;
    wx.chooseAddress({
      success: (value) => this.setData({
        showAddressForm: true,
        editingAddressId,
        region: [value.provinceName, value.cityName, value.countyName],
        regionText: [value.provinceName, value.cityName, value.countyName].filter(Boolean).join(" / "),
        addressForm: {
          recipient_name: value.userName, phone: value.telNumber, province: value.provinceName,
          city: value.cityName, district: value.countyName, detail: value.detailInfo,
          postal_code: value.postalCode || "", is_default: true,
        },
      }),
    });
  },
  async saveAddress() {
    try {
      const saved = this.data.editingAddressId
        ? await updateAddress(this.data.editingAddressId, this.data.addressForm)
        : await createAddress(this.data.addressForm);
      const addresses = [saved, ...this.data.addresses.filter(item => item.id !== saved.id).map(item => ({ ...item, is_default: false }))];
      this.setData({ addresses, selectedAddress: saved, selectedAddressId: saved.id, showAddressForm: false, editingAddressId: 0 });
    } catch (_) { /* request 已统一展示后端校验信息 */ }
  },
  deleteSelectedAddress() {
    const selected = this.data.selectedAddress; if (!selected) return;
    wx.showModal({ title: "删除收货地址", content: "确定删除当前地址吗？", success: async result => {
      if (!result.confirm) return;
      try {
        await deleteAddress(selected.id);
        const addresses = this.data.addresses.filter(item => item.id !== selected.id);
        const next = addresses[0] || null;
        this.setData({ addresses, selectedAddress: next, selectedAddressId: next?.id || 0, showAddressForm: !next });
      } catch (_) { /* 请求层已展示错误 */ }
    } });
  },
  inputRemark(event: WechatMiniprogram.Input) { this.setData({ remark: event.detail.value }); },
  changeAgreement(event: WechatMiniprogram.CheckboxGroupChange) { this.setData({ agreed: event.detail.value.includes("yes") }); },
  toPolicy() { wx.navigateTo({ url: "/pages/checkout/policy" }); },
  toShop() { wx.switchTab({ url: "/pages/caikuxiang/index" }); },
  async submitOrder() {
    if (this.data.submitting || this.data.error) return;
    if (!this.data.saleEnabled) { wx.showToast({ title: "商城尚未正式开启收款", icon: "none" }); return; }
    if (!this.data.selectedAddressId) { wx.showToast({ title: "请先填写收货地址", icon: "none" }); return; }
    if (!this.data.agreed) { wx.showToast({ title: "请先阅读并同意购买须知", icon: "none" }); return; }
    this.setData({ submitting: true });
    try {
      // 页面生命周期内复用同一个幂等键，防止快速连点或弱网重试产生重复订单。
      const order = await createOrder({
        items: this.data.items.map(item => ({ product_id: item.id, quantity: item.quantity })),
        address_id: this.data.selectedAddressId, idempotency_key: this.data.idempotencyKey,
        remark: this.data.remark.trim(),
      });
      // 订单已经在服务端成立，即使用户取消付款也应从“我的订单”继续，而非再次下单。
      removeCartItems(this.data.items.map(item => item.id));
      try {
        await payOrder(order.id);
        wx.showToast({ title: "支付成功", icon: "success" });
      } catch (paymentError) {
        const raw = String((paymentError as { errMsg?: unknown })?.errMsg || (paymentError as Error)?.message || "");
        wx.showToast({ title: raw.includes("cancel") ? "订单已创建，可稍后支付" : "支付未完成，请在订单中重试", icon: "none", duration: 2600 });
      }
      setTimeout(() => wx.redirectTo({ url: "/pages/orders/index?status=all" }), 700);
    } catch (_) {
      this.setData({ idempotencyKey: key() });
    } finally { this.setData({ submitting: false }); }
  },
});
