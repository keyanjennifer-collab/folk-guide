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

function entitlementService({ token = 'token', quota = async () => ({ active: true }) } = {}) {
  const calls = [];
  const exports = {};
  const services = { getToken: () => token, getAIQuota: quota, getApiErrorMessage: () => '网络异常' };
  const wx = {
    showModal: options => calls.push(['modal', options]),
    navigateTo: options => calls.push(['navigate', options]),
    switchTab: options => calls.push(['tab', options]),
    showToast: options => calls.push(['toast', options]),
  };
  vm.runInNewContext(compile('miniprogram/services/entitlements.ts'), { exports, require: () => services, wx });
  return { ...exports, calls };
}

function page(file, overrides = {}) {
  let result;
  const calls = [];
  const services = {
    getTheme: () => 'night', getToken: () => 'token',
    getApiErrorMessage: () => '请求失败', isApiError: (error, status) => error.statusCode === status,
    ensureFeatureAccess: async () => false, showFeatureAccessRequired: () => calls.push('access-required'),
    PRODUCTS: [{ id: 'gift' }], SINGLE_PRODUCTS: [{ id: 'green' }], SCENT_DETAILS: {},
    ...overrides,
  };
  vm.runInNewContext(compile(file), {
    exports: {}, require: () => services,
    wx: { navigateTo: options => calls.push(options.url), showToast: () => {} },
    Page: options => { result = options; },
  });
  result.setData = values => Object.assign(result.data, values);
  return { result, calls };
}

test('七天体验显示剩余天数，永久权益不显示剩余0天', () => {
  const { entitlementPresentation: label } = entitlementService();
  const trial = label({ active: true, plan: 'new_user_7_days', expires_at: new Date(Date.now() + 6 * 86400000).toISOString() });
  assert.equal(trial.title, '新用户7天体验');
  assert.match(trial.description, /剩余6天/);
  const lifetime = label({ active: true, plan: 'gift_lifetime', expires_at: null });
  assert.match(lifetime.title, /永久/);
  assert.doesNotMatch(lifetime.description, /剩余|0天/);
});

test('未登录先进入登录页，不自动查询或购买', async () => {
  const service = entitlementService({ token: '', quota: () => assert.fail('不应查询') });
  assert.equal(await service.ensureFeatureAccess(), false);
  assert.equal(service.calls[0][0], 'tab');
  assert.equal(service.calls[0][1].url, '/pages/settings/index');
});

test('到期提示购买套装，只有用户确认后才导航', async () => {
  const service = entitlementService({ quota: async () => ({ active: false }) });
  assert.equal(await service.ensureFeatureAccess(), false);
  assert.equal(service.calls.length, 1);
  const modal = service.calls[0][1];
  assert.match(modal.content, /268元五色套装/);
  modal.success({ confirm: false });
  assert.equal(service.calls.length, 1);
  modal.success({ confirm: true });
  assert.equal(service.calls[1][1].url, '/pages/product/index?id=gift');
});

test('有效权益允许确定性测算，不要求AI模型就绪', async () => {
  const service = entitlementService({ quota: async () => ({ active: true, answer_ready: false }) });
  assert.equal(await service.ensureFeatureAccess(), true);
  assert.equal(service.calls.length, 0);
});

test('查询失败显示重试提示，不误判为体验到期', async () => {
  const service = entitlementService({ quota: async () => { throw new Error('offline'); } });
  assert.equal(await service.ensureFeatureAccess(), false);
  assert.equal(service.calls[0][0], 'toast');
});

test('测一测入口在权益不足时不跳转，允许时进入正确的合盘页', async () => {
  const denied = page('miniprogram/pages/chat/index.ts');
  await denied.result.toZiwei({ currentTarget: { dataset: { mode: 'compatibility' } } });
  assert.equal(denied.calls.length, 0);
  const allowed = page('miniprogram/pages/chat/index.ts', { ensureFeatureAccess: async () => true });
  await allowed.result.toZiwei({ currentTarget: { dataset: { mode: 'compatibility' } } });
  assert.equal(allowed.calls[0], '/pages/ziwei/index?mode=compatibility');
});

test('直接进入起盘页也先检查权益，清除旧记录', async () => {
  const { result } = page('miniprogram/pages/ziwei/index.ts', {
    getZiweiCharts: () => assert.fail('不应查询'), getZiweiCompatibilities: () => assert.fail('不应查询'),
  });
  result.data.savedCharts = [{ id: 1 }];
  await result.loadRecords();
  assert.equal(result.data.accessAllowed, false);
  assert.equal(result.data.savedCharts.length, 0);
});

test('个人五色到期后清除已有结果，显示购买状态', async () => {
  const { result } = page('miniprogram/pages/home/index.ts', {
    getPersonalDailyGuidance: async () => { throw { statusCode: 403 }; },
  });
  result.data.personalColors = [{ name: '旧结果' }];
  result.data.personalOpen = true;
  await result.loadPersonalColors();
  assert.equal(result.data.personalState, 'expired');
  assert.equal(result.data.personalColors.length, 0);
  assert.equal(result.data.personalOpen, false);
});

test('AI解读返回权益失效时不保留本地单盘分析', async () => {
  const { result, calls } = page('miniprogram/pages/ziwei/result.ts', {
    interpretZiwei: async () => { throw { statusCode: 403 }; },
    ANALYSIS_TABS: [],
  });
  result.data.chartResult = { id: 1 };
  result.data.analysis = { text: '旧分析' };
  await result.loadRemoteAnalysis('overview', 'mingpan', null);
  assert.equal(result.data.chartResult, null);
  assert.equal(result.data.analysis, null);
  assert.equal(calls[0], 'access-required');
});
