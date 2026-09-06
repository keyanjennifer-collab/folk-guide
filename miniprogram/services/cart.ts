import { PRODUCTS, Product } from "../data/products";
const KEY = "wuse-shopping-bag-v1";
export type CartItem = Product & { quantity: number; subtotal: number };
/** 这里只存本机选香清单，不把购物袋伪装成已提交订单。 */
export function readCart(): CartItem[] {
  const stored: unknown = wx.getStorageSync(KEY);
  if (!Array.isArray(stored)) return [];
  return PRODUCTS.flatMap(product => {
    const row = stored.find(item => item && item.id === product.id);
    const quantity = Number(row?.quantity);
    return Number.isInteger(quantity) && quantity > 0 && quantity <= 99
      ? [{ ...product, quantity, subtotal: product.price * quantity }] : [];
  });
}
export function changeCart(id: string, delta: number): CartItem[] {
  const product = PRODUCTS.find(item => item.id === id);
  if (!product || !Number.isInteger(delta)) return readCart();
  const items = readCart();
  const row = items.find(item => item.id === id);
  const quantity = Math.max(0, Math.min(99, (row?.quantity || 0) + delta));
  const next = items.filter(item => item.id !== id).map(item => ({ id: item.id, quantity: item.quantity }));
  if (quantity) next.push({ id, quantity });
  wx.setStorageSync(KEY, next);
  return readCart();
}
