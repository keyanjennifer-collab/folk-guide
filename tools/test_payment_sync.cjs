const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../miniprogram/services/commerce.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const pending = { id: 1, status: 'pending', paid_at: null };
const paid = { id: 1, status: 'paid', paid_at: '2026-10-30T15:49:39' };
const params = { mock: false, timeStamp: '123', nonceStr: 'nonce', package: 'prepay_id=test', signType: 'RSA', paySign: 'signed' };

function setup(syncResults, payment = params) {
  const calls = [];
  const exports = {};
  const responses = [...syncResults];
  vm.runInNewContext(compiled, {
    exports, require: () => ({ request: async options => {
      calls.push(options.path);
      if (options.path.endsWith('/sync-payment')) {
        assert.equal(options.method, 'POST');
        assert.equal(options.showError, false);
        const result = responses.shift();
        if (result instanceof Error) throw result;
        return result;
      }
      if (options.path.endsWith('/pay')) return payment;
      if (options.path.endsWith('/mock-pay')) return paid;
      assert.fail('unexpected request: ' + options.path);
    } }),
    wx: { requestPayment: options => { calls.push('requestPayment'); options.success({}); } },
  });
  return { ...exports, calls };
}

test('付款后主动请求服务端核实，不能仅凭客户端回调开通', async () => {
  const service = setup([pending, paid]);
  assert.equal((await service.payOrder(1)).status, 'paid');
  assert.deepEqual(service.calls, ['/api/orders/1/sync-payment', '/api/orders/1/pay', 'requestPayment', '/api/orders/1/sync-payment']);
});

test('已经扣款并核实成功时，继续支付按钮不会再次调起付款', async () => {
  const service = setup([paid]);
  assert.equal((await service.payOrder(1)).status, 'paid');
  assert.deepEqual(service.calls, ['/api/orders/1/sync-payment']);
});

test('支付成功但查单网络失败，返回核实中状态，不能提示重新付款', async () => {
  const service = setup([pending, new Error('gateway timeout')]);
  assert.equal(await service.payOrder(1), null);
  assert.equal(service.calls.filter(x => x === 'requestPayment').length, 1);
});

test('微信尚未确认成功时不伪造付款状态', async () => {
  const service = setup([pending, pending]);
  const result = await service.payOrder(1);
  assert.equal(result.status, 'pending');
  assert.equal(result.paid_at, null);
});

test('上次付款查询失败时阻止再次付款', async () => {
  const service = setup([new Error('签名校验失败')]);
  await assert.rejects(service.payOrder(1), /签名校验失败/);
  assert.deepEqual(service.calls, ['/api/orders/1/sync-payment']);
});

test('已取消订单不能调起支付', async () => {
  const service = setup([{ ...pending, status: 'cancelled' }]);
  await assert.rejects(service.payOrder(1), /当前订单不能支付/);
  assert.equal(service.calls.filter(x => x === 'requestPayment').length, 0);
});

test('已退款订单不能因为保留了付款时间而被当作新付款成功', async () => {
  const service = setup([{ ...paid, status: 'refunded' }]);
  await assert.rejects(service.payOrder(1), /当前订单不能支付/);
  assert.equal(service.calls.filter(x => x === 'requestPayment').length, 0);
});
