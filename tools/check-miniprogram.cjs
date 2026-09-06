const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');
const root = path.join(__dirname, '../miniprogram');
const cache = new Map(), storage = new Map();
let page, token = '', publicResult, requests = 0;
const wx = {
  getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, value),
  showToast() {}, showModal() {}, nextTick: fn => fn(), pageScrollTo() {},
};
function load(relative) {
  const file = path.resolve(root, relative);
  if (cache.has(file)) return cache.get(file);
  const source = fs.readFileSync(file, 'utf8');
  const output = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText;
  const module = {exports:{}};
  const localRequire = name => {
    if (name.endsWith('/services/api') || (relative.endsWith('/orders.ts') && name === './api')) return {
      getToken: () => token, getApiErrorMessage: (_, fallback) => fallback, isApiError: () => false,
      request: async () => { requests++; if (publicResult instanceof Error) throw publicResult; return publicResult; },
    };
    return load(path.relative(root, path.resolve(path.dirname(file), name + '.ts')));
  };
  vm.runInNewContext(output, {exports:module.exports, module, require:localRequire, wx, setTimeout, clearTimeout, Page: config => {page=config;}}, {filename:file});
  cache.set(file, module.exports);
  return module.exports;
}
function instance(file) {
  cache.delete(path.join(root, file));
  load(file);
  const target = {...page, data:structuredClone(page.data), setData(values) {Object.assign(this.data, values);}};
  return target;
}
async function main() {
  const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'));
  assert.equal(app.tabBar.list.length, 4);
  assert.equal(app.tabBar.custom, true);
  assert.equal(app.window.navigationBarTextStyle, 'white');
  assert.equal(app.tabBar.backgroundColor.toLowerCase(), '#0d0e0d');
  for (const ext of ['ts','json','wxml','wxss']) assert(fs.existsSync(path.join(root,'custom-tab-bar/index.'+ext)));
  for (const item of app.tabBar.list) {
    assert(app.pages.includes(item.pagePath));
    for (const icon of [item.iconPath,item.selectedIconPath]) assert(fs.existsSync(path.join(root, icon)));
  }
  for (const route of app.pages) for (const ext of ['ts','wxml','wxss','json']) assert(fs.existsSync(path.join(root, route+'.'+ext)), route+'.'+ext);
  const {PRODUCTS} = load('data/products.ts');
  assert.equal(PRODUCTS.length,6);
  assert.equal(new Set(PRODUCTS.map(p=>p.id)).size,6);
  for (const p of PRODUCTS) for (const image of [p.image,p.emblem]) assert(fs.existsSync(path.join(root,image)));
  const cart = load('services/cart.ts');
  assert.equal(cart.readCart().length,0);
  cart.changeCart('green',2);
  assert.equal(cart.readCart()[0].subtotal,118);
  cart.changeCart('green',200);
  assert.equal(cart.readCart()[0].quantity,99);
  cart.changeCart('green',-200);
  assert.equal(cart.readCart().length,0);
  cart.changeCart('unknown',1);
  assert.equal(cart.readCart().length,0);
  storage.set('wuse-shopping-bag-v1',[{id:'green',quantity:'bad'},{id:'red',quantity:-3}]);
  assert.equal(cart.readCart().length,0);
  publicResult={guide_date:'2026-09-06',solar_term:'处暑',lunar_date:'七月廿五',weekday:'星期日',day_ganzhi:'癸未',
    items:['土','水','金','木','火'].map((element,i)=>({element,rank:i+1,color:'旧名称',smoothness:'比较合适',suitable:['整理'],resistance:'留意节奏',advice:'适量配色'}))};
  const home=instance('pages/home/index.ts');
  await home.loadToday();
  assert.equal(home.data.guides.length,5);
  assert.equal(home.data.scent.name,'黄檀香');
  home.selectGuide({currentTarget:{dataset:{rank:4}}});
  assert.equal(home.data.scent.name,'青木香');
  home.selectScent({currentTarget:{dataset:{id:'black'}}});
  assert.equal(home.data.scent.name,'墨沉香');
  publicResult=new Error('network');
  await home.loadToday();
  assert.equal(home.data.contentSource,'error');
  assert.equal(home.data.guides.length,0);
  assert.equal(home.data.selected,null);
  const orders=instance('pages/orders/index.ts'), before=requests;
  await orders.loadOrders();
  assert.equal(requests,before,'guest must not fetch personal orders');
  assert.equal(orders.data.loggedIn,false);
  console.log('PASS: 4 routes; 6 SKUs/assets; cart persistence, bounds and invalid data; daily color mapping/switch/error reset; guest order guard');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
