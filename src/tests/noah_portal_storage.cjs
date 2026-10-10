const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Storage {
  constructor(values = {}, failWrites = false) {
    Object.assign(this, values);
    Object.defineProperty(this, 'failWrites', {value: failWrites});
  }
  getItem(key) { return Object.hasOwn(this, key) ? this[key] : null; }
  setItem(key, value) {
    if (this.failWrites) throw new Error('storage unavailable');
    this[key] = String(value);
  }
  removeItem(key) { delete this[key]; }
}

const script = fs.readFileSync(process.argv[2], 'utf8');
function run(storage) {
  const element = {classList: {toggle() {}}, textContent: ''};
  const context = {
    localStorage: storage,
    window: {addEventListener() {}},
    document: {getElementById() { return element; }, querySelectorAll() { return []; }},
  };
  vm.runInNewContext(script, context);
  return context;
}

const previous = 'previous_portal_';
const storage = new Storage({
  [previous + 'filtro_v1']: '["startup"]',
  [previous + 'selecionadas_v1']: '["job-1"]',
  [previous + 'migrou_internacional_v1']: '1',
});
const context = run(storage);
assert.equal(storage.getItem('noah_portal_filtro_v1'), '["startup"]');
assert.equal(storage.getItem('noah_portal_selecionadas_v1'), '["job-1"]');
assert.equal(storage.getItem(previous + 'filtro_v1'), null);
context.window.onCheck({checked: true, getAttribute() { return 'job-2'; }});
assert.deepEqual(JSON.parse(storage.getItem('noah_portal_selecionadas_v1')), ['job-1', 'job-2']);
run(storage);
assert.equal(storage.getItem('noah_portal_filtro_v1'), '["startup"]');

const current = new Storage({
  noah_portal_filtro_v1: '["banco"]',
  noah_portal_migrou_internacional_v1: '1',
  [previous + 'filtro_v1']: '["startup"]',
});
run(current);
assert.equal(current.getItem('noah_portal_filtro_v1'), '["banco"]');

const unavailable = new Storage({[previous + 'filtro_v1']: '["startup"]'}, true);
run(unavailable);
assert.equal(unavailable.getItem(previous + 'filtro_v1'), '["startup"]');
console.log('Noah portal storage: passed');
