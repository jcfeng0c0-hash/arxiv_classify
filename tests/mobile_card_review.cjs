const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
async function test(action, success) {
  const paper = {arxiv_id: '2401.12345', is_read: false};
  const buttons = [{textContent: 'Important'}, {textContent: '不关注'}];
  const navigation = [];
  const alerts = [];
  const context = {
    CardView: {items: [paper], cursor: 0, reviewing: false},
    document: {querySelectorAll: () => buttons, getElementById: id => buttons[id === 'btnCardImportant' ? 0 : 1]},
    fetch: async (url, options) => {
      assert.equal(JSON.parse(options.body).action, action);
      assert.equal(options.method, 'POST');
      assert(buttons.every(b => b.disabled));
      return {ok: success, json: async () => ({success, is_read: true, is_important: action === 'important', error: 'test failure'})};
    },
    showCursor: async i => navigation.push(i),
    alert: s => alerts.push(s), AbortController, setTimeout, clearTimeout
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function reviewCard(action)'), source.indexOf('function cardNext()')), context);
  await context.reviewCard(action);
  assert.equal(context.CardView.reviewing, false);
  assert(buttons.every(b => !b.disabled));
  if (success) {
    assert.equal(paper.is_read, true);
    assert.equal(paper.is_important_author, action === 'important');
    assert.deepEqual(navigation, [1]);
  } else {
    assert.equal(paper.is_read, false);
    assert.equal(navigation.length, 0);
    assert.equal(alerts.length, 1);
  }
}
(async () => {
  await test('dismiss', true);
  await test('important', true);
  await test('dismiss', false);
  console.log('Review tests passed: read/important flags, automatic advance, failure stays, button feedback.');
})().catch(e => {console.error(e); process.exitCode = 1;});
