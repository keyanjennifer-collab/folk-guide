const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const compile = file => ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function service(request = async () => ({})) {
  const exports = {};
  vm.runInNewContext(compile('miniprogram/services/logistics.ts'), { exports, require: () => ({ request }) });
  return exports;
}

function pageSetup(fetchLogistics, token = 'buyer-token') {
  let page;
  const services = {
    getToken: () => token, getApiErrorMessage: () => '物流读取失败', isApiError: (error, status) => error.statusCode === status,
    prepareAfterSalesContact: async () => {}, contactAfterSales: () => {},
    getTheme: () => 'night', getOrderLogistics: fetchLogistics,
    logisticsTimeLabel: service().logisticsTimeLabel,
    ORDER_LABELS: { paid: '待发货', shipped: '待收货', completed: '已完成' },
  };
  vm.runInNewContext(compile('miniprogram/pages/orders/logistics.ts'), {
    exports: {}, require: () => services, wx: {},
    Page: options => { page = options; },
  });
  page.setData = data => Object.assign(page.data, data);
  return page;
}

const shipment = number => ({
  order_id: 7, order_number: 'WS7', order_status: 'shipped', carrier: '顺丰速运', tracking_number: number,
  shipment_recorded: true, tracking_status: 'not_connected', tracking_message: '运输轨迹暂不可用',
  tracking_updated_at: null, tracking_events: [],
  order_events: [{ time: '2026-10-12T18:00:00Z', title: '商家已登记发货', description: '' }],
});

test('物流日期固定北京时间，支持带时区和旧无时区时间', () => {
  const { logisticsTimeLabel: label } = service();
  assert.equal(label('2026-10-12T18:00:00Z'), '2026-10-13 02:00');
  assert.equal(label('2026-10-13T02:00:00+08:00'), '2026-10-13 02:00');
  assert.equal(label('2026-10-12T18:00:00'), '2026-10-13 02:00');
  assert.equal(label('invalid'), '');
});

test('查询本人订单接口，不启用匿名请求', async () => {
  await service(async options => {
    assert.equal(options.path, '/api/orders/7/logistics');
    assert.notEqual(options.auth, false);
    assert.equal(options.retryOnUnauthorized, false);
  }).getOrderLogistics(7);
});

test('物流页展示运单但不会凭发货记录生成运输轨迹', async () => {
  const page = pageSetup(async id => { assert.equal(id, 7); return shipment('SF123'); });
  page.onLoad({ id: '7' });
  await page.loadLogistics();
  assert.equal(page.data.logistics.tracking_number, 'SF123');
  assert.equal(page.data.orderEvents[0].timeLabel, '2026-10-13 02:00');
  assert.equal(page.data.trackingEvents.length, 0);
  assert.equal(page.data.loading, false);
});

test('未登录或订单编号无效时不查询', async () => {
  const noFetch = async () => assert.fail('不应请求订单');
  const loggedOut = pageSetup(noFetch, '');
  loggedOut.onLoad({ id: '7' });
  await loggedOut.loadLogistics();
  assert.equal(loggedOut.data.loggedIn, false);
  const invalid = pageSetup(noFetch);
  invalid.onLoad({ id: '-2' });
  await invalid.loadLogistics();
  assert.match(invalid.data.error, /订单信息无效/);
});

test('离开页面后丢弃延迟响应，不重新显示订单数据', async () => {
  let resolve;
  const page = pageSetup(() => new Promise(done => { resolve = done; }));
  page.onLoad({ id: '7' });
  const loading = page.loadLogistics();
  page.onHide();
  resolve(shipment('SF123'));
  await loading;
  assert.equal(page.data.logistics, null);
  assert.equal(page.data.orderEvents.length, 0);
});

test('刷新后到达的旧响应不覆盖新运单', async () => {
  const resolvers = [];
  const page = pageSetup(() => new Promise(done => resolvers.push(done)));
  page.onLoad({ id: '7' });
  const first = page.loadLogistics();
  const second = page.loadLogistics();
  resolvers[1](shipment('NEW-NUMBER'));
  await second;
  resolvers[0](shipment('OLD-NUMBER'));
  await first;
  assert.equal(page.data.logistics.tracking_number, 'NEW-NUMBER');
});
