/* 抖音表情包 -> 微信 控制台 */
'use strict';

const $ = (id) => document.getElementById(id);

const S = {
  items: [],
  markets: [],
  sel: new Set(),
  selByMarket: {},    // 每个页签各自记住勾选了哪些（各管各的）
  statusOf: new Map(),
  page: 0,
  limit: 60,
  total: 0,
  touched: new Set(),
  busy: false,
  loggedIn: null,
  login: {},          // 各来源的登录态：{ douyin: bool, xhs: bool }
  modeByMarket: {},   // 各页签各自记住的抓取方式
  counts: {},
  sent: new Set(),
  refreshTimer: null,
};

/* ---------------- 基础请求 ---------------- */
async function api(path, body) {
  const opt = body === undefined
    ? { method: 'GET' }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (_) { data = {}; }
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}

/* ---------------- 日志 ---------------- */
function logLine(text, level) {
  const box = $('log');
  const div = document.createElement('div');
  if (level === 'ok') div.className = 'l-ok';
  else if (level === 'warn') div.className = 'l-warn';
  else if (level === 'err') div.className = 'l-err';
  const t = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  div.textContent = `[${t}] ${text}`;
  box.appendChild(div);
  while (box.childElementCount > 300) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

function setProgress(pct, text) {
  $('bar').style.width = Math.max(0, Math.min(100, pct)) + '%';
  if (text !== undefined) $('progress-text').textContent = text;
}

/* ---------------- 状态 ---------------- */
function applyState(st) {
  const c = st.counts || {};
  S.counts = c;
  $('chip-count').textContent =
    `候选 ${c.total || 0} · 已下载 ${c.downloaded || 0} · 已导入 ${c.imported || 0}`;
  S.loggedIn = !!st.logged_in;
  S.login = st.login || { douyin: S.loggedIn };
  if (S.markets && S.markets.length) syncMarketUI();
}

async function refreshState() {
  try { applyState(await api('/api/state')); } catch (e) { /* 忽略 */ }
}

/* ---------------- 列表 ---------------- */
function currentStatuses() {
  const v = $('filter').value;
  return (v && v !== 'all') ? v.split(',').filter(Boolean) : [];   /* all = 全部 */
}

async function loadList() {
  const statuses = currentStatuses();
  const parts = ['status=' + encodeURIComponent(statuses.length ? statuses.join(',') : 'all')];
  const mf = $('market-filter').value;
  if (mf) parts.push('market=' + encodeURIComponent(mf));
  parts.push('offset=' + (S.page * S.limit), 'limit=' + S.limit);
  let data;
  try {
    data = await api('/api/candidates?' + parts.join('&'));
  } catch (e) {
    logLine('加载列表失败：' + e.message, 'err');
    return;
  }
  S.items = data.items || [];
  // 页码越界（比如最后一页被下载完了）就回退一页
  if (!S.items.length && S.page > 0) {
    S.page = Math.max(0, S.page - 1);
    return loadList();
  }
  S.total = data.total || 0;
  for (const it of S.items) S.statusOf.set(it.id, it.status);
  for (const it of S.items) {
    if (it.status === 'new' && !S.touched.has(it.id)) S.sel.add(it.id);
  }
  render();
  refreshState();
}

const STATUS_LABEL = {
  new: '待下载', downloaded: '已下载', skipped: '跳过',
  duplicate: '重复', imported: '已导入', error: '失败',
};

function emptyText() {
  const v = $('filter').value;
  if (v === 'new') {
    return '没有待下载的了。点右上「导入微信」把已下载的拖进微信，或者点「开始抓取」拉最新表情包。';
  }
  if (v === 'downloaded') return '还没有下载好的文件。切到「待下载」勾选后点「下载选中」。';
  if (v === 'all') return '库里还没有表情包。点「开始抓取」先拉一次。';
  return '这个分类下没有表情包。';
}

function render() {
  const grid = $('grid');
  grid.textContent = '';
  $('empty').textContent = emptyText();
  $('empty').classList.toggle('show', S.items.length === 0);

  const frag = document.createDocumentFragment();
  for (const it of S.items) {
    const card = document.createElement('div');
    card.className = 'card' + (S.sel.has(it.id) ? ' sel' : '');
    card.dataset.id = it.id;

    const check = document.createElement('div');
    check.className = 'check';
    check.textContent = '✓';
    card.appendChild(check);

    const thumb = document.createElement('div');
    thumb.className = 'thumb';
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.alt = it.desc || '';
    img.src = '/api/thumb/' + it.id;
    img.addEventListener('error', () => {
      // 原图太大/太慢的时候后端会放弃生成缩略图，给个占位而不是空白
      const ph = document.createElement('span');
      ph.className = 'thumb-ph';
      ph.textContent = '原图太大，下载后可看';
      thumb.replaceChild(ph, img);
    });
    thumb.appendChild(img);
    card.appendChild(thumb);

    const info = document.createElement('div');
    info.className = 'info';

    const desc = document.createElement('div');
    desc.className = 'desc';
    desc.textContent = it.desc || '（无描述）';
    info.appendChild(desc);

    const row = document.createElement('div');
    row.className = 'row';

    const author = document.createElement('span');
    author.className = 'author';
    author.textContent = it.author ? '@' + it.author : '';
    row.appendChild(author);

    const badges = document.createElement('span');
    badges.className = 'tags';
    const kind = document.createElement('span');
    kind.className = 'badge ' + (it.is_animated ? 'gif' : 'png');
    kind.textContent = it.is_animated ? 'GIF' : 'PNG';
    badges.appendChild(kind);
    const src = it.market || 'douyin';
    if (src !== 'douyin') {
      const pill = document.createElement('span');
      pill.className = 'src-pill';
      pill.textContent = MARKET_SHORT[src] || MARKET_LABELS[src] || src;
      thumb.appendChild(pill);
    }
    const stt = document.createElement('span');
    stt.className = 'badge s-' + it.status;
    stt.textContent = STATUS_LABEL[it.status] || it.status;
    badges.appendChild(stt);
    row.appendChild(badges);

    info.appendChild(row);
    card.appendChild(info);

    card.addEventListener('click', () => toggle(it.id));
    frag.appendChild(card);
  }
  grid.appendChild(frag);
  updateCounter();
  updatePager();
}

function updatePager() {
  const pages = Math.max(1, Math.ceil(S.total / S.limit));
  const info = $('pageinfo');
  if (info) info.textContent = `${S.page + 1} / ${pages} · 共 ${S.total}`;
  const prev = $('btn-prev');
  const next = $('btn-next');
  if (prev) prev.disabled = S.page <= 0;
  if (next) next.disabled = S.page + 1 >= pages;
}

function toggle(id) {
  if (S.sel.has(id)) S.sel.delete(id); else S.sel.add(id);
  S.touched.add(id);
  const card = document.querySelector(`.card[data-id="${id}"]`);
  if (card) card.classList.toggle('sel', S.sel.has(id));
  updateCounter();
}

function updateCounter() {
  $('counter').textContent = `已选 ${S.sel.size}`;
  const n = actionableIds().length;
  $('btn-download').textContent = n ? `下载选中 (${n})` : '下载选中';
}

function actionableIds() {
  return [...S.sel].filter((id) => {
    const st = S.statusOf.get(id);
    return ['new', 'skipped', 'error'].includes(st);
  });
}

/* ---------------- 来源（市场） ---------------- */
const MARKET_LABELS = { douyin: '抖音', xhs: '小红书', chinesebqb: '中文表情包库' };
const MARKET_SHORT = { douyin: '抖音', xhs: 'XHS', chinesebqb: 'BQB' };
/* 只有这些抓取方式需要用户填内容（关键词 / 主页链接） */
const VALUED_MODES = ['keyword', 'user'];
const MODE_LABELS = {
  sticker: '我的表情包', collection: '我的收藏', like: '我点赞的',
  smiles: '我的表情包', redmoji: '小红书自带表情',
};
function modeNeedsValue() { return VALUED_MODES.includes($('mode').value); }

function currentMarket() {
  return S.markets.find((m) => m.id === $('market').value)
    || { id: 'douyin', name: '抖音', kind: 'live', categories: [] };
}

/* 抓取方式选项跟着来源走：抖音 5 种，小红书 2 种。各页签各记各的。 */
function renderModes() {
  const sel = $('mode');
  if (!sel) return;
  const mk = currentMarket();
  const modes = mk.modes || [];
  if (!modes.length) return;
  S.modeByMarket = S.modeByMarket || {};
  const want = S.modeByMarket[mk.id] || sel.value;
  sel.textContent = '';
  for (const mo of modes) {
    const o = document.createElement('option');
    o.value = mo.id;
    o.textContent = mo.name;
    sel.appendChild(o);
  }
  if (want && [...sel.options].some((o) => o.value === want)) sel.value = want;
  S.modeByMarket[mk.id] = sel.value;
}

/* 当前来源是否已登录（后端 /api/state 的 login 字段） */
function marketLoggedIn(m) {
  const id = (m || currentMarket()).id;
  if (S.login && id in S.login) return !!S.login[id];
  return !!S.loggedIn;
}

function syncModeUI() {
  const need = modeNeedsValue();
  const q = $('query');
  q.disabled = !need;
  q.style.opacity = need ? '1' : '0.45';
  q.placeholder = need
    ? ($('mode').value === 'keyword' ? '输入关键词，例如：猫咪表情包' : '粘贴账号主页链接，例如 https://www.douyin.com/user/MS4wLj...')
    : '点「开始抓取」即可，不用填内容';
}

/* 目录型来源：显示分类下拉，隐藏抖音的抓取方式 */
function renderMarketTabs() {
  const box = $('market-tabs');
  if (!box) return;
  const now = $('market').value || 'douyin';
  box.textContent = '';
  for (const m of S.markets) {
    const b = document.createElement('button');
    b.className = 'mtab' + (m.id === now ? ' on' : '');
    b.dataset.market = m.id;
    b.textContent = m.name || m.id;
    if (m.kind === 'live') {
      const dot = document.createElement('i');
      dot.className = 'dot' + (marketLoggedIn(m) ? ' on' : '');
      b.appendChild(dot);
    }
    const n = (S.counts && S.counts.by_market && S.counts.by_market[m.id]) || 0;
    if (n) {
      const num = document.createElement('b');
      num.className = 'n';
      num.textContent = n;
      b.appendChild(num);
    }
    b.addEventListener('click', () => pickMarket(m.id));
    box.appendChild(b);
  }
}

function pickMarket(id) {
  const cur = $('market').value;
  if (cur === id) return;
  /* 各管各的：切页签时把当前页签的勾选存起来，切回来还在 */
  S.selByMarket = S.selByMarket || {};
  S.selByMarket[cur] = new Set(S.sel);
  $('market').value = id;
  const mf = $('market-filter');
  if (mf) mf.value = id;
  S.sel = new Set(S.selByMarket[id] || []);
  S.touched.clear();
  S.page = 0;
  syncMarketUI();
  loadList();
}

const LOGIN_HINTS = {
  douyin: '抖音要登录才能读到你的表情包：点右上角「登录/检测」，在弹出的浏览器里扫码、过一下滑块，然后回来再点一次检测。',
  xhs: '小红书要登录才能读到你的表情包：点右上角「登录/检测」，在弹出的浏览器里扫码登录，成功后会自己关掉窗口。自带表情不用登录。',
};

/* 某些来源里只有部分抓取方式需要登录（小红书自带表情免登录） */
const LOGIN_MODES = { xhs: ['smiles'] };

function syncLoginHint() {
  const box = $('login-hint');
  if (!box) return;
  const m = currentMarket();
  const limited = LOGIN_MODES[m.id];
  const modeNeedsLogin = !limited || limited.includes($('mode').value);
  const need = !!m.needs_login && modeNeedsLogin && !marketLoggedIn(m);
  box.hidden = !need;
  if (need) box.textContent = LOGIN_HINTS[m.id] || `${m.name} 需要先登录：点右上角「登录/检测」。`;
}

function renderLoginChip() {
  const chip = $('chip-login');
  if (!chip) return;
  const m = currentMarket();
  const who = MARKET_SHORT[m.id] || m.name || '';
  if (marketLoggedIn(m)) { chip.textContent = `${who} 登录：已登录`; chip.className = 'chip ok'; }
  else { chip.textContent = `${who} 登录：未登录`; chip.className = 'chip bad'; }
}

function syncMarketUI() {
  const m = currentMarket();
  const catalog = m.kind === 'catalog';
  $('mode').hidden = catalog;
  $('category').hidden = true;      // 真正的分类选择器是 #cat-picker 里的按钮
  $('btn-refresh-manifest').hidden = !catalog;
  const picker = $('cat-picker');
  if (picker && !catalog) picker.hidden = true;   // 非目录市场不能露出分类胶囊
  renderMarketTabs();
  renderModes();
  renderLoginChip();
  syncLoginHint();
  if (!catalog) {
    syncModeUI();
    return;
  }
  const sel = $('category');
  const keep = sel.value;
  sel.textContent = '';
  const cats = m.categories || [];
  if (!cats.length) {
    const o = document.createElement('option');
    o.value = '';
    o.textContent = '（还没有清单，点右边「刷新清单」）';
    sel.appendChild(o);
  }
  for (const c of cats) {
    const o = document.createElement('option');
    o.value = c.id;
    o.textContent = `${c.name}（${c.count}）`;
    sel.appendChild(o);
  }
  if (keep && [...sel.options].some((o) => o.value === keep)) sel.value = keep;
  if (!sel.value && cats.length) sel.value = cats[0].id;
  renderCatList();
  const q = $('query');
  q.disabled = false;
  q.style.opacity = '1';
  q.placeholder = '可选：按关键词过滤，留空＝整个分类';
}

function renderCatList() {
  const box = $('cat-list');
  const picker = $('cat-picker');
  if (!box || !picker) return;
  picker.hidden = currentMarket().kind !== 'catalog';
  if (picker.hidden) return;
  const cats = currentMarket().categories || [];
  const now = $('category').value;
  const kw = ($('cat-search').value || '').trim().toLowerCase();
  const shown = cats.filter((c) => !kw
    || (c.name || '').toLowerCase().includes(kw)
    || (c.id || '').toLowerCase().includes(kw)
    || String(c.number || '') === kw);
  box.textContent = '';
  if (!cats.length) {
    const s = document.createElement('span');
    s.className = 'cat-empty';
    s.textContent = '还没有清单，点右边「刷新清单」拉一份';
    box.appendChild(s);
  }
  for (const c of shown) {
    const b = document.createElement('button');
    b.className = 'cat' + (c.id === now ? ' on' : '');
    b.dataset.id = c.id;
    const i = document.createElement('i');
    i.textContent = `${c.number ? c.number + ' ' : ''}${c.name}`;
    const n = document.createElement('b');
    n.textContent = String(c.count);
    b.append(i, n);
    b.addEventListener('click', () => {
      $('category').value = c.id;
      renderCatList();
    });
    box.appendChild(b);
  }
  const total = cats.filter((c) => c.id !== '__all__').reduce((n, c) => n + (c.count || 0), 0);
  const real = cats.filter((c) => c.id !== '__all__').length;
  $('cat-meta').textContent = `${real} 个分类 · ${total} 张`;
}

async function loadMarkets() {
  let data;
  try {
    data = await api('/api/markets');
  } catch (e) {
    logLine('加载来源失败：' + e.message, 'err');
    return;
  }
  S.markets = data.markets || [];
  const sel = $('market');
  const keep = sel.value || 'douyin';
  sel.textContent = '';
  for (const m of S.markets) {
    const o = document.createElement('option');
    o.value = m.id;
    o.textContent = m.name;
    sel.appendChild(o);
  }
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;

  const mf = $('market-filter');
  const keepF = mf.value;
  mf.textContent = '';
  const all = document.createElement('option');
  all.value = '';
  all.textContent = '全部来源';
  mf.appendChild(all);
  for (const m of S.markets) {
    const o = document.createElement('option');
    o.value = m.id;
    o.textContent = MARKET_LABELS[m.id] || m.name;
    mf.appendChild(o);
  }
  mf.value = keepF || sel.value || '';
  syncMarketUI();
}

async function collect() {
  const m = currentMarket();
  const value = $('query').value.trim();
  let payload;
  let what;
  if (m.kind === 'catalog') {
    const category = $('category').value;
    if (!category) { logLine('先选一个分类（或点「刷新清单」拉一份）', 'warn'); return; }
    payload = { market: m.id, category, value };
    what = `${m.name} · ${($('category').selectedOptions[0] || {}).textContent || category}`;
  } else {
    const mode = $('mode').value;
    if (modeNeedsValue() && !value) { $('query').focus(); return; }
    payload = { market: m.id, mode, value };
    what = value || MODE_LABELS[mode] || mode;
  }
  $('btn-collect').disabled = true;
  const opening = m.id === 'xhs' ? '正在读取小红书表情…'
    : (payload.mode === 'sticker' ? '正在读取我的表情包…'
      : (payload.mode === 'collection' ? '正在读取我的收藏…' : '打开浏览器…'));
  setProgress(2, m.kind === 'catalog' ? '正在读取清单…' : opening);
  try {
    await api('/api/collect', payload);
    logLine('已提交抓取请求：' + what);
  } catch (e) {
    logLine('抓取失败：' + e.message, 'err');
    $('btn-collect').disabled = false;
    setProgress(0, '空闲');
  }
}

/* ---------------- 下载 ---------------- */
/* ---------------- 清空列表 ---------------- */
async function clearList() {
  const statusRaw = currentStatuses().join(',') || 'all';
  const statusText = $('filter').selectedOptions[0]?.textContent || statusRaw;
  const mf = $('market-filter').value;
  const marketText = mf ? (MARKET_LABELS[mf] || mf) : '全部来源';
  const total = S.total;
  const msg = `确定清空「${marketText} · ${statusText}」这 ${total} 条记录吗？\n`
    + '只删列表记录，已经下载到素材库的文件不会删。';
  if (!window.confirm(msg)) return;
  try {
    const r = await api('/api/candidates/clear',
      { status: statusRaw, market: mf || 'all' });
    S.sel.clear();
    S.touched.clear();
    S.statusOf.clear();
    S.page = 0;
    logLine(`已清空 ${r.deleted} 条记录`, 'ok');
    await loadList();
  } catch (e) {
    logLine('清空失败：' + e.message, 'err');
  }
}

async function download() {
  const ids = actionableIds();
  if (!ids.length) { logLine('没有可下载的选中项', 'warn'); return; }
  $('btn-download').disabled = true;
  try {
    const r = await api('/api/download', { ids });
    if (!r.ok) logLine('下载未启动：' + (r.error || '未知原因'), 'warn');
    else {
      S.sent = new Set(ids);
      logLine(`开始下载 ${r.queued} 个…`); setProgress(0, '下载中…');
    }
  } catch (e) {
    logLine('下载请求失败：' + e.message, 'err');
  } finally {
    $('btn-download').disabled = false;
  }
}

/* ---------------- 导入微信 ---------------- */
function openImportModal(count, folder) {
  $('imp-count').textContent = count;
  $('imp-path').textContent = folder || '';
  $('mask').classList.add('show');
}

/* ---------------- 本地文件管理 ---------------- */
function fmtSize(n) {
  if (!n) return '0 KB';
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}

async function openLocal() {
  $('local-mask').classList.add('show');
  await refreshLocal();
}

async function refreshLocal() {
  let d;
  try {
    d = await api('/api/local');
  } catch (e) {
    logLine('读取本地文件失败：' + e.message, 'err');
    return;
  }
  const ob = d.outbox || { files: [], count: 0, bytes: 0, dir: '' };
  const lib = d.library || { count: 0, bytes: 0, dir: '', imported: 0 };
  $('loc-ob-count').textContent = `${ob.count} 个文件`;
  $('loc-ob-size').textContent = fmtSize(ob.bytes);
  $('loc-ob-path').textContent = ob.dir;
  $('loc-lib-count').textContent = `${lib.count} 个文件`;
  $('loc-lib-size').textContent = fmtSize(lib.bytes);
  $('loc-lib-imported').textContent = lib.imported;
  $('loc-lib-path').textContent = lib.dir;

  const grid = $('loc-ob-grid');
  grid.innerHTML = '';
  $('loc-ob-empty').hidden = ob.count > 0;
  for (const f of ob.files) {
    const cell = document.createElement('div');
    cell.className = 'loc-cell';
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.src = '/api/local/file?name=' + encodeURIComponent(f.name);
    img.alt = f.name;
    const name = document.createElement('span');
    name.className = 'loc-name';
    name.textContent = f.name;
    const size = document.createElement('span');
    size.className = 'loc-size';
    size.textContent = fmtSize(f.size);
    const del = document.createElement('button');
    del.className = 'loc-del';
    del.title = '从导出夹删掉这个文件';
    del.textContent = '×';
    del.addEventListener('click', async () => {
      if (!window.confirm(`从导出夹删掉 ${f.name}？`)) return;
      try {
        await api('/api/local/delete', { name: f.name });
        await refreshLocal();
      } catch (e) {
        logLine('删除失败：' + e.message, 'err');
      }
    });
    cell.append(img, name, size, del);
    grid.appendChild(cell);
  }
}

async function localClearOutbox() {
  const n = $('loc-ob-count').textContent;
  if (!window.confirm(`清空导出夹（${n}）？素材库里的原图不受影响。`)) return;
  try {
    const r = await api('/api/local/clear', {});
    logLine(`导出夹已清空（${r.removed} 个文件）`, 'ok');
    await refreshLocal();
  } catch (e) {
    logLine('清空失败：' + e.message, 'err');
  }
}

async function localPurge(scope, label) {
  const tips = {
    orphan: '删除素材库里没有任何记录引用的图片（一般是历史残留）',
    imported: '删除「已导入」那批的原图，列表记录保留',
  };
  if (!window.confirm(`${tips[scope]}，确定吗？`)) return;
  try {
    const r = await api('/api/local/purge', { scope });
    logLine(`${label}：删除 ${r.removed} 个文件，释放 ${fmtSize(r.bytes)}`, 'ok');
    await refreshLocal();
  } catch (e) {
    logLine('清理失败：' + e.message, 'err');
  }
}

async function prepareImport() {
  $('btn-import').disabled = true;
  try {
    const r = await api('/api/import/prepare', {});
    if (!r.count) {
      logLine('没有已下载的表情，先下载一些吧', 'warn');
      return;
    }
    openImportModal(r.count, r.folder);
    logLine(`已导出 ${r.count} 个文件到导出文件夹`, 'ok');
  } catch (e) {
    logLine('导出失败：' + e.message, 'err');
  } finally {
    $('btn-import').disabled = false;
  }
}

async function importDone() {
  try {
    const r = await api('/api/import/done', {});
    logLine(`已标记 ${r.imported || 0} 个为已导入`, 'ok');
    $('mask').classList.remove('show');
    S.sel.clear();
    await loadList();
  } catch (e) {
    logLine('标记失败：' + e.message, 'err');
  }
}

/* ---------------- SSE ---------------- */
function scheduleRefresh() {
  clearTimeout(S.refreshTimer);
  S.refreshTimer = setTimeout(loadList, 400);
}

function bindEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (_) { return; }
    switch (m.type) {
      case 'progress': {
        if (m.phase === 'browse') {
          const n = m.count || 0;
          setProgress(Math.min(92, 6 + n * 2.2), `浏览中… 已发现 ${n} 条`);
        } else if (m.phase === 'download' && m.total) {
          setProgress(Math.round((m.done / m.total) * 100), `下载中 ${m.done}/${m.total}`);
        }
        break;
      }
      case 'candidate':
        scheduleRefresh();
        break;
      case 'collect_done':
        $('btn-collect').disabled = false;
        setProgress(100, '抓取完成');
        logLine(`抓取完成：共 ${m.captured} 条，新增 ${m.new}，过小跳过 ${m.skipped}` +
                (m.skipped_video ? `，视频跳过 ${m.skipped_video}` : ''), 'ok');
        loadList();
        break;
      case 'download_done':
        setProgress(100, '下载完成');
        logLine(`下载结束：成功 ${m.ok}，重复 ${m.dup}，失败 ${m.fail}`, 'ok');
        // 这批已经不是「待下载」了，把它们从选中集合里摘掉（可能跨了好几页）
        for (const id of S.sent) S.sel.delete(id);
        S.sent = new Set();
        loadList();
        break;
      case 'local_changed':
        if ($('local-mask').classList.contains('show')) refreshLocal();
        break;
      case 'need_login':
        $('btn-collect').disabled = false;
        setProgress(0, '等待扫码登录');
        logLine(m.msg || (m.market === 'xhs' ? '需要登录小红书' : '需要登录抖音'), 'warn');
        break;
      case 'login_state': {
        const mid = m.market || 'douyin';
        S.login = S.login || {};
        S.login[mid] = !!m.logged_in;
        if (mid === 'douyin') S.loggedIn = m.logged_in;
        renderLoginChip();
        if (S.markets && S.markets.length) syncMarketUI();
        break;
      }
      case 'warn':
        logLine(m.msg || '', 'warn');
        break;
      case 'error':
        $('btn-collect').disabled = false;
        setProgress(0, '出错');
        logLine(m.msg || '出错', 'err');
        break;
      case 'log':
        logLine(m.msg || '');
        break;
      default:
        break;
    }
  };
  es.onerror = () => { $('progress-text').textContent = '与后台断线，重连中…'; };
}

/* ---------------- 初始化 ---------------- */
function bindUI() {
  $('btn-collect').addEventListener('click', collect);
  $('mode').addEventListener('change', () => {
    S.modeByMarket = S.modeByMarket || {};
    S.modeByMarket[currentMarket().id] = $('mode').value;
    syncModeUI();
    syncLoginHint();
  });
  $('cat-search').addEventListener('input', renderCatList);
  $('market').addEventListener('change', syncMarketUI);
  $('market-filter').addEventListener('change', () => { S.touched.clear(); S.page = 0; loadList(); });
  $('filter').addEventListener('change', () => { S.touched.clear(); S.page = 0; loadList(); });
  $('btn-prev').addEventListener('click', () => { if (S.page > 0) { S.page -= 1; loadList(); } });
  $('btn-next').addEventListener('click', () => {
    if ((S.page + 1) * S.limit < S.total) { S.page += 1; loadList(); }
  });
  $('btn-refresh-manifest').addEventListener('click', async () => {
    const m = currentMarket();
    $('btn-refresh-manifest').disabled = true;
    logLine('正在拉取「' + m.name + '」清单，可能要 20 秒左右…', 'warn');
    try {
      await api('/api/market/refresh', { market: m.id });
      await loadMarkets();
      logLine('清单已更新', 'ok');
    } catch (e) {
      logLine('刷新清单失败：' + e.message, 'err');
    } finally {
      $('btn-refresh-manifest').disabled = false;
    }
  });
  $('query').addEventListener('keydown', (e) => { if (e.key === 'Enter') collect(); });
  $('btn-login').addEventListener('click', async () => {
    const m = currentMarket();
    try {
      await api('/api/login', { market: m.id });
      logLine(`正在打开${m.name || m.id}，请扫码登录…`, 'warn');
    } catch (e) { logLine('打开登录失败：' + e.message, 'err'); }
  });
  $('btn-refresh').addEventListener('click', () => { loadList(); logLine('已刷新'); });
  $('filter').addEventListener('change', () => { S.touched.clear(); S.page = 0; loadList(); });
  $('btn-all').addEventListener('click', () => {
    for (const it of S.items) { S.sel.add(it.id); S.touched.add(it.id); }
    render();
  });
  $('btn-none').addEventListener('click', () => {
    // 取消整个选择（不只是当前页），否则翻回去看还是勾着的
    for (const id of [...S.sel]) S.touched.add(id);
    S.sel.clear();
    render();
  });
  $('btn-clear-list').addEventListener('click', clearList);
  $('btn-download').addEventListener('click', download);
  $('btn-import').addEventListener('click', prepareImport);

  $('btn-imp-cancel').addEventListener('click', () => $('mask').classList.remove('show'));
  $('btn-imp-done').addEventListener('click', importDone);
  $('btn-imp-open').addEventListener('click', () => {
    api('/api/open', { target: 'outbox' }).catch((e) => logLine(e.message, 'err'));
  });
  $('mask').addEventListener('click', (e) => {
    if (e.target === $('mask')) $('mask').classList.remove('show');
  });

  $('btn-local').addEventListener('click', openLocal);
  $('btn-loc-close').addEventListener('click', () => $('local-mask').classList.remove('show'));
  $('local-mask').addEventListener('click', (e) => {
    if (e.target === $('local-mask')) $('local-mask').classList.remove('show');
  });
  $('btn-loc-ob-clear').addEventListener('click', localClearOutbox);
  $('btn-loc-ob-open').addEventListener('click', () => {
    api('/api/open', { target: 'outbox' }).catch((e) => logLine(e.message, 'err'));
  });
  $('btn-loc-lib-open').addEventListener('click', () => {
    api('/api/open', { target: 'stickers' }).catch((e) => logLine(e.message, 'err'));
  });
  $('btn-loc-lib-orphan').addEventListener('click', () => localPurge('orphan', '清理孤儿文件'));
  $('btn-loc-lib-imported').addEventListener('click', () => localPurge('imported', '删除已导入原图'));
}

async function main() {
  bindUI();
  bindEvents();
  syncModeUI();
  await refreshState();
  await loadMarkets();
  await loadList();
  logLine('就绪。默认抓「我的表情包」，首次使用请点右上角「登录/检测」扫码登录（抖音、小红书各一次）。');
}

main();
