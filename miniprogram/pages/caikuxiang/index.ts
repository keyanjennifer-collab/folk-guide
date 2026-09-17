import { getTheme, AppTheme } from "../../services/theme";
import { PRODUCTS } from "../../data/products";
import { readCart, changeCart, CartItem } from "../../services/cart";
Page({
  data: { themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    products: PRODUCTS, visibleProducts: PRODUCTS, gift: PRODUCTS[0], category: "all",
    filters: [{ id: "all", name: "全部香品" }, { id: "set", name: "线香套装" }, { id: "single", name: "五色单香" }],
    cartItems: [] as CartItem[], cartCount: 0, cartTotal: 0, showCart: false, showSaleNotice: false,
  },
  onShow() { const theme = getTheme(); this.setData({ theme, themeClass: `theme-${theme}` });
    (this as any).getTabBar?.()?.setData({ selected: 1 });
    this.syncCart();
    if (wx.getStorageSync("wuse-open-cart-on-show")) {
      wx.setStorageSync("wuse-open-cart-on-show", false);
      this.setData({ showCart: true });
    }
  },
  syncCart() {
    const cartItems = readCart();
    this.setData({ cartItems, cartCount: cartItems.reduce((sum, item) => sum + item.quantity, 0), cartTotal: cartItems.reduce((sum, item) => sum + item.subtotal, 0) });
  },
  filterProducts(event: WechatMiniprogram.TouchEvent) {
    const category = String(event.currentTarget.dataset.id);
    this.setData({ category, visibleProducts: PRODUCTS.filter(item => category === "all" || item.category === category) });
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
    this.setData({ showSaleNotice: true });
  },
  closeSaleNotice() { this.setData({ showSaleNotice: false }); },
  noop() {},
});


