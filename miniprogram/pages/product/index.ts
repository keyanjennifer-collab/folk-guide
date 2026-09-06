import { PRODUCTS, Product } from "../../data/products";
import { changeCart } from "../../services/cart";
Page({
  data: { product: null as Product | null, quantity: 1, images: [] as string[], added: false },
  onLoad(options: Record<string, string>) {
    const product = PRODUCTS.find(item => item.id === options.id);
    if (product) {
      this.setData({ product, images: product.id === "gift" ? [product.image, "/assets/brand/gift-open.jpg", "/assets/brand/five-set.jpg"] : [product.image] });
      wx.setNavigationBarTitle({ title: product.name });
    }
  },
  changeQuantity(event: WechatMiniprogram.TouchEvent) {
    this.setData({ quantity: Math.min(99, Math.max(1, this.data.quantity + Number(event.currentTarget.dataset.delta))), added: false });
  },
  addToBag() {
    if (!this.data.product) return;
    try {
      changeCart(this.data.product.id, this.data.quantity);
      this.setData({ added: true });
      wx.showToast({ title: "已加入购物袋", icon: "success" });
    } catch (_) { wx.showToast({ title: "保存失败，请重试", icon: "none" }); }
  },
  toShop() { wx.switchTab({ url: "/pages/caikuxiang/index" }); },
  onShareAppMessage() { return { title: this.data.product?.name || "五色知时", path: "/pages/product/index?id=" + (this.data.product?.id || "gift") }; },
});
