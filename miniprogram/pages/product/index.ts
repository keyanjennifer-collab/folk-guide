import { getTheme, AppTheme } from "../../services/theme";
import { PRODUCTS, Product } from "../../data/products";
import { changeCart } from "../../services/cart";
import { getCatalog, CatalogItem } from "../../services/commerce";
import { API_BASE_URL } from "../../config";

// 后台保存的图片是相对文件名，这里统一拼上商品图静态前缀得到完整 URL。
function assetUrl(filename: string): string {
  if (!filename) return "";
  if (filename.startsWith("http")) return filename;
  return `${API_BASE_URL}/product-assets/${filename}`;
}

Page({
  data: { themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    product: null as Product | null,
    quantity: 1,
    images: [] as string[],
    added: false,
    saleEnabled: false,
    saleMode: "ready" as "ready" | "preorder",
    available: 0,
    shippingEta: "付款后48小时内发货",
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
  // 从后端动态拉取商品完整信息（名称、价格、文案、图片），覆盖本地兜底数据。
  // 这样后台修改内容后，小程序无需重新提审即可生效。
  async syncCatalog(product: Product) {
    try {
      const catalog = await getCatalog();
      const live = catalog.items.find(item => item.id === product.id);
      if (!live) return;
      const merged = this.mergeLiveProduct(product, live);
      this.setData({
        product: merged, images: merged.gallery,
        saleEnabled: catalog.sale_enabled && live.active, saleMode: catalog.sale_mode,
        available: live.available, shippingEta: catalog.shipping_eta,
      });
      wx.setNavigationBarTitle({ title: merged.name });
    } catch (_) { this.setData({ saleEnabled: false, available: 0 }); }
  },
  // 把后端返回的动态字段合并进本地 Product，缺失字段回退到本地兜底。
  mergeLiveProduct(fallback: Product, live: CatalogItem): Product {
    const gallery = (live.gallery && live.gallery.length ? live.gallery : fallback.gallery).map(assetUrl);
    const image = live.image ? assetUrl(live.image) : fallback.image;
    const emblem = live.emblem ? assetUrl(live.emblem) : fallback.emblem;
    return {
      ...fallback,
      name: live.name || fallback.name,
      color: live.color || fallback.color,
      element: live.element || fallback.element,
      beast: live.beast || fallback.beast,
      mood: live.mood || fallback.mood,
      scent: live.scent || fallback.scent,
      story: live.story || fallback.story,
      meaning: live.meaning || fallback.meaning,
      price: live.price_fen / 100,
      lengthCm: live.length_cm || fallback.lengthCm,
      weightGrams: live.weight_grams || fallback.weightGrams,
      image, emblem, gallery,
      swatches: live.swatches && live.swatches.length ? live.swatches : fallback.swatches,
    };
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

