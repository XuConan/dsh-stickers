/**
 * Web half of the sticker bundle: a full page in the Harness Web UI.
 *
 * It renders inside the host's `main` slot (opened from the sidebar entry) and
 * talks to the local sticker backend over HTTP, so the page shows the same
 * library the standalone console does.
 */
window.__ModuleLoader__.load({
  id: 'dsh-stickers',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useCallback, useEffect, useRef, useState } = React

    const BASE = `http://127.0.0.1:${window.DSH_STICKERS_PORT || 8799}`
    const PAGE = 60

    async function api(path, init, hooks) {
      const method = (init && init.method) || 'GET'
      const attempts = method === 'GET' ? 15 : 0
      for (let attempt = 0; ; attempt += 1) {
        let res
        try {
          res = await fetch(`${BASE}${path}`, {
            ...init,
            headers: { 'Content-Type': 'application/json', ...(init && init.headers) },
          })
        } catch (err) {
          if (attempt >= attempts) throw err
          if (hooks && hooks.onWait) hooks.onWait(attempt)
          await new Promise((resolve) => setTimeout(resolve, 2000))
          continue
        }
        const text = await res.text()
        let body = null
        try {
          body = text ? JSON.parse(text) : null
        } catch {
          body = null
        }
        if (!res.ok) throw new Error((body && body.error) || `HTTP ${res.status}`)
        return body
      }
    }

    const STATUS = [
      ['new', '待下载'],
      ['downloaded', '已下载待导入'],
      ['imported', '已导入'],
      ['all', '全部'],
    ]

    // 卡片右下角的状态徽标：未下载 / 已下载 / 已有
    const STATUS_TEXT = {
      new: '未下载',
      downloaded: '已下载',
      imported: '已有',
      duplicate: '已有',
      skipped: '跳过',
      error: '出错',
    }
    const STATUS_CLASS = {
      new: 'wait',
      downloaded: 'dl',
      imported: 'ok',
      duplicate: 'ok',
      skipped: 'skip',
      error: 'err',
    }

    function Page() {
      const [markets, setMarkets] = useState([])
      const [market, setMarket] = useState('douyin')
      const [status, setStatus] = useState('all')
      const [mode, setMode] = useState('sticker')
      const [category, setCategory] = useState('__all__')
      const [login, setLogin] = useState({})
      const [items, setItems] = useState([])
      const [total, setTotal] = useState(0)
      const [offset, setOffset] = useState(0)
      const [jump, setJump] = useState('')
      const [sel, setSel] = useState(() => new Set())
      const [msg, setMsg] = useState('')
      const [busy, setBusy] = useState(false)
      const [counts, setCounts] = useState({})
      const alive = useRef(true)

      useEffect(() => () => {
        alive.current = false
      }, [])

      const loadMarkets = useCallback(async () => {
        const wait = () => {
          if (alive.current) setMsg('正在启动表情包服务，请稍等…')
        }
        try {
          const data = await api('/api/markets', undefined, { onWait: wait })
          if (!alive.current) return
          setMarkets((data && data.markets) || [])
          const st = await api('/api/state', undefined, { onWait: wait })
          if (!alive.current) return
          setCounts((st && st.counts) || {})
          setLogin((st && st.login) || {})
          setMsg('')
        } catch (err) {
          if (alive.current) setMsg(`连不上表情包服务：${err.message}`)
        }
      }, [])

      const load = useCallback(async () => {
        try {
          const qs = new URLSearchParams({
            status,
            limit: String(PAGE),
            offset: String(offset),
          })
          if (market) qs.set('market', market)
          // 目录型来源：列表跟着所选分类走，这样拉哪个分类就只看那个分类
          const cur = (markets || []).find((m) => m.id === market)
          if (cur && cur.kind === 'catalog' && category && category !== '__all__') {
            const hit = (cur.categories || []).find((c) => c.id === category)
            if (hit && hit.name) qs.set('desc', hit.name)
          }
          const data = await api(`/api/candidates?${qs}`)
          if (!alive.current) return
          setItems(data.items || [])
          setTotal(data.total || 0)
        } catch (err) {
          if (alive.current) setMsg(`加载失败：${err.message}`)
        }
      }, [market, status, offset, markets, category])

      useEffect(() => {
        loadMarkets()
      }, [loadMarkets])
      useEffect(() => {
        load()
      }, [load])

      const toggle = (id) => {
        setSel((prev) => {
          const next = new Set(prev)
          if (next.has(id)) next.delete(id)
          else next.add(id)
          return next
        })
      }

      const download = async () => {
        const ids = [...sel]
        if (!ids.length) {
          setMsg('先勾选几个表情')
          return
        }
        setBusy(true)
        try {
          const data = await api('/api/download', {
            method: 'POST',
            body: JSON.stringify({ ids }),
          })
          setMsg(`开始下载 ${data.started || 0} 个，完成后切到「已下载待导入」`)
          setSel(new Set())
          setStatus('downloaded')
          setOffset(0)
        } catch (err) {
          setMsg(`下载失败：${err.message}`)
        } finally {
          setBusy(false)
        }
      }

      const importToWechat = async () => {
        setBusy(true)
        try {
          const data = await api('/api/import/prepare', { method: 'POST', body: '{}' })
          let opened = true
          try {
            const res = await api('/api/open', {
              method: 'POST',
              body: JSON.stringify({ target: 'outbox' }),
            })
            opened = !!(res && res.ok !== false)
          } catch {
            opened = false
          }
          if (!opened) {
            try {
              await navigator.clipboard.writeText(data.folder || '')
            } catch {}
          }
          setMsg(
            opened
              ? `已平铺 ${data.count || 0} 个文件，把它们拖进微信表情面板，再点「我已导入」`
              : `已平铺 ${data.count || 0} 个文件到 ${data.folder}。窗口没自动弹出来，路径已复制，粘到资源管理器地址栏打开，全选拖进微信`,
          )
        } catch (err) {
          setMsg(`导入准备失败：${err.message}`)
        } finally {
          if (alive.current) setBusy(false)
        }
      }

      const markImported = async () => {
        setBusy(true)
        try {
          const data = await api('/api/import/done', { method: 'POST', body: '{}' })
          setMsg(`已标记 ${data.imported || 0} 个为已导入`)
          setSel(new Set())
          load()
          loadMarkets()
        } catch (err) {
          setMsg(`标记失败：${err.message}`)
        } finally {
          setBusy(false)
        }
      }

      const currentMarket = markets.find((m) => m.id === market) || null
      const modes = (currentMarket && currentMarket.modes) || []
      const cats = (currentMarket && currentMarket.categories) || []
      const isCatalog = !!(currentMarket && currentMarket.kind === 'catalog')
      const needsLogin = !!(currentMarket && currentMarket.needs_login)
      const loggedIn = !!login[market]

      useEffect(() => {
        if (isCatalog) {
          if (cats.length && !cats.some((c) => c.id === category)) setCategory(cats[0].id)
          return
        }
        if (!modes.length) return
        if (!modes.some((m) => m.id === mode)) setMode(modes[0].id)
      }, [market, markets])

      const collect = async () => {
        if (isCatalog && cats.length && !category) {
          setMsg('先选一个分类')
          return
        }
        if (needsLogin && !loggedIn && !(market === 'xhs' && mode === 'redmoji')) {
          setMsg(`先点右边「扫码登录」，${currentMarket ? currentMarket.name : ''}登录成功后再抓`)
          return
        }
        setBusy(true)
        setMsg(isCatalog ? '正在重新拉取（上次未下载的会被覆盖）…' : '已提交抓取，稍等…')
        const before = (counts && counts.total) || 0
        try {
          const body = isCatalog ? { market, category } : { market, mode }
          await api('/api/collect', { method: 'POST', body: JSON.stringify(body) })
          for (let i = 0; i < 40; i += 1) {
            await new Promise((r) => setTimeout(r, 1500))
            const st = await api('/api/state')
            if (!alive.current) return
            setCounts((st && st.counts) || {})
            setLogin((st && st.login) || {})
            if (!st.busy) {
              const now = (st.counts && st.counts.total) || 0
              const stLogin = (st.login && st.login[market]) || false
              const mname = currentMarket ? currentMarket.name : ''
              const run = (st.last_run && st.last_run.stats) || {}
              const captured = typeof run.captured === 'number' ? run.captured : null
              const added = typeof run.new === 'number' ? run.new : now - before
              if (added > 0) {
                setMsg(
                  `抓取完成：新增 ${added} 条${captured ? `（这个分类共 ${captured} 条）` : ''}，库里共 ${now} 条`,
                )
              } else if (needsLogin && !stLogin) {
                setMsg(`没抓到东西：先去上面「扫码登录」，${mname}登录后再点「开始抓取」`)
              } else {
                setMsg(
                  captured
                    ? `抓取完成：${mname} 这个分类共 ${captured} 条，都已经在库里了，没有新增`
                    : '抓取完成，没有新增（这些已经都在库里了）',
                )
              }
              setOffset(0)
              load()
              return
            }
          }
          setMsg('还在抓，过一会儿点「刷新」看看')
        } catch (err) {
          setMsg(`抓取失败：${err.message}`)
        } finally {
          if (alive.current) setBusy(false)
        }
      }

      const doLogin = async () => {
        setBusy(true)
        try {
          await api('/api/login', { method: 'POST', body: JSON.stringify({ market }) })
          setMsg(`已打开${currentMarket ? currentMarket.name : ''}登录窗口：扫码后回来点一次「检测」`)
        } catch (err) {
          setMsg(`打开登录窗口失败：${err.message}`)
        } finally {
          if (alive.current) setBusy(false)
        }
      }

      const pages = Math.max(1, Math.ceil(total / PAGE))
      const pageNo = Math.floor(offset / PAGE) + 1
      const doJump = () => {
        const n = parseInt(String(jump), 10)
        if (!Number.isFinite(n)) return
        const p = Math.min(pages, Math.max(1, n))
        setOffset((p - 1) * PAGE)
        setJump('')
      }

      return h(
        'div',
        { className: 'dshst-root' },
        h(
          'div',
          { className: 'dshst-head' },
          h('div', { className: 'dshst-title' }, '表情包收藏'),
          h(
            'div',
            { className: 'dshst-tabs' },
            markets.map((m) =>
              h(
                'button',
                {
                  key: m.id,
                  className: `dshst-tab${m.id === market ? ' on' : ''}`,
                  onClick: () => {
                    setMarket(m.id)
                    setOffset(0)
                    setSel(new Set())
                  },
                },
                m.name,
                counts.by_market && counts.by_market[m.id]
                  ? h('b', { className: 'n' }, counts.by_market[m.id])
                  : null,
              ),
            ),
          ),
        ),
        h(
          'div',
          { className: 'dshst-bar' },
          isCatalog
            ? h(
                'select',
                {
                  className: 'dshst-input',
                  value: category,
                  onChange: (e) => {
                    setCategory(e.target.value)
                    setOffset(0)
                  },
                },
                (cats.length ? cats : [{ id: '__all__', name: '全部表情包', count: 0 }]).map((c) =>
                  h(
                    'option',
                    { key: c.id, value: c.id },
                    c.id === '__all__' ? `${c.name}（${c.count}）` : `${c.number ? c.number + ' ' : ''}${c.name}（${c.count}）`,
                  ),
                ),
              )
            : h(
                'select',
                {
                  className: 'dshst-input',
                  value: mode,
                  onChange: (e) => setMode(e.target.value),
                },
                (modes.length ? modes : [{ id: 'sticker', name: '我的表情包' }]).map((m) =>
                  h('option', { key: m.id, value: m.id }, m.name),
                ),
              ),
          h('button', { className: 'dshst-btn primary', disabled: busy, onClick: collect }, '开始抓取'),
          needsLogin
            ? h('button', { className: 'dshst-btn', disabled: busy, onClick: doLogin }, loggedIn ? '检测' : '扫码登录')
            : null,
          h(
            'span',
            { className: 'dshst-dim' },
            needsLogin ? (loggedIn ? '已登录' : '未登录') : '免登录',
          ),
          h('span', { className: 'dshst-grow' }),
          h('button', { className: 'dshst-btn', disabled: busy, onClick: () => { loadMarkets(); load() } }, '刷新'),
        ),
        h(
          'div',
          { className: 'dshst-bar' },
          h(
            'select',
            {
              className: 'dshst-input',
              value: status,
              onChange: (e) => {
                setStatus(e.target.value)
                setOffset(0)
              },
            },
            STATUS.map(([v, t]) => h('option', { key: v, value: v }, t)),
          ),
          h(
            'button',
            { className: 'dshst-btn', onClick: () => setSel(new Set(items.map((i) => i.id))) },
            '全选本页',
          ),
          h('button', { className: 'dshst-btn', onClick: () => setSel(new Set()) }, '清空选择'),
          h('span', { className: 'dshst-dim' }, `已选 ${sel.size}`),
          h('span', { className: 'dshst-grow' }),
          h(
            'button',
            { className: 'dshst-btn', disabled: busy, onClick: download },
            `下载选中${sel.size ? `（${sel.size}）` : ''}`,
          ),
          h('button', { className: 'dshst-btn primary', disabled: busy, onClick: importToWechat }, '导入微信'),
          h('button', { className: 'dshst-btn', disabled: busy, onClick: markImported }, '我已导入'),
        ),
        msg ? h('div', { className: 'dshst-msg' }, msg) : null,
        h(
          'div',
          { className: 'dshst-grid' },
          items.map((it) =>
            h(
              'div',
              {
                key: it.id,
                className: `dshst-card${sel.has(it.id) ? ' on' : ''}`,
                onClick: () => toggle(it.id),
              },
              h(
                'div',
                { className: 'dshst-photo' },
                h('img', { className: 'dshst-thumb', src: `${BASE}/api/thumb/${it.id}`, alt: '', loading: 'lazy' }),
              ),
              // 分类名不再写在卡片上（选中哪个分类看上面的下拉就够了）
              isCatalog ? null : h('div', { className: 'dshst-meta' }, it.desc || '表情包'),
              h(
                'div',
                { className: 'dshst-tags' },
                h('span', { className: 'dshst-tag' }, it.is_animated ? 'GIF' : 'PNG'),
                it.market && it.market !== 'douyin' ? h('span', { className: 'dshst-tag src' }, it.market) : null,
                h(
                  'span',
                  { className: `dshst-badge ${STATUS_CLASS[it.status] || 'wait'}` },
                  STATUS_TEXT[it.status] || it.status,
                ),
              ),
            ),
          ),
          items.length
            ? null
            : h(
                'div',
                { className: 'dshst-empty' },
                needsLogin && !loggedIn
                  ? `还没读到${currentMarket ? currentMarket.name : ''}的表情：先点上面「扫码登录」，登录后再点「开始抓取」。`
                  : '这个筛选下没有表情，换个状态看看，或者点「开始抓取」。',
              ),
        ),
        h(
          'div',
          { className: 'dshst-foot' },
          h(
            'button',
            {
              className: 'dshst-btn',
              disabled: offset <= 0,
              onClick: () => setOffset(Math.max(0, offset - PAGE)),
            },
            '‹ 上一页',
          ),
          h('span', { className: 'dshst-dim' }, `第 ${pageNo} / ${pages} 页 · 共 ${total} 条`),
          h(
            'button',
            {
              className: 'dshst-btn',
              disabled: pageNo >= pages,
              onClick: () => setOffset(offset + PAGE),
            },
            '下一页 ›',
          ),
          h('span', { className: 'dshst-dim' }, '跳到'),
          h('input', {
            className: 'dshst-jump',
            type: 'number',
            min: 1,
            max: pages,
            value: jump,
            placeholder: String(pageNo),
            onChange: (e) => setJump(e.target.value),
            onKeyDown: (e) => {
              if (e.key === 'Enter') doJump()
            },
          }),
          h('button', { className: 'dshst-btn', onClick: doJump }, '页'),
          h(
            'button',
            {
              className: 'dshst-btn',
              disabled: pageNo >= pages,
              onClick: () => setOffset((pages - 1) * PAGE),
            },
            '末页 »',
          ),
        ),
      )
    }

    function EntryIcon() {
      return h('span', { className: 'dshst-icon', 'aria-hidden': true }, '🙂')
    }

    const CSS = `
.dshst-root { display: flex; flex-direction: column; gap: 12px; height: 100%; padding: 16px 20px 20px; box-sizing: border-box; overflow: hidden; color: var(--dsw-alias-text-primary, #e7e9ee); }
.dshst-head { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.dshst-title { font-size: 18px; font-weight: 600; }
.dshst-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
.dshst-tab { display: inline-flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: 999px; border: 1px solid var(--dsw-alias-border-base, #2c2f36); background: transparent; color: inherit; cursor: pointer; font: inherit; font-size: 13px; }
.dshst-tab.on { background: #ffd84d; border-color: #ffd84d; color: #17191c; font-weight: 600; }
.dshst-tab .n { font-size: 11px; opacity: .75; }
.dshst-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.dshst-grow { flex: 1 1 auto; }
.dshst-dim { font-size: 12px; opacity: .65; }
.dshst-input { padding: 6px 10px; border-radius: 8px; border: 1px solid var(--dsw-alias-border-base, #2c2f36); background: var(--dsw-alias-bg-input, #1a1d22); color: inherit; font: inherit; font-size: 13px; }
.dshst-btn { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--dsw-alias-border-base, #2c2f36); background: transparent; color: inherit; font: inherit; font-size: 13px; cursor: pointer; }
.dshst-btn:hover:not(:disabled) { background: rgba(255,255,255,.06); }
.dshst-btn:disabled { opacity: .45; cursor: default; }
.dshst-btn.primary { background: #1f6feb; border-color: #1f6feb; color: #fff; }
.dshst-msg { padding: 8px 12px; border-radius: 8px; background: rgba(255,216,77,.1); border: 1px solid rgba(255,216,77,.35); font-size: 12.5px; }
.dshst-grid { flex: 1 1 auto; overflow: auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(148px, 1fr)); grid-auto-rows: max-content; gap: 10px; align-content: start; }
.dshst-card { position: relative; align-self: start; border: 1px solid var(--dsw-alias-border-base, #2c2f36); border-radius: 10px; overflow: hidden; cursor: pointer; background: var(--dsw-alias-bg-card, #16191e); }
.dshst-card.on { border-color: #ffd84d; box-shadow: 0 0 0 1px #ffd84d inset; }
.dshst-thumb { display: block; width: 100%; aspect-ratio: 1/1; object-fit: contain; background: #0e1013; }
.dshst-photo { position: relative; display: block; }
/* 状态徽标放在卡片底部一行，靠右，不压住图里的字 */
.dshst-badge {
  margin-left: auto; padding: 1px 8px; border-radius: 999px;
  font-size: 11px; line-height: 16px; background: rgba(255, 255, 255, .06);
  border: 1px solid transparent; white-space: nowrap; pointer-events: none;
}
.dshst-badge.wait { color: #ffd84d; border-color: #6b5a20; }
.dshst-badge.dl { color: #7cc4ff; border-color: #2b5570; }
.dshst-badge.ok { color: #6ee7a8; border-color: #25603f; }
.dshst-badge.skip { color: #b9b9b9; border-color: #454545; }
.dshst-badge.err { color: #ff8b8b; border-color: #6b2a2a; }
.dshst-meta { padding: 6px 8px 0; font-size: 11.5px; opacity: .85; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dshst-tags { display: flex; align-items: center; gap: 4px; padding: 6px 8px 8px; flex-wrap: wrap; }
.dshst-tag { font-size: 10px; padding: 1px 6px; border-radius: 999px; border: 1px solid var(--dsw-alias-border-base, #2c2f36); opacity: .8; }
.dshst-tag.src { color: #ffd84d; border-color: #6b5a20; }
.dshst-empty { grid-column: 1 / -1; padding: 40px; text-align: center; font-size: 13px; opacity: .55; }
.dshst-foot { display: flex; align-items: center; gap: 10px; justify-content: center; }
.dshst-jump { width: 64px; padding: 4px 8px; border-radius: 8px; text-align: center;
  background: var(--dsw-alias-surface-2, #17191c); color: inherit;
  border: 1px solid var(--dsw-alias-line, #2a2e33); font-size: 12px; }
.dshst-icon { font-size: 18px; line-height: 1; }
`

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.effect(() => {
          const style = document.createElement('style')
          style.dataset.plugin = 'dsh-stickers'
          style.textContent = CSS
          document.head.appendChild(style)
          return () => style.remove()
        })
        ctx.slots.inject('main', function* registerPanel() {
          yield ctx.slots.register({ name: 'main', key: 'stickers', order: 60 }, Page)
        })
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            { name: 'sidebar.panellist', id: 'stickers', order: 60, label: () => '表情包' },
            EntryIcon,
          ),
        )
      },
    }
  },
})
