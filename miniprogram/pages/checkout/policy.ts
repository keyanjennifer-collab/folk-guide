import { getCatalog } from "../../services/commerce";
import { getTheme } from "../../services/theme";
import { contactAfterSales, prepareAfterSalesContact } from "../../services/after-sales";

Page({
  data: { themeClass: "theme-" + getTheme(), merchantName: "五色知时", customerService: "", shippingEta: "付款后48小时内发货", saleMode: "ready" },
  onShow() { void prepareAfterSalesContact(); },
  contactSupport() { contactAfterSales(); },
  async onLoad() {
    try {
      const catalog = await getCatalog();
      this.setData({ merchantName: catalog.merchant_name, customerService: catalog.customer_service, shippingEta: catalog.shipping_eta, saleMode: catalog.sale_mode });
    } catch (_) { /* 保留基础须知，结算接口恢复后会重新读取正式信息。 */ }
  },
});
