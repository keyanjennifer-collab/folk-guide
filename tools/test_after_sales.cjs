// 无需下载依赖：验证小程序客服入口和后台脚本的关键交互。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'miniprogram/services/after-sales.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

function setup(response, supported = true, platform = 'ios') {
  const calls = [];
  const exports = {};
  const context = {
    exports,
    require: () => ({ request: async options => {
      assert.equal(options.auth, false);
      assert.equal(options.path, '/api/after-sales/contact');
      return response;
    } }),
    wx: {
      getDeviceInfo: () => ({ platform }),
      canIUse: () => supported,
      openCustomerServiceChat: data => calls.push(['chat', data]),
      showModal: data => calls.push(['modal', data]),
      showToast: data => calls.push(['toast', data]),
      setClipboardData: data => calls.push(['copy', data]),
    },
  };
  vm.runInNewContext(compiled, context);
  return { api: exports, calls };
}

test('未配置客服时提示，不调用空地址', async () => {
  const { api, calls } = setup({ available: false, corp_id: '', url: '', fallback_contact: '' });
  await api.prepareAfterSalesContact();
  api.contactAfterSales();
  assert.equal(calls[0][0], 'modal');
  assert.match(calls[0][1].content, /准备中/);
});

test('点击客服携带正确企业信息和可选订单卡片', async () => {
  const { api, calls } = setup({ available: true, corp_id: 'ww-test', url: 'https://work.weixin.qq.com/kfid/test', fallback_contact: '' });
  await api.prepareAfterSalesContact();
  assert.equal(calls.length, 0); // 页面预载不会自行打开或发送消息。
  api.contactAfterSales('WS123');
  assert.equal(calls[0][0], 'chat');
  assert.equal(calls[0][1].corpId, 'ww-test');
  assert.equal(calls[0][1].extInfo.url, 'https://work.weixin.qq.com/kfid/test');
  assert.equal(calls[0][1].showMessageCard, true);
  assert.match(calls[0][1].sendMessageTitle, /WS123/);
  api.contactAfterSales();
  assert.equal(calls[1][1].showMessageCard, false);
});

test('旧版微信提示升级并提供备用客服方式', async () => {
  const { api, calls } = setup({ available: true, corp_id: 'ww-test', url: 'https://work.weixin.qq.com/kfid/test', fallback_contact: '400-000-0000' }, false);
  await api.prepareAfterSalesContact();
  api.contactAfterSales();
  assert.equal(calls[0][0], 'modal');
  assert.match(calls[0][1].content, /400-000-0000/);
});

test('开发者工具直接提示手机预览，不把模拟器失败当作客服配置错误', async () => {
  const { api, calls } = setup({ available: true, corp_id: 'ww-test', url: 'https://work.weixin.qq.com/kfid/test', fallback_contact: '' }, true, 'devtools');
  await api.prepareAfterSalesContact();
  api.contactAfterSales();
  assert.equal(calls[0][0], 'modal');
  assert.match(calls[0][1].content, /预览二维码/);
  assert.equal(calls.filter(x => x[0] === 'chat').length, 0);
});

test('真机客服失败保留微信错误，用户主动确认后可复制诊断信息', async () => {
  const { api, calls } = setup({ available: true, corp_id: 'ww-test', url: 'https://work.weixin.qq.com/kfid/test', fallback_contact: '' });
  await api.prepareAfterSalesContact();
  api.contactAfterSales();
  calls[0][1].fail({ errMsg: 'openCustomerServiceChat:fail corpId invalid', errCode: 123 });
  const modal = calls[1][1];
  assert.match(modal.content, /corpId invalid/);
  assert.equal(modal.confirmText, '复制错误');
  modal.success({ confirm: false });
  assert.equal(calls.filter(x => x[0] === 'copy').length, 0);
  modal.success({ confirm: true });
  assert.match(calls[2][1].data, /错误码：123/);
  assert.match(calls[2][1].data, /企业ID：ww-test/);
});

test('用户取消客服不弹故障提示', async () => {
  const { api, calls } = setup({ available: true, corp_id: 'ww-test', url: 'https://work.weixin.qq.com/kfid/test', fallback_contact: '' });
  await api.prepareAfterSalesContact();
  api.contactAfterSales();
  calls[0][1].fail({ errMsg: 'openCustomerServiceChat:fail cancel' });
  assert.equal(calls.length, 1);
});

test('后台脚本可解析，只有可退款订单显示退款入口', () => {
  const html = fs.readFileSync(path.join(root, 'backend/app/static/admin_orders.html'), 'utf8');
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(x => x[1]);
  for (const script of scripts) new vm.Script(script);
  const renderer = scripts.join('\n').match(/function renderOrder\(x, opts=\{\}\)\{[\s\S]*?\n    \}/)[0];
  const context = { adminProfile: { role: 'superadmin' }, esc: s => String(s), money: n => String(n), fmtTime: s => s, STATUS_TEXT: {} };
  vm.runInNewContext(renderer, context);
  const order = { id: 1, number: 'WS1', status: 'pending', items: [], total_fen: 7800 };
  assert.doesNotMatch(context.renderOrder(order), /onclick="refundOrder/);
  Object.assign(order, { status: 'shipped', paid_at: '2026-10-12', shipped_at: '2026-10-12' });
  assert.match(context.renderOrder(order), /onclick="refundOrder/);
  Object.assign(order, { status: 'refunded', refund_restock: false });
  assert.match(context.renderOrder(order), /onclick="restockReturn/);
  context.adminProfile.role = 'operator';
  assert.doesNotMatch(context.renderOrder(order), /onclick="restockReturn/);
});

test('后台发货使用JSON和CSRF，上传文件保留浏览器生成的表单类型', async () => {
  const html = fs.readFileSync(path.join(root, 'backend/app/static/admin_orders.html'), 'utf8');
  const helper = html.match(/async function api\(path,options=\{\}\)\{[\s\S]*?\n    \}/)[0];
  const calls = [];
  class FormData {}
  const context = { FormData, csrfToken: 'csrf-test', fetch: async (url, options) => {
    calls.push({ url, ...options });
    return { ok: true, status: 200, json: async () => ({ status: 'shipped' }) };
  } };
  vm.runInNewContext(helper, context);
  await context.api('/api/admin/orders/1/ship', { method: 'POST', body: JSON.stringify({ carrier: '中通快递', tracking_number: '73123456789012' }) });
  assert.equal(calls[0].headers['content-type'], 'application/json');
  assert.equal(calls[0].headers['X-CSRF-Token'], 'csrf-test');
  assert.equal(calls[0].credentials, 'same-origin');
  await context.api('/upload', { method: 'POST', body: new FormData() });
  assert.equal(calls[1].headers['content-type'], undefined);
});

test('微信模式先取号打印再确认发货，异常只补查，未取号填写实际包裹数据', () => {
  const html = fs.readFileSync(path.join(root, 'backend/app/static/admin_orders.html'), 'utf8');
  const renderer = html.match(/function renderOrder\(x, opts=\{\}\)\{[\s\S]*?\n    \}/)[0];
  const context = { adminProfile: { role: 'superadmin' }, shippingIntegration: { enabled: true },
    esc: s => String(s), money: n => String(n), fmtTime: s => s, STATUS_TEXT: {} };
  vm.runInNewContext(renderer, context);
  const row = { id: 1, number: 'WS1', status: 'paid', items: [], total_fen: 7800,
    shipping_sync_status: 'ordered', shipping_sync_message: '已取号待发货' };
  const rendered = context.renderOrder(row, { showShip: true });
  assert.match(rendered, /已取号待发货/);
  assert.match(rendered, /打印 \/ 重打面单/);
  assert.match(rendered, /打包后确认发货/);
  row.shipping_sync_status = 'unknown';
  assert.match(context.renderOrder(row, { showShip: true }), /补查运单/);
  assert.doesNotMatch(context.renderOrder(row, { showShip: true }), /生成运单|打包后确认发货/);
  assert.doesNotMatch(rendered, /id="tracking-1"|onclick="ship\(1\)"/);
  row.shipping_sync_status = 'failed';
  assert.match(context.renderOrder(row, { showShip: true }), /重新生成运单/);
  assert.match(context.renderOrder(row, { showShip: true }), /id="weight-1"/);
  context.shippingIntegration.enabled = false;
  assert.match(context.renderOrder(row, { showShip: true }), /id="tracking-1"/);
});
