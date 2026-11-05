/**
 * Smoke test for client.js without the Harness host: stubs the module loader,
 * React, and the slot/effect API, then runs `apply()` and prints what it
 * registered. Catches runtime shape errors that `node --check` cannot.
 */
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../client.js', import.meta.url), 'utf8')

let factory = null
globalThis.window = {
  __ModuleLoader__: {
    load({ id, factory: f }) {
      console.log('registered id:', id)
      factory = f
    },
  },
  DSH_STICKERS_PORT: '8799',
}

const styleNodes = []
globalThis.document = {
  head: { appendChild: (n) => styleNodes.push(n) },
  createElement: (tag) => ({ tag, dataset: {}, textContent: '', remove: () => {} }),
}

const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState: (v) => [v, () => {}],
  useEffect: () => {},
  useCallback: (f) => f,
  useRef: (v) => ({ current: v }),
}
const stubRequire = (name) => {
  if (name === 'react') return React
  throw new Error(`client.js required unexpected module: ${name}`)
}

new Function('window', src)(globalThis.window)
if (!factory) throw new Error('factory not registered')

const mod = factory(stubRequire)
console.log('exports keys:', Object.keys(mod))

const registered = []
const ctx = {
  effect: (fn) => {
    const dispose = fn()
    registered.push({ kind: 'effect', disposeType: typeof dispose })
    return dispose
  },
  slots: {
    inject: (owner, cb) => {
      const out = cb()
      registered.push({ kind: 'inject', owner, outType: typeof out })
      if (out && typeof out.next === 'function') {
        let step = out.next()
        while (!step.done) {
          registered.push({ kind: 'yield', owner, value: step.value })
          step = out.next()
        }
      }
      return out
    },
    register: (decl, comp) => {
      registered.push({ kind: 'register', decl, compType: typeof comp })
      return () => {}
    },
  },
}

mod.apply(ctx)
for (const r of registered) {
  if (r.kind === 'register') console.log('register:', JSON.stringify(r.decl), '->', r.compType)
  else if (r.kind === 'yield') console.log('yielded from', r.owner, ':', typeof r.value)
  else console.log(r.kind + ':', r.owner || r.disposeType)
}
console.log('OK: client.js applied cleanly')
