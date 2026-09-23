import { request } from "./api";
import { Order } from "./orders";

export interface CatalogItem {
  id: string; name: string;
  // 服务端金额单位是分，页面展示前必须除以 100。
  price_fen: number; category: "set" | "single";
  length_cm: number; weight_grams: number;
  available: number; active: boolean;
}
export interface Catalog {
  sale_enabled: boolean; sale_mode: "ready" | "preorder"; shipping_fee_fen: number; free_shipping_threshold_fen: number;
  merchant_name: string; customer_service: string; shipping_eta: string;
  items: CatalogItem[];
}
export interface ShippingAddressInput {
  recipient_name: string; phone: string; province: string; city: string; district: string;
  detail: string; postal_code?: string | null; is_default: boolean;
}
export interface ShippingAddress extends ShippingAddressInput { id: number; }
export interface PaymentParams {
  mock: boolean; order_id: number; timeStamp?: string; nonceStr?: string;
  package?: string; signType?: "RSA"; paySign?: string;
}

export function getCatalog(): Promise<Catalog> {
  return request<Catalog>({ path: "/api/catalog", auth: false, showError: false });
}
export function getAddresses(): Promise<ShippingAddress[]> {
  return request<ShippingAddress[]>({ path: "/api/addresses", showError: false });
}
export function createAddress(data: ShippingAddressInput): Promise<ShippingAddress> {
  return request<ShippingAddress>({ path: "/api/addresses", method: "POST", data });
}
export function updateAddress(id: number, data: ShippingAddressInput): Promise<ShippingAddress> {
  return request<ShippingAddress>({ path: `/api/addresses/${id}`, method: "PUT", data });
}
export function deleteAddress(id: number): Promise<void> {
  return request<void>({ path: `/api/addresses/${id}`, method: "DELETE" });
}
export function createOrder(data: {
  items: { product_id: string; quantity: number }[]; address_id: number;
  idempotency_key: string; remark?: string;
}): Promise<Order> {
  // 前端只提交商品 ID 和数量；最终单价、运费与总额全部由后端计算。
  return request<Order>({ path: "/api/orders", method: "POST", data });
}
export async function payOrder(orderId: number): Promise<Order | null> {
  // mock 分支仅用于本机自动化测试，生产环境由后端启动校验强制禁用。
  const payment = await request<PaymentParams>({ path: `/api/orders/${orderId}/pay`, method: "POST" });
  if (payment.mock) {
    return request<Order>({ path: `/api/orders/${orderId}/mock-pay`, method: "POST" });
  }
  if (!payment.timeStamp || !payment.nonceStr || !payment.package || !payment.signType || !payment.paySign) {
    throw new Error("服务器未返回完整支付参数");
  }
  // wx.requestPayment 成功只代表客户端流程结束，订单最终状态仍由服务端通知更新。
  await new Promise<void>((resolve, reject) => wx.requestPayment({
    timeStamp: payment.timeStamp!, nonceStr: payment.nonceStr!, package: payment.package!,
    signType: payment.signType!, paySign: payment.paySign!, success: () => resolve(), fail: reject,
  }));
  return null;
}
export function cancelOrder(orderId: number): Promise<Order> {
  return request<Order>({ path: `/api/orders/${orderId}/cancel`, method: "POST" });
}
export function refundOrder(orderId: number, reason = "用户申请整单退款"): Promise<Order> {
  return request<Order>({ path: `/api/orders/${orderId}/refund`, method: "POST", data: { reason } });
}
export function completeOrder(orderId: number): Promise<Order> {
  return request<Order>({ path: `/api/orders/${orderId}/complete`, method: "POST" });
}
