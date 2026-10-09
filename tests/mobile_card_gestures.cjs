// Unit-test the actual template gesture handlers without browser or database writes.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
const handlers = {};
const box = {replaceChildren() {}, append() {}, scrollTop: 0, addEventListener(name, fn) {handlers[name] = fn;}};
const label = {};
const context = {
  CardView: {slides: [{text: '摘要'}, {text: '图', number: 1, images: []}], slide: 0},
  document: {getElementById(id) {return id === 'cardSummary' ? box : label;}, createElement() {return {};}}
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function renderCardSlide()'), source.indexOf('function initCardView()')), context);
function swipe(x, y, cancel = false) {
  handlers.touchstart({touches: [{clientX: 200, clientY: 100}]});
  handlers.touchmove({touches: [{clientX: 200 + x, clientY: 100 + y}]});
  if (cancel) handlers.touchcancel();
  handlers.touchend();
}
swipe(-100, 5); assert.equal(context.CardView.slide, 1);
swipe(100, 5); assert.equal(context.CardView.slide, 0);
swipe(-20, 100); assert.equal(context.CardView.slide, 0);
swipe(-100, 5, true); assert.equal(context.CardView.slide, 0);
context.CardView.slides = [{text: '暂无图片'}];
swipe(-100, 5); assert.equal(context.CardView.slide, 0);
console.log('Gesture tests passed: left/right content switching, vertical scroll, cancellation, no figures.');
