const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const origin = 'https://api.wusezhishi.com';
const storedPath = '/avatar-assets/1-' + 'a'.repeat(32) + '.png';
const oldPath = '/avatar-assets/1-' + 'b'.repeat(32) + '.png';
const user = { id: 1, nickname: '已保存的昵称', avatar_url: oldPath, phone_bound: false, wechat_phone_available: false, phone_number: null };
const compile = file => ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
class ApiError extends Error { constructor(message, statusCode = 0) { super(message); this.statusCode = statusCode; } }

function account({ fileContent = 'base64-image', readError = false, afterRead = () => {}, serverAvatar = storedPath } = {}) {
  const exports = {}, calls = [];
  let token = 'token';
  const services = { ApiError, clearLogin: () => { token = ''; }, ensureLogin: async () => token,
    getToken: () => token, request: async options => { calls.push(options); return { ...user, avatar_url: serverAvatar }; } };
  vm.runInNewContext(compile('miniprogram/services/account.ts'), {
    exports, require: name => name === '../config' ? { API_BASE_URL: origin } : services,
    wx: { getFileSystemManager: () => ({ readFile: options => {
      calls.push(['read', options.filePath, options.encoding]);
      if (readError) options.fail({});
      else { afterRead(() => { token = 'different-account-token'; }); options.success({ data: fileContent }); }
    } }) },
  });
  return { ...exports, calls };
}

test('保存头像上传实际文件内容，不把微信临时地址写进数据库', async () => {
  const service = account();
  await service.updateUserProfile('昵称', 'wxfile://tmp/new.png');
  assert.deepEqual(service.calls[0], ['read', 'wxfile://tmp/new.png', 'base64']);
  const options = service.calls[1];
  assert.equal(options.path, '/api/users/me/profile');
  assert.equal(options.data.avatar_base64, 'base64-image');
  assert.equal(options.data.avatar_url, undefined);
  assert.equal(options.retryOnUnauthorized, false);
});

test('只改昵称时保留服务器头像，不重新读取或上传图片', async () => {
  const service = account();
  await service.updateUserProfile('新昵称', origin + storedPath);
  assert.equal(service.calls.length, 1);
  assert.equal(service.calls[0].data.avatar_url, storedPath);
  assert.equal(service.calls[0].data.avatar_base64, undefined);
});

test('登录从服务端恢复头像昵称，旧临时地址不会当作可持久使用的图片', () => {
  const service = account();
  assert.equal(service.userProfilePresentation(user).avatarUrl, origin + oldPath);
  assert.equal(service.userProfilePresentation(user).nickname, user.nickname);
  for (const url of ['wxfile://tmp/a.png', 'http://tmp/a.png', 'https://tmp/a.png']) {
    assert.equal(service.userProfilePresentation({ ...user, avatar_url: url }).avatarUrl, service.DEFAULT_AVATAR_URL);
  }
  assert.equal(service.userProfilePresentation({ ...user, nickname: null, avatar_url: null }).nickname, service.DEFAULT_NICKNAME);
});

test('临时文件失效或超大时明确失败，不提交虚假的保存请求', async () => {
  const missing = account({ readError: true });
  await assert.rejects(missing.updateUserProfile('昵称', 'wxfile://tmp/gone.png'), /重新选择头像/);
  assert.equal(missing.calls.filter(x => x.path).length, 0);
  const huge = account({ fileContent: 'x'.repeat(3 * 1024 * 1024) });
  await assert.rejects(huge.updateUserProfile('昵称', 'wxfile://tmp/huge.png'), /2MB/);
  assert.equal(huge.calls.filter(x => x.path).length, 0);
});

test('读取图片期间切换登录账号，不把旧账号照片保存给新账号', async () => {
  const service = account({ afterRead: changeToken => changeToken() });
  await assert.rejects(service.updateUserProfile('昵称', 'wxfile://tmp/a.png'), /登录状态已变化/);
  assert.equal(service.calls.filter(x => x.path).length, 0);
});

test('旧后台忽略图片内容时不能误提示头像保存成功', async () => {
  const service = account({ serverAvatar: null });
  await assert.rejects(service.updateUserProfile('昵称', 'wxfile://tmp/new.png'), /更新后台后重试/);
});

function page() {
  let result, current = user, readUser = async () => current;
  let token = 'token', saveUser = async () => ({ ...current, nickname: '新昵称', avatar_url: storedPath });
  const calls = [];
  const presentation = account();
  const services = {
    DEFAULT_NICKNAME: presentation.DEFAULT_NICKNAME, DEFAULT_AVATAR_URL: presentation.DEFAULT_AVATAR_URL,
    userProfilePresentation: presentation.userProfilePresentation, getTheme: () => 'night', getToken: () => token,
    getCurrentUser: () => readUser(), getCurrentProfile: async () => ({ completeness: 100 }),
    getAIQuota: async () => ({}), entitlementPresentation: () => ({ title: '权益', description: '说明' }),
    getOrders: async () => ({ counts: { pending: 0, paid: 0, shipped: 0 } }), prepareAfterSalesContact: async () => {},
    updateUserProfile: (...args) => { calls.push(['save', ...args]); return saveUser(...args); },
    getApiErrorMessage: error => error.message || '失败', isApiError: (e, status) => e.statusCode === status,
    logoutLocalAccount: () => { token = ''; }, loginWithWechat: async () => { token = 'token'; },
  };
  vm.runInNewContext(compile('miniprogram/pages/settings/index.ts'), {
    exports: {}, require: () => services,
    wx: { getStorageSync: () => false, setStorageSync: () => {}, showToast: options => calls.push(['toast', options]),
      showModal: options => options.success({ confirm: true }) },
    Page: options => { result = options; },
  });
  result.setData = values => Object.assign(result.data, values);
  return { page: result, calls, setUser: value => { current = value; }, setRead: fn => { readUser = fn; }, setSave: fn => { saveUser = fn; } };
}

test('退出重登恢复服务器已保存的资料，切换账号不串用上一人的头像', async () => {
  const s = page(), p = s.page;
  await p.loadAccount();
  assert.equal(p.data.nickname, user.nickname);
  assert.equal(p.data.avatarUrl, origin + oldPath);
  p.logout();
  assert.equal(p.data.avatarUrl, account().DEFAULT_AVATAR_URL);
  await p.realLogin();
  assert.equal(p.data.avatarUrl, origin + oldPath);
  s.setUser({ ...user, id: 2, nickname: null, avatar_url: null });
  await p.loadAccount();
  assert.equal(p.data.avatarUrl, account().DEFAULT_AVATAR_URL);
  assert.equal(p.data.nickname, account().DEFAULT_NICKNAME);
});

test('选头像返回页面触发账号刷新时，不覆盖未保存的头像和昵称', async () => {
  const s = page(), p = s.page;
  await p.loadAccount();
  p.toggleProfileEdit();
  p.chooseAvatar({ detail: { avatarUrl: 'wxfile://tmp/new.png' } });
  p.editNickname({ detail: { value: '尚未保存的昵称' } });
  await p.loadAccount();
  assert.equal(p.data.avatarUrl, 'wxfile://tmp/new.png');
  assert.equal(p.data.nickname, '尚未保存的昵称');
});

test('服务器确认保存后才提示成功并换成持久头像，防止重复提交', async () => {
  const s = page(), p = s.page;
  await p.loadAccount();
  p.toggleProfileEdit();
  p.chooseAvatar({ detail: { avatarUrl: 'wxfile://tmp/new.png' } });
  let finish;
  s.setSave(() => new Promise(resolve => { finish = resolve; }));
  const saving = p.saveProfile();
  await p.saveProfile();
  assert.equal(p.data.profileSaving, true);
  assert.equal(s.calls.filter(x => x[0] === 'save').length, 1);
  assert.equal(s.calls.filter(x => x[0] === 'toast').length, 0);
  finish({ ...user, nickname: '新昵称', avatar_url: storedPath });
  await saving;
  assert.equal(p.data.avatarUrl, origin + storedPath);
  assert.equal(p.data.profileSaving, false);
  assert.equal(p.data.editingProfile, false);
  assert.equal(s.calls.find(x => x[0] === 'toast')[1].title, '资料已保存');
});

test('保存失败保留编辑内容并展示错误，不声称已保存到本机', async () => {
  const s = page(), p = s.page;
  await p.loadAccount();
  p.toggleProfileEdit();
  p.chooseAvatar({ detail: { avatarUrl: 'wxfile://tmp/new.png' } });
  s.setSave(async () => { throw new Error('网络断开，未保存'); });
  await p.saveProfile();
  assert.equal(p.data.editingProfile, true);
  assert.equal(p.data.profileSaving, false);
  assert.equal(p.data.avatarUrl, 'wxfile://tmp/new.png');
  assert.match(p.data.profileError, /未保存/);
  assert.doesNotMatch(s.calls.find(x => x[0] === 'toast')[1].title, /已保存/);
});

test('保存之前发起的旧读取不能把新头像覆盖回去', async () => {
  const s = page(), p = s.page;
  await p.loadAccount();
  p.toggleProfileEdit();
  p.chooseAvatar({ detail: { avatarUrl: 'wxfile://tmp/new.png' } });
  let staleResponse;
  s.setRead(() => new Promise(resolve => { staleResponse = resolve; }));
  const loading = p.loadAccount();
  await p.saveProfile();
  assert.equal(p.data.avatarUrl, origin + storedPath);
  staleResponse(user);
  await loading;
  assert.equal(p.data.avatarUrl, origin + storedPath);
});

test('保存过程中重新进入页面发起的迟到读取也不能覆盖新头像', async () => {
  const s = page(), p = s.page;
  await p.loadAccount();
  p.toggleProfileEdit();
  p.chooseAvatar({ detail: { avatarUrl: 'wxfile://tmp/new.png' } });
  let finish, staleResponse;
  s.setSave(() => new Promise(resolve => { finish = resolve; }));
  const saving = p.saveProfile();
  s.setRead(() => new Promise(resolve => { staleResponse = resolve; }));
  const loading = p.loadAccount();
  finish({ ...user, nickname: '新昵称', avatar_url: storedPath });
  await saving;
  staleResponse(user);
  await loading;
  assert.equal(p.data.avatarUrl, origin + storedPath);
  assert.equal(p.data.dashboardLoading, false);
});
