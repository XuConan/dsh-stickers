// 验证：apply() 时会不会主动把 Python 后端拉起来（面板不经过工具，必须预热）。
// 用法：node scripts/smoke-start.mjs
const tools = []

const ctx = {
  effect(fn) {
    const dispose = fn()
    if (typeof dispose === 'function') dispose()
  },
  tools: {
    register(tool) {
      tools.push(tool.name)
      return () => {}
    },
  },
}

const mod = await import('../index.js')
await mod.apply(ctx, { port: 8799 })

console.log('tools:', tools.join(', '))

let ok = false
for (let i = 0; i < 40; i += 1) {
  try {
    const res = await fetch('http://127.0.0.1:8799/api/state', { signal: AbortSignal.timeout(1000) })
    if (res.ok) {
      const body = await res.json()
      ok = true
      console.log('backend up, total =', body.counts && body.counts.total)
      break
    }
  } catch {}
  await new Promise((r) => setTimeout(r, 500))
}

console.log(ok ? '[PASS] 后端已自动拉起' : '[FAIL] 10 秒内后端没起来')
process.exit(ok ? 0 : 1)
