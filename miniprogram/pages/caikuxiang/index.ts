type Product = {
  id: string; name: string; element: string; tone: string; price: number;
  spec: string; scent: string; ingredients: string; badge?: string;
};

const PRODUCTS: Product[] = [
  { id: "black", name: "黑金", element: "水", tone: "black", price: 59, spec: "30支／管", scent: "凉香绵长，木韵厚重内敛，带沉稳木质奶香。", ingredients: "绿棋、檀香、降香、金箔、天然粘粉" },
  { id: "gold", name: "黄金", element: "土", tone: "gold", price: 59, spec: "30支／管", scent: "温润奶香木质调，扎实柔和，清甜干净。", ingredients: "西澳老檀香、金箔粉、天然粘粉" },
  { id: "green", name: "绿金", element: "木", tone: "green", price: 59, spec: "30支／管", scent: "草本清香与木质甜香交织，层次清爽。", ingredients: "沉香、檀香、灵香、排草、金箔粉、天然粘粉" },
  { id: "red", name: "红金", element: "火", tone: "red", price: 59, spec: "30支／管", scent: "蜜香与脂润甜感明显，绵密醇厚。", ingredients: "檀香、沉香、降真香、琥珀、金箔粉、天然粘粉" },
  { id: "white", name: "白金", element: "金", tone: "white", price: 59, spec: "30支／管", scent: "柔和木质、乳香脂感与桂花清甜，清雅柔和。", ingredients: "沉香、檀香、乳香、五色豆、桂花、金箔粉、天然粘粉" },
];

Page({
  data: {
    products: PRODUCTS,
    cartCount: 0,
    cartTotal: 0,
    selectedProduct: null as Product | null,
    showCart: false,
    cartItems: [] as Array<Product & { quantity: number }>,
  },
  showProduct(event: WechatMiniprogram.TouchEvent) {
    const id = String(event.currentTarget.dataset.id);
    this.setData({ selectedProduct: PRODUCTS.find((item) => item.id === id) || null });
  },
  closeProduct() { this.setData({ selectedProduct: null }); },
  addFlagship() {
    const flagship: Product = { id: "flagship", name: "五色旗舰套装", element: "五行五色", tone: "flagship", price: 199, spec: "五色各30支，共150支", scent: "五色齐备，可按每日五色建议灵活选择。", ingredients: "黑金、黄金、绿金、红金、白金各一管" };
    this.addItem(flagship);
  },
  addSelected() { if (this.data.selectedProduct) this.addItem(this.data.selectedProduct); },
  addProduct(event: WechatMiniprogram.TouchEvent) {
    const id = String(event.currentTarget.dataset.id);
    const product = PRODUCTS.find((item) => item.id === id);
    if (product) this.addItem(product);
  },
  addItem(product: Product) {
    const items = [...this.data.cartItems];
    const existing = items.find((item) => item.id === product.id);
    if (existing) existing.quantity += 1;
    else items.push({ ...product, quantity: 1 });
    const cartCount = items.reduce((total, item) => total + item.quantity, 0);
    const cartTotal = items.reduce((total, item) => total + item.price * item.quantity, 0);
    this.setData({ cartItems: items, cartCount, cartTotal, selectedProduct: null });
    wx.showToast({ title: "已加入购物车", icon: "success" });
  },
  openCart() { this.setData({ showCart: true }); },
  closeCart() { this.setData({ showCart: false }); },
  changeQuantity(event: WechatMiniprogram.TouchEvent) {
    const id = String(event.currentTarget.dataset.id);
    const delta = Number(event.currentTarget.dataset.delta);
    const items = this.data.cartItems.map((item) => item.id === id ? { ...item, quantity: item.quantity + delta } : item).filter((item) => item.quantity > 0);
    this.setData({
      cartItems: items,
      cartCount: items.reduce((total, item) => total + item.quantity, 0),
      cartTotal: items.reduce((total, item) => total + item.price * item.quantity, 0),
    });
  },
  checkout() {
    if (!this.data.cartItems.length) return;
    wx.showModal({
      title: "登录后结算",
      content: "商品浏览无需登录。提交订单、支付和查看物流时需要微信登录；当前为前端演示，暂未接入真实支付。",
      confirmText: "微信登录", cancelText: "继续逛逛",
      success: (result) => { if (result.confirm) wx.navigateTo({ url: "/pages/profile/index" }); },
    });
  },
  buyFlagship() { this.addFlagship(); this.setData({ showCart: true }); },
  noop() {},
});
