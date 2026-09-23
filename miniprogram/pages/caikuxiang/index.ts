import { getTheme, AppTheme } from "../../services/theme";
import { PRODUCTS } from "../../data/products";
import { readCart, changeCart, CartItem } from "../../services/cart";
import { getCatalog } from "../../services/commerce";
const INITIAL_PRODUCTS = PRODUCTS.map(product => ({ ...product, available: 0, active: true }));
Page({
  data: { themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    products: INITIAL_PRODUCTS, visibleProducts: INITIAL_PRODUCTS, gift: INITIAL_PRODUCTS[0], category: "all",
    filters: [{ id: "all", name: "全部香品" }, { id: "set", name: "线香套装" }, { id: "single", name: "五色单香" }],
    cartItems: [] as CartItem[], cartCount: 0, cartTotal: 0, showCart: false,
    saleEnabled: false, saleNote: "正在读取正式价格与库存…",
  },
  onShow() { const theme = getTheme(); this.setData({ theme, themeClass: `theme-${theme}` });
    (this as any).getTabBar?.()?.setData({ selected: 1 });
    this.syncCart();
    void this.syncCatalog();
    if (wx.getStorageSync("wuse-open-cart-on-show")) {
      wx.setStorageSync("wuse-open-cart-on-show", false);
      this.setData({ showCart: true });
    }
  },
  async syncCatalog() {
    try {
      const catalog = await getCatalog();
      const live = new Map(catalog.items.map(item => [item.id, item]));
      const products = PRODUCTS.map(product => ({ ...product,
        price: (live.get(product.id)?.price_fen ?? product.price * 100) / 100,
        available: live.get(product.id)?.available ?? 0,
        active: live.get(product.id)?.active ?? false,
      }));
      const visibleProducts = products.filter(item => this.data.category === "all" || item.category === this.data.category);
      this.setData({ products, visibleProducts, gift: products[0], saleEnabled: catalog.sale_enabled,
        saleNote: catalog.sale_enabled ? `正式开售 · 满 ¥${(catalog.free_shipping_threshold_fen / 100).toFixed(0)} 包邮` : "商城收款尚未开启" });
    } catch (_) { this.setData({ saleEnabled: false, saleNote: "正式价格与库存暂时无法读取" }); }
  },
  syncCart() {
    const cartItems = readCart();
    this.setData({ cartItems, cartCount: cartItems.reduce((sum, item) => sum + item.quantity, 0), cartTotal: cartItems.reduce((sum, item) => sum + item.subtotal, 0) });
  },
  filterProducts(event: WechatMiniprogram.TouchEvent) {
    const category = String(event.currentTarget.dataset.id);
    this.setData({ category, visibleProducts: this.data.products.filter(item => category === "all" || item.category === category) });
  },
  showProduct(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: "/pages/product/index?id=" + event.currentTarget.dataset.id }); },
  toGift() { wx.navigateTo({ url: "/pages/product/index?id=gift" }); },
  openCart() { this.syncCart(); this.setData({ showCart: true }); },
  closeCart() { this.setData({ showCart: false }); },
  changeQuantity(event: WechatMiniprogram.TouchEvent) {
    try { changeCart(String(event.currentTarget.dataset.id), Number(event.currentTarget.dataset.delta)); this.syncCart(); }
    catch (_) { wx.showToast({ title: "购物袋保存失败，请重试", icon: "none" }); }
  },
  checkout() {
    if (!this.data.cartItems.length) return;
    if (!this.data.saleEnabled) { wx.showToast({ title: "商城尚未正式开启收款", icon: "none" }); return; }
    this.setData({ showCart: false });
    wx.navigateTo({ url: "/pages/checkout/index" });
  },
  noop() {},
});


