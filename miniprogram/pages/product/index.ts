import { getTheme, AppTheme } from "../../services/theme";
import { PRODUCTS, Product } from "../../data/products";
import { changeCart } from "../../services/cart";
import { getCatalog } from "../../services/commerce";
Page({
  data: { themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    product: null as Product | null,
    quantity: 1,
    images: [] as string[],
    added: false,
    saleEnabled: false,
    saleMode: "preorder" as "ready" | "preorder",
    available: 0,
    shippingEta: "付款后两个月内发货",
    // 礼盒内容直接来自商品目录，避免在模板中重复维护单品名称。
    setContents: PRODUCTS.filter(item => item.category === "single").map(item => item.name).join("、") + "。五款线香与对应矿石香插，承载一份应时心意。",
  },
  onLoad(options: Record<string, string>) {
    const product = PRODUCTS.find(item => item.id === options.id);
    if (product) {
      this.setData({ product, images: product.gallery });
      wx.setNavigationBarTitle({ title: product.name });
      void this.syncCatalog(product);
    }
  },
  async syncCatalog(product: Product) {
    try {
      const catalog = await getCatalog();
      const live = catalog.items.find(item => item.id === product.id);
      if (!live) return;
      this.setData({ product: { ...product, price: live.price_fen / 100,
        lengthCm: live.length_cm || product.lengthCm, weightGrams: live.weight_grams || product.weightGrams },
        saleEnabled: catalog.sale_enabled && live.active, saleMode: catalog.sale_mode,
        available: live.available, shippingEta: catalog.shipping_eta });
    } catch (_) { this.setData({ saleEnabled: false, available: 0 }); }
  },
  changeQuantity(event: WechatMiniprogram.TouchEvent) {
    this.setData({ quantity: Math.min(99, Math.max(1, this.data.quantity + Number(event.currentTarget.dataset.delta))), added: false });
  },
  addToBag() {
    if (!this.data.product) return;
    if (!this.data.saleEnabled) { wx.showToast({ title: "商城尚未正式开启收款", icon: "none" }); return; }
    if (this.data.available < this.data.quantity) { wx.showToast({ title: "当前库存不足", icon: "none" }); return; }
    try {
      changeCart(this.data.product.id, this.data.quantity);
      this.setData({ added: true });
      wx.showToast({ title: "已加入购物袋", icon: "success" });
    } catch (_) { wx.showToast({ title: "保存失败，请重试", icon: "none" }); }
  },
  toBag() {
    wx.setStorageSync("wuse-open-cart-on-show", true);
    wx.switchTab({ url: "/pages/caikuxiang/index" });
  },
  onShareAppMessage() { return { title: this.data.product?.name || "五色知时", path: "/pages/product/index?id=" + (this.data.product?.id || "gift") }; },
});

