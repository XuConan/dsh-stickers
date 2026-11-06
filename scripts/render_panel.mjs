/**
 * 把一个 Client 组件真渲染成 HTML 再截图——不用开 DSH 就能看面板长什么样。
 *
 * 用法：node scripts/render_panel.mjs [输出png]
 * 依赖：本机 127.0.0.1:8799 上跑着后端（缩略图要真的去取）。
 */
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')
const OUT_PNG = process.argv[2] || join(ROOT, 'data', 'render_panel.png')
const OUT_HTML = join(ROOT, 'data', 'render_panel.html')
const PORT = process.env.STICKERS_PORT || '8799'

// ---------- 迷你 React：只要 useState / useRef / useCallback / useEffect ----------
const store = []
let cursor = 0
let dirty = false
const effects = []

function useState(initial) {
  const i = cursor++
  if (!(i in store)) store[i] = typeof initial === 'function' ? initial() : initial
  const set = (v) => {
    const next = typeof v === 'function' ? v(store[i]) : v
    if (next !== store[i]) dirty = true
    store[i] = next
  }
  return [store[i], set]
}
function useRef(initial) {
  const i = cursor++
  if (!(i in store)) store[i] = { current: initial }
  return store[i]
}
function useCallback(fn) {
  cursor++ // 只占位，保证 hook 顺序稳定
  return fn
}
function useEffect(fn) {
  const i = cursor++
  effects.push({ i, fn })
}

const React = {
  createElement: (type, props, ...children) =>
    typeof type === 'function'
      ? type({ ...(props || {}), children })
      : { type, props: props || {}, children: children.flat(Infinity).filter((c) => c != null) },
  useState,
  useRef,
  useCallback,
  useEffect,
  Fragment: 'fragment',
}
React.default = React

// ---------- 加载 client.js ----------
let mod = null
globalThis.window = {
  DSH_STICKERS_PORT: PORT,
  __ModuleLoader__: { load: (m) => (mod = m) },
}
const styleNodes = []
globalThis.document = {
  createElement: (tag) => ({ tagName: tag, textContent: '', dataset: {}, setAttribute() {}, remove() {} }),
  head: { appendChild: (n) => styleNodes.push(n), removeChild() {} },
  body: { appendChild() {}, removeChild() {} },
  querySelector: () => null,
}
const realRequire = (name) => {
  if (name === 'react') return React
  throw new Error('unexpected require: ' + name)
}

const src = readFileSync(join(ROOT, 'client.js'), 'utf8')
new Function('window', 'document', 'require', src)(globalThis.window, globalThis.document, realRequire)

// 从 apply(ctx) 里抓出注册的面板组件
let Page = null
const factory = mod.factory(realRequire)
const ctx = {
  slots: {
    inject: (name, fn) => {
      if (typeof fn !== 'function') return
      const it = fn()
      if (it && typeof it.next === 'function') it.next()
      if (it && typeof it.return === 'function') it.return()
    },
    register: (meta, Comp) => {
      if (meta && meta.name === 'main') Page = Comp
      return () => {}
    },
  },
  effect: (fn) => {
    const d = typeof fn === 'function' ? fn() : null
    return typeof d === 'function' ? d : () => {}
  },
  layout: { selectPanel() {} },
  locale: { t: (k) => k },
}
factory.apply(ctx)
if (!Page) throw new Error('没抓到面板组件')

// ---------- 渲染若干轮，等异步数据回来 ----------
const CSS = (src.match(/const CSS = `([\s\S]*?)`\n/) || [, ''])[1]
const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

function attrs(p) {
  const out = []
  if (p.className) out.push(`class="${esc(p.className)}"`)
  if (p.src) out.push(`src="${esc(p.src)}"`)
  if (p.style && typeof p.style === 'string') out.push(`style="${esc(p.style)}"`)
  if (p.disabled) out.push('disabled')
  if (p.value != null && p.tagName !== 'input') out.push(`value="${esc(p.value)}"`)
  return out.length ? ' ' + out.join(' ') : ''
}

function html(node) {
  if (node == null || node === false) return ''
  if (Array.isArray(node)) return node.map(html).join('')
  if (typeof node !== 'object') return esc(node)
  if (typeof node.type === 'function') return html(node.type(node.props))
  const tag = node.type === 'fragment' ? '' : node.type
  const inner = node.children.map(html).join('')
  if (!tag) return inner
  if (tag === 'img') return `<img${attrs(node.props)}>`
  if (tag === 'input') return `<input${attrs(node.props)} placeholder="${esc(node.props.placeholder || '')}">`
  if (tag === 'select') {
    const opts = node.children.map(html).join('')
    return `<select${attrs(node.props)}>${opts}</select>`
  }
  if (tag === 'option') {
    const v = node.props.value != null ? ` value="${esc(node.props.value)}"` : ''
    const sel = node.props.value === node.props.selected ? ' selected' : ''
    return `<option${v}${sel}>${inner}</option>`
  }
  return `<${tag}${attrs(node.props)}>${inner}</${tag}>`
}

function find(node, pred, out = []) {
  if (node == null || node === false) return out
  if (Array.isArray(node)) {
    node.forEach((n) => find(n, pred, out))
    return out
  }
  if (typeof node !== 'object') return out
  if (pred(node)) out.push(node)
  if (node.children) node.children.forEach((n) => find(n, pred, out))
  return out
}

// 可选的交互：先切到某个页签，再选某个分类（用环境变量驱动，方便验证不同视图）
const WANT_MARKET = process.env.MARKET || ''
const WANT_CATEGORY = process.env.CATEGORY || ''
let interacted = false

let tree = null
for (let round = 0; round < 10; round += 1) {
  cursor = 0
  dirty = false
  effects.length = 0
  tree = Page()
  for (const e of effects) {
    try {
      e.fn()
    } catch (err) {
      console.error('effect failed:', err.message)
    }
  }
  await new Promise((r) => setTimeout(r, 350))
  if (!interacted && WANT_MARKET) {
    const tab = find(tree, (n) => n.props && n.props.onClick && String(n.children.join('')).includes(WANT_MARKET))[0]
    if (tab) {
      tab.props.onClick()
      dirty = true
      interacted = true
    }
  }
  if (interacted && WANT_CATEGORY && WANT_MARKET) {
    const sel = find(tree, (n) => n.type === 'select' && n.children.some((c) => c && c.props && String(c.children.join('')).includes(WANT_CATEGORY)))[0]
    if (sel) {
      const opt = sel.children.find((c) => c && c.props && String(c.children.join('')).includes(WANT_CATEGORY))
      sel.props.onChange({ target: { value: opt.props.value } })
      dirty = true
    } else console.error('找不到分类:', WANT_CATEGORY)
  }
  if (!dirty) break
}

const body = html(tree)
const page = `<!doctype html><meta charset="utf-8">
<style>
html, body { margin: 0; background: #0f1115; font-family: system-ui, "Segoe UI", "Microsoft YaHei", sans-serif; }
${CSS}
</style>
<div style="height:1000px">${body}</div>
`
mkdirSync(dirname(OUT_HTML), { recursive: true })
writeFileSync(OUT_HTML, page, 'utf8')
console.log('html:', OUT_HTML, createHash('sha1').update(page).digest('hex').slice(0, 8))

const { chromium } = await import('playwright')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const pg = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
await pg.goto('file://' + OUT_HTML.replace(/\\/g, '/'))
await pg.waitForTimeout(2500)
mkdirSync(dirname(OUT_PNG), { recursive: true })
await pg.screenshot({ path: OUT_PNG })
const stat = await pg.evaluate(() => ({
  cards: document.querySelectorAll('.dshst-card').length,
  badges: [...document.querySelectorAll('.dshst-badge')].slice(0, 3).map((e) => e.textContent),
  tags: document.querySelectorAll('.dshst-tag').length,
}))
console.log(stat)
await browser.close()
console.log('shot:', OUT_PNG)
