/**
 * Host half of the sticker bundle.
 *
 * Owns the Python backend (`douyin-sticker-bot`): starts it on demand, stops it
 * on unload, and exposes it to the agent as tools. The Web UI half lives in
 * `client.js` and talks to the same local HTTP API.
 */
import { spawn } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, openSync, closeSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const inject = ['tools']

/**
 * `@deepseek-ai/dsh-tools` ships inside the Harness runtime, so a bundle that is
 * installed as a link (or copied outside the profile's `node_modules`) cannot
 * resolve it by bare specifier — Node looks up from the bundle's real path and
 * finds nothing. Import it lazily and fall back to a minimal normaliser, so the
 * bundle loads from any folder.
 */
let defineToolRef = null

async function resolveDefineTool() {
  if (defineToolRef) return defineToolRef
  try {
    const mod = await import('@deepseek-ai/dsh-tools')
    defineToolRef = typeof mod.defineTool === 'function' ? mod.defineTool : plainTool
  } catch {
    defineToolRef = plainTool
  }
  return defineToolRef
}

/** Human-readable projection of a tool result (the runtime requires `output.render`). */
function renderValue(value) {
  if (value && typeof value === 'object') {
    const lines = Object.entries(value).map(([key, item]) => {
      const text = item && typeof item === 'object' ? JSON.stringify(item) : String(item)
      return `${key}: ${text.length > 240 ? `${text.slice(0, 240)}…` : text}`
    })
    return lines.join('\n')
  }
  return String(value ?? '')
}

/** Fill in the `output.render` contract that `register()` insists on. */
function withDefaultRender(options) {
  const output = options.output || {}
  if (typeof output.render === 'function') return options
  return {
    ...options,
    output: {
      ...output,
      render: (_args, value) => [{ type: 'text', text: renderValue(value) }],
    },
  }
}

/** Shorthand `{key: {type, required, description}}` → object JSON Schema. */
function plainTool(options) {
  return {
    ...options,
    parameters: normalizeSchema({ type: 'object', properties: options.parameters || {} }),
    output: {
      ...(options.output || {}),
      schema: normalizeSchema(options.output?.schema || { type: 'object' }),
    },
  }
}

/**
 * `defineTool` accepts a shorthand where a property carries `required: true`;
 * the runtime validates against strict JSON Schema, so lift those flags into the
 * parent's `required` array (recursively).
 */
function normalizeSchema(spec) {
  if (!spec || typeof spec !== 'object') return spec
  const out = { ...spec }
  if (out.type === 'array' && out.items) out.items = normalizeSchema(out.items)
  if (out.properties && typeof out.properties === 'object') {
    const properties = {}
    const required = []
    for (const [key, child] of Object.entries(out.properties)) {
      const normalized = normalizeSchema(child)
      if (normalized && normalized.required === true) {
        required.push(key)
        delete normalized.required
      }
      properties[key] = normalized
    }
    out.properties = properties
    const declared = Array.isArray(out.required) ? out.required : []
    const merged = [...new Set([...declared, ...required])]
    if (merged.length) out.required = merged
    else delete out.required
  }
  return out
}

const HERE = dirname(fileURLToPath(import.meta.url))

/**
 * Where the Python backend lives. A packaged copy carries `douyin-sticker-bot`
 * next to (or inside) the bundle, so look there first; the absolute path is
 * only the fallback for this machine's dev layout.
 */
const PROJECT_CANDIDATES = [
  join(HERE, 'douyin-sticker-bot'),
  join(HERE, '..', 'douyin-sticker-bot'),
  join(HERE, '..', '..', 'douyin-sticker-bot'),
  'D:\\Documents\\deepseek-harness\\default-workspace\\douyin-sticker-bot',
]

function isProject(dir) {
  return !!dir && existsSync(join(dir, 'app', '__main__.py'))
}

function resolveProject(override) {
  if (override) return override
  const fromEnv = process.env.DSH_STICKERS_PROJECT
  if (isProject(fromEnv)) return fromEnv
  for (const dir of PROJECT_CANDIDATES) {
    if (isProject(dir)) return dir
  }
  return PROJECT_CANDIDATES[0]
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** Trim a stored candidate row down to what the model needs. */
function brief(item) {
  return {
    id: item.id,
    desc: item.desc || '',
    market: item.market || 'douyin',
    status: item.status,
    animated: !!item.is_animated,
    width: item.width || 0,
    height: item.height || 0,
  }
}

export async function apply(ctx, config = {}) {
  const baseDefineTool = await resolveDefineTool()
  const defineTool = (options) => baseDefineTool(withDefaultRender(options))
  const projectDir = resolveProject(config.projectDir)
  const port = Number(config.port || 8799)
  const autoStart = config.autoStart !== false
  const base = `http://127.0.0.1:${port}`
  let child = null

  const pythonPath = () =>
    config.pythonPath ||
    process.env.DSH_STICKERS_PYTHON ||
    (process.platform === 'win32'
      ? join(projectDir, '.venv', 'Scripts', 'python.exe')
      : join(projectDir, '.venv', 'bin', 'python'))

  /** One child process, output appended to data/setup.log, resolves with its exit code. */
  function run(cmd, args, logFd) {
    return new Promise((resolve) => {
      let settled = false
      const done = (value) => {
        if (!settled) {
          settled = true
          resolve(value)
        }
      }
      let proc
      try {
        proc = spawn(cmd, args, {
          cwd: projectDir,
          windowsHide: true,
          stdio: ['ignore', logFd, logFd],
        })
      } catch (err) {
        done({ code: -1, error: err })
        return
      }
      proc.on('error', (err) => done({ code: -1, error: err }))
      proc.on('exit', (code) => done({ code }))
    })
  }

  let pythonReady = null

  /**
   * Make sure `<project>/.venv` exists with the backend's dependencies.
   *
   * An install straight from a Git URL (or the portable zip) has no virtualenv,
   * so build one once: `venv --without-pip` first because plain `venv` trips over
   * a sandboxed ensurepip, then bootstrap pip and install requirements.
   */
  async function ensurePython() {
    const target = pythonPath()
    if (existsSync(target)) return target
    if (config.pythonPath || process.env.DSH_STICKERS_PYTHON) return target
    if (pythonReady) return pythonReady

    pythonReady = (async () => {
      const dataDir = join(projectDir, 'data')
      mkdirSync(dataDir, { recursive: true })
      const logPath = join(dataDir, 'setup.log')
      const say = (line) => {
        const text = `[${new Date().toISOString()}] ${line}\n`
        try {
          appendFileSync(logPath, text, 'utf8')
        } catch {}
        console.warn('[dsh-stickers]', line)
      }
      const logFd = openSync(logPath, 'a')
      try {
        say(`准备 Python 环境（${projectDir}），日志：${logPath}`)
        const candidates =
          process.platform === 'win32'
            ? [
                ['python', []],
                ['py', ['-3']],
              ]
            : [
                ['python3', []],
                ['python', []],
              ]
        let system = null
        for (const [cmd, prefix] of candidates) {
          const probe = await run(cmd, [...prefix, '-c', 'import sys; print(sys.version)'], logFd)
          if (probe.code === 0) {
            system = { cmd, prefix }
            break
          }
        }
        if (!system) {
          throw new Error(
            `没找到 Python。装一个 Python 3.9+ 并把它加进 PATH，然后重启 Harness。（日志：${logPath}）`,
          )
        }
        const venvDir = join(projectDir, '.venv')
        let made = await run(system.cmd, [...system.prefix, '-m', 'venv', '--without-pip', venvDir], logFd)
        if (made.code !== 0) {
          say('venv --without-pip 失败，改用普通 venv')
          made = await run(system.cmd, [...system.prefix, '-m', 'venv', venvDir], logFd)
        }
        if (!existsSync(target)) {
          closeSync(logFd)
          throw new Error(`建虚拟环境失败（${venvDir}）。日志：${logPath}`)
        }
        say('安装 pip')
        await run(target, ['-m', 'ensurepip', '--upgrade'], logFd)
        say('安装依赖（playwright / pillow / requests，约 1-2 分钟）')
        let pip = await run(target, ['-m', 'pip', 'install', '-r', 'requirements.txt', '--disable-pip-version-check'], logFd)
        if (pip.code !== 0) {
          say('默认源失败，改用清华镜像重试')
          pip = await run(
            target,
            [
              '-m',
              'pip',
              'install',
              '-r',
              'requirements.txt',
              '--disable-pip-version-check',
              '-i',
              'https://pypi.tuna.tsinghua.edu.cn/simple/',
            ],
            logFd,
          )
        }
        closeSync(logFd)
        if (pip.code !== 0) {
          throw new Error(`安装依赖失败。日志：${logPath}`)
        }
        say('Python 环境就绪')
        return target
      } catch (err) {
        try {
          closeSync(logFd)
        } catch {}
        throw err
      } finally {
        pythonReady = null
      }
    })()
    return pythonReady
  }

  async function healthy() {
    try {
      const res = await fetch(`${base}/api/state`, {
        signal: AbortSignal.timeout(1500),
      })
      return res.ok
    } catch {
      return false
    }
  }

  let starting = null

  async function doStart() {
    if (!autoStart) {
      throw new Error(
        `表情包服务没在运行（${base}）。先启动 ${projectDir} 下的 run.bat，或把插件配置里的 autoStart 打开。`,
      )
    }
    if (!isProject(projectDir)) {
      throw new Error(
        `找不到表情包后端：${projectDir}。把 douyin-sticker-bot 放到插件目录旁边，或在 cordis.patch.yml 里配 projectDir / 设环境变量 DSH_STICKERS_PROJECT 指过去。`,
      )
    }
    if (child) return
    const python = await ensurePython()
    let spawnError = null
    child = spawn(python, ['-m', 'app', '--no-browser', '--port', String(port)], {
      cwd: projectDir,
      windowsHide: true,
      stdio: 'ignore',
    })
    child.on('exit', () => {
      child = null
    })
    child.on('error', (err) => {
      spawnError = err
      child = null
    })
    for (let i = 0; i < 120; i += 1) {
      await sleep(250)
      if (spawnError) {
        throw new Error(
          `启动 Python 失败（${python}）：${spawnError.message}。看 ${join(projectDir, 'data', 'setup.log')}。`,
        )
      }
      if (await healthy()) return
    }
    throw new Error(`表情包服务启动超时：${python} -m app --port ${port}`)
  }

  async function startService() {
    if (await healthy()) return
    if (starting) return starting
    starting = doStart().finally(() => {
      starting = null
    })
    return starting
  }

  async function call(path, init) {
    await startService()
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init && init.headers) },
      signal: AbortSignal.timeout(120_000),
    })
    const text = await res.text()
    let body = null
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      body = { raw: text.slice(0, 400) }
    }
    if (!res.ok) {
      const message = (body && (body.error || body.message)) || `HTTP ${res.status}`
      throw new Error(message)
    }
    return body
  }

  ctx.effect(() => () => {
    if (child) {
      child.kill()
      child = null
    }
  })

  ctx.effect(() =>
    ctx.tools.register(
      defineTool({
        name: 'stickers_collect',
        description:
          '抓取表情包入库。source=douyin 时 mode 取 sticker（我的表情包）/collection（我的收藏）/like（我点赞的）/keyword/user；source=xhs 时 mode 取 smiles（要登录）/redmoji（免登录自带表情）；source=chinesebqb 时必须给 category（分类 id）。抓取在后台跑，用 stickers_list 看结果。',
        parameters: {
          source: {
            type: 'string',
            required: true,
            description: 'douyin | xhs | chinesebqb',
          },
          mode: {
            type: 'string',
            description: '抓取方式；抖音默认 sticker，小红书默认 redmoji，目录来源忽略此项',
          },
          keyword: {
            type: 'string',
            description: '抖音关键词/账号链接，或目录来源的关键词过滤',
          },
          category: {
            type: 'string',
            description: '目录来源的分类 id（先用 stickers_markets 查）',
          },
        },
        output: {
          schema: {
            type: 'object',
            additionalProperties: false,
            properties: {
              ok: { type: 'boolean', required: true, description: '是否已受理抓取任务' },
            },
          },
        },
        execute: async (args) => {
          const source = String(args.source || 'douyin')
          if (source === 'xhs') {
            await call('/api/collect', {
              method: 'POST',
              body: JSON.stringify({
                market: 'xhs',
                mode: args.mode || 'redmoji',
              }),
            })
          } else if (source === 'chinesebqb') {
            if (!args.category) throw new Error('中文表情包库需要先选分类，用 stickers_markets 查分类 id')
            await call('/api/collect', {
              method: 'POST',
              body: JSON.stringify({
                market: 'chinesebqb',
                category: args.category,
                value: args.keyword || '',
              }),
            })
          } else {
            await call('/api/collect', {
              method: 'POST',
              body: JSON.stringify({
                market: 'douyin',
                mode: args.mode || 'sticker',
                value: args.keyword || '',
              }),
            })
          }
          return { ok: true }
        },
      }),
    ),
  )

  ctx.effect(() =>
    ctx.tools.register(
      defineTool({
        name: 'stickers_markets',
        description:
          '列出表情包来源、它们的抓取方式、登录状态与（目录来源的）分类清单。抓取前先看这里。',
        parameters: {},
        output: {
          schema: {
            type: 'object',
            additionalProperties: false,
            properties: {
              markets: {
                type: 'array',
                required: true,
                description: '来源列表',
                items: {
                  type: 'object',
                  additionalProperties: false,
                  properties: {
                    id: { type: 'string', required: true, description: '来源 id' },
                    name: { type: 'string', required: true, description: '显示名' },
                    kind: { type: 'string', required: true, description: 'live | catalog' },
                    needsLogin: { type: 'boolean', required: true, description: '是否需要登录' },
                    loggedIn: { type: 'boolean', description: '当前是否已登录' },
                    modes: { type: 'array', description: '抓取方式 id', items: { type: 'string' } },
                    categories: { type: 'array', description: '目录来源的分类', items: { type: 'string' } },
                  },
                },
              },
            },
          },
        },
        execute: async () => {
          const [payload, state] = await Promise.all([call('/api/markets'), call('/api/state')])
          const login = (state && state.login) || {}
          return {
            markets: ((payload && payload.markets) || []).map((m) => ({
              id: m.id,
              name: m.name,
              kind: m.kind,
              needsLogin: !!m.needs_login,
              loggedIn: !!login[m.id],
              modes: (m.modes || []).map((x) => x.id || x),
              categories: (m.categories || []).slice(0, 200).map((c) => c.id),
            })),
          }
        },
      }),
    ),
  )

  ctx.effect(() =>
    ctx.tools.register(
      defineTool({
        name: 'stickers_list',
        description:
          '查看候选表情包列表（默认只看待下载）。返回 id、描述、来源、状态、尺寸。',
        parameters: {
          status: {
            type: 'string',
            description: 'new（默认）/downloaded/imported/skipped/error/all',
          },
          market: { type: 'string', description: 'douyin | xhs | chinesebqb，留空=全部来源' },
          limit: { type: 'number', description: '返回条数，默认 30，最大 200' },
          offset: { type: 'number', description: '偏移，用于翻页' },
        },
        output: {
          schema: {
            type: 'object',
            additionalProperties: false,
            properties: {
              total: { type: 'number', required: true, description: '符合筛选的总数' },
              items: {
                type: 'array',
                required: true,
                description: '候选列表',
                items: {
                  type: 'object',
                  additionalProperties: false,
                  properties: {
                    id: { type: 'number', required: true, description: '候选 id' },
                    desc: { type: 'string', required: true, description: '描述' },
                    market: { type: 'string', required: true, description: '来源' },
                    status: { type: 'string', required: true, description: '状态' },
                    animated: { type: 'boolean', required: true, description: '是否动图' },
                    width: { type: 'number', required: true, description: '宽' },
                    height: { type: 'number', required: true, description: '高' },
                  },
                },
              },
            },
          },
        },
        execute: async (args) => {
          const qs = new URLSearchParams({
            status: args.status || 'new',
            limit: String(Math.min(Number(args.limit) || 30, 200)),
            offset: String(Number(args.offset) || 0),
          })
          if (args.market) qs.set('market', args.market)
          const data = await call(`/api/candidates?${qs}`)
          return { total: data.total || 0, items: (data.items || []).map(brief) }
        },
      }),
    ),
  )

  ctx.effect(() =>
    ctx.tools.register(
      defineTool({
        name: 'stickers_download',
        description:
          '把选中的（或某个状态下的）候选下载并归一化成微信可用的 240x240 PNG/GIF，同时做查重。',
        parameters: {
          ids: {
            type: 'array',
            description: '要下载的候选 id；留空则按 status 批量下载',
            items: { type: 'number' },
          },
          status: { type: 'string', description: '不带 ids 时按状态批量下载，默认 new' },
        },
        output: {
          schema: {
            type: 'object',
            additionalProperties: false,
            properties: {
              started: { type: 'number', required: true, description: '已开始下载的条数' },
            },
          },
        },
        execute: async (args) => {
          const body = {}
          if (Array.isArray(args.ids) && args.ids.length) body.ids = args.ids
          else body.status = args.status || 'new'
          const data = await call('/api/download', { method: 'POST', body: JSON.stringify(body) })
          return { started: data.started || 0 }
        },
      }),
    ),
  )

  ctx.effect(() =>
    ctx.tools.register(
      defineTool({
        name: 'stickers_folder',
        description:
          '返回下载目录（素材库）的绝对路径；导入微信由用户手动拖进表情面板，工具不做自动导入。',
        parameters: {},
        output: {
          schema: {
            type: 'object',
            additionalProperties: false,
            properties: {
              folder: { type: 'string', required: true, description: '下载目录绝对路径' },
              opened: { type: 'boolean', required: true, description: '是否成功弹出资源管理器' },
            },
          },
        },
        execute: async () => {
          const data = await call('/api/open', {
            method: 'POST',
            body: JSON.stringify({ target: 'stickers' }),
          })
          return { folder: data.folder || '', opened: !!data.ok }
        },
      }),
    ),
  )

  // 面板（client.js）直接 fetch 后端，不经过工具；这里先把它拉起来，面板一打开就有数据
  if (autoStart) {
    startService().catch((err) => {
      console.warn('[dsh-stickers] 后台服务没能自动启动：', err && err.message ? err.message : err)
    })
  }
}
