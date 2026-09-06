import { PRODUCTS } from "../../data/products";
import { readCart, changeCart, CartItem } from "../../services/cart";
Page({
  data: {
    products: PRODUCTS, visibleProducts: PRODUCTS, gift: PRODUCTS[0], category: "all",
    filters: [{ id: "all", name: "全部香品" }, { id: "set", name: "线香套装" }, { id: "single", name: "五色单香" }],
    cartItems: [] as CartItem[], cartCount: 0, cartTotal: 0, showCart: false,
  },
  onShow() { this.syncCart(); },
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
    wx.showModal({ title: "商城尚未开售", content: "选香清单已保存在本机。当前价格为参考价，在线下单和微信支付开放后即可购买；现在不会生成订单或扣款。", showCancel: false, confirmText: "继续选香" });
  },
  noop() {},
});
