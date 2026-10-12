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

function setup(response, supported = true) {
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
      canIUse: () => supported,
      openCustomerServiceChat: data => calls.push(['chat', data]),
      showModal: data => calls.push(['modal', data]),
      showToast: data => calls.push(['toast', data]),
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
