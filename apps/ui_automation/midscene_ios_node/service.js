/**
 * midscene-ios Node.js RPC Service
 *
 * 作为 TestHub Python 侧 MidsceneIOSEngine 的后端，通过 JSON-RPC 2.0 over HTTP 通信。
 *
 * 为什么需要它：Python 包 `midscene` 最新版就是 0.1.5，只有 agent_android / agent_web，
 * 没有 iOS；官方的 iOS 能力只在 JS SDK `@midscene/ios` 里（底层同样是 WebDriverAgent）。
 * 所以这里用 Node 起一个薄服务把 iOS 能力暴露出来，Python 侧通过 HTTP 调用。
 *
 * 用法：
 *   node service.js --port=39257
 * 环境变量（由 Python 侧从 AIModelConfig(role='midscene_vision') 注入）：
 *   MIDSCENE_MODEL_BASE_URL / MIDSCENE_MODEL_API_KEY
 *   MIDSCENE_MODEL_NAME     / MIDSCENE_MODEL_FAMILY
 */

'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

let IOSAgent = null;
let IOSDevice = null;
try {
  const mod = require('@midscene/ios');
  IOSAgent = mod.IOSAgent;
  IOSDevice = mod.IOSDevice;
} catch (e) {
  console.error('failed to require @midscene/ios: ' + (e && e.message));
}

const sessions = new Map();
let sessionCounter = 0;

const LOG_FILE = path.join(process.cwd(), 'midscene_ios_service.log');
const LOG_MAX_BYTES = 5 * 1024 * 1024;

function rotateLogIfNeeded() {
  try {
    if (fs.statSync(LOG_FILE).size > LOG_MAX_BYTES) {
      fs.renameSync(LOG_FILE, LOG_FILE + '.1');
    }
  } catch (_) {
    // ignore
  }
}

function log(message) {
  const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
  const line = '[' + ts + '] ' + message + '\n';
  try {
    rotateLogIfNeeded();
    fs.appendFileSync(LOG_FILE, line, 'utf-8');
  } catch (_) {
    // ignore
  }
  console.log(line.trim());
}

function parsePort() {
  const arg = (process.argv || []).find((x) => String(x).startsWith('--port='));
  if (arg) {
    const n = parseInt(arg.split('=')[1], 10);
    if (n > 0) return n;
  }
  return 0;
}

function nextSessionId() {
  sessionCounter += 1;
  return 'ios_session_' + Date.now() + '_' + sessionCounter;
}

function getSession(sessionId) {
  const s = sessions.get(sessionId);
  if (!s) throw new Error('Session not found: ' + sessionId);
  return s;
}

/**
 * 统一调用 agent 方法。v1.x 的签名：
 *   aiAct(prompt) / aiTap(locate) / aiInput(value, locate)
 *   aiQuery(shape) / aiAssert(prompt) / aiWaitFor(prompt)
 */
async function invoke(sessionId, method, params) {
  const s = getSession(sessionId);
  const agent = s.agent;
  const prompt = params.prompt || '';
  const value = params.value || '';
  const locate = params.locate || '';
  const timeoutMs = parseInt(params.timeoutMs || 0, 10) || 0;

  const fn = agent[method];
  if (typeof fn !== 'function') {
    throw new Error(method + ' is not supported by this agent');
  }

  switch (method) {
    case 'aiAct':
      return await fn.call(agent, prompt);
    case 'aiTap':
      return await fn.call(agent, locate || prompt);
    case 'aiInput':
      return await fn.call(agent, value, locate || prompt || undefined);
    case 'aiQuery':
      return await fn.call(agent, prompt);
    case 'aiAssert':
      return await fn.call(agent, prompt);
    case 'aiWaitFor':
      return await invokeWaitFor(agent, fn, prompt, timeoutMs);
    default:
      throw new Error('unhandled method: ' + method);
  }
}

// aiWaitFor 的挂起时间由条件何时成立决定，必须有超时兜底，否则页面一直不出现
// 目标元素时会长时间挂住（Python 侧一定传 timeoutMs，这里再兜一层默认值）。
const DEFAULT_WAIT_FOR_TIMEOUT_MS = 15000;

/**
 * 调用原生 aiWaitFor，并把超时限制在其内部生效。
 * 不同版本的 SDK 对超时的接受方式不一样（有的支持第二参数，
 * 有的只认 opts.timeout），所以这里"探测 + 兜底"两层：
 *   1) 有原生 timeout 参数就传；
 *   2) 再套一个外部 Promise.race 保证一定不会无限等。
 */
async function invokeWaitFor(agent, fn, prompt, timeoutMs) {
  const limit = timeoutMs > 0 ? timeoutMs : DEFAULT_WAIT_FOR_TIMEOUT_MS;
  let timer = null;
  try {
    return await Promise.race([
      fn.call(agent, prompt, { timeout: limit }),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(
            '等待超时（' + limit + 'ms）：元素/条件未出现 —— ' + prompt)),
          limit
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * 取屏幕逻辑尺寸（点）。
 *
 * 不同版本 @midscene/ios 暴露的方法名不一样，按能力探测依次尝试；
 * 全都拿不到时回退到常见 iPhone 的逻辑分辨率（390x844），
 * 保证 back 手势在极端情况下仍可用，而不是直接抛错。
 */
async function viewportSize(device) {
  const candidates = ['size', 'getScreenSize'];
  for (const name of candidates) {
    if (typeof device[name] === 'function') {
      try {
        const r = await device[name].call(device);
        if (r && r.width && r.height) {
          return { width: Number(r.width), height: Number(r.height) };
        }
      } catch (e) {
        log('viewportSize via ' + name + ' failed: ' + (e && e.message));
      }
    }
  }
  log('viewportSize: 回退默认 390x844');
  return { width: 390, height: 844 };
}

/**
 * 取屏幕**逻辑**尺寸（点）—— 只认真实设备报告，**不回退默认值**。
 *
 * 与 viewportSize 的区别（为什么不能直接复用）：
 *   viewportSize 拿不到时会回退 390x844，这对 back 手势是无害兜底；
 *   但 aiLocate 用它来判断"坐标是否落屏内 / 反推 dpr"，
 *   一旦用错机型尺寸去比对，会把正确坐标误判成越界、或反推出错误的 dpr。
 *   所以这里宁可不回退（返回 null），让调用方退化为"不换算、原样返回"。
 */
async function deviceLogicalSize(session) {
  const device = session.device;
  const candidates = ['size', 'getScreenSize'];
  for (const name of candidates) {
    if (typeof device[name] === 'function') {
      try {
        const r = await device[name].call(device);
        if (r && Number(r.width) > 0 && Number(r.height) > 0) {
          return { width: Number(r.width), height: Number(r.height) };
        }
      } catch (e) {
        log('deviceLogicalSize via ' + name + ' failed: ' + (e && e.message));
      }
    }
  }
  // 兜底：WDA 的窗口尺寸（逻辑点）
  try {
    const res = await device.runWdaRequest('GET', '/window/size');
    const v = (res && res.value) || {};
    if (Number(v.width) > 0 && Number(v.height) > 0) {
      return { width: Number(v.width), height: Number(v.height) };
    }
  } catch (e) {
    log('deviceLogicalSize via /window/size failed: ' + (e && e.message));
  }
  return null;
}

/**
 * 解析 WDA /source 返回的 XCUIElement 树，抽出带坐标的节点列表。
 *
 * 为什么需要它（2026-09-21）：
 *   平台的「AI 点击」本质是**让视觉模型看图猜坐标** —— 在底部这种 79px 一个的
 *   密集图标条上，猜偏几十 px 就会点到隔壁（实测「万年历」被点到「黄历」，
 *   二者中心仅差 78px），而且**点错了也不报错**。
 *   WDA 的 /source 里有完整的 accessibility 树，每个元素都带精确 x/y/width/height，
 *   按 name/label 查一次就能拿到准确坐标 —— 这才是真正的元素定位。
 *
 * 只处理自闭合/开始标签，够用且不引入 XML 依赖。
 */
function parseElementTree(xml) {
  const nodes = [];
  const re = /<XCUIElementType([A-Za-z]+)([^>]*?)\/?>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const attrs = {};
    const ar = /([A-Za-z_-]+)="([^"]*)"/g;
    let a;
    while ((a = ar.exec(m[2])) !== null) attrs[a[1]] = a[2];
    const x = parseInt(attrs.x, 10);
    const y = parseInt(attrs.y, 10);
    const w = parseInt(attrs.width, 10);
    const h = parseInt(attrs.height, 10);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    nodes.push({
      type: 'XCUIElementType' + m[1],
      name: attrs.name || '',
      label: attrs.label || '',
      value: attrs.value || '',
      // WDA 把 &quot; &amp; #10; 等做了转义，这里还原，便于和用户输入比对
      x, y, width: w || 0, height: h || 0,
      index: parseInt(attrs.index, 10),
    });
  }
  return nodes;
}

/** 反转义 XML 实体（&#10; 等），并去掉首尾空白 */
function decodeText(s) {
  return String(s || '')
    .replace(/&#(\d+);/g, (_, d) => String.fromCharCode(parseInt(d, 10)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .trim();
}

/**
 * 从一句"人类描述"里提取可能的元素文案候选。
 *
 * 为什么需要（2026-09-21 实战教训）：
 *   用户填「底部导航栏从左数第1个「万年历」图标」这类描述 —— 人看得懂，
 *   但元素树里那个按钮的 name **就是「万年历」**，整句去匹配必然找不到。
 *   所以先把描述里"最像标签文字"的片段抠出来，逐个拿去试。
 *
 * 提取优先级：
 *   1. 引号/括号里的内容：「万年历」 '万年历' “万年历” 【万年历】
 *   2. 去掉方位/动作/控件类型等修饰词后的主干
 *   3. 原句本身（兜底）
 *
 * @returns {String[]} 去重后的候选，按可信度从高到低
 */
function extractTextCandidates(raw) {
  const s = String(raw || '').trim();
  if (!s) return [];

  const cands = [];

  // 1) 各种引号/括号里的内容（中英文都要覆盖）
  const quoteRe = /[「『【\[\(（"“'‘]([^」』】\]\)）"”'’]{1,40})[」』】\]\)）"”'’]/g;
  let m;
  while ((m = quoteRe.exec(s)) !== null) {
    const t = decodeText(m[1]).trim();
    if (t) cands.push(t);
  }

  // 2) 去掉方位/动作/控件类型等修饰词，得到主干。
  //    例：「底部导航栏从左数第1个万年历图标」-> 「万年历」
  let core = s;
  // 去掉引号本身（保留其中文字）
  core = core.replace(/[「『【\[\(（"“'‘」』】\]\)）"”'’]/g, '');
  // 去掉常见修饰词/方位词/动作词/控件类型
  const noise = [
    '点击', '点一下', '按下', '轻触', '触摸',
    '底部', '顶部', '上方', '下方', '左侧', '右侧', '左边', '右边',
    '左上角', '右上角', '左下角', '右下角', '屏幕', '页面', '界面上',
    '导航栏', '标签栏', '标签页', '选项卡', 'tab', 'Tab', 'TAB',
    '图标', '按钮', '栏', '位置', '区域', '入口',
    '从左数第', '从右数第', '从左往右第', '从右往左第',
    '第一个', '第二个', '第三个', '第四个', '第五个',
    '第1个', '第2个', '第3个', '第4个', '第5个',
    '的', '个',
  ];
  noise.forEach((w) => { core = core.split(w).join(' '); });
  // 去掉纯数字/序号残留
  core = core.replace(/[0-9０-９]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (core) {
    // 主干可能还是多个词，按空格拆开逐一作为候选
    core.split(' ').forEach((t) => {
      const v = t.trim();
      if (v.length >= 1 && v.length <= 40) cands.push(v);
    });
  }

  // 3) 原句兜底（长描述匹配不到也没关系，findElementByText 会逐级降级）
  cands.push(s);

  // 去重 + 保序；太短的（1 个字符）和纯符号的丢掉，避免误命中
  const seen = new Set();
  const out = [];
  cands.forEach((t) => {
    const v = String(t || '').trim();
    if (!v || v.length > 60) return;
    if (!/[\u4e00-\u9fa5A-Za-z0-9]/.test(v)) return;
    if (seen.has(v)) return;
    seen.add(v);
    out.push(v);
  });
  // 短候选（更像真实标签）排前面
  out.sort((a, b) => a.length - b.length);
  return out;
}

/**
 * 从节点列表里按文本找目标元素，返回命中项（含中心坐标）。
 *
 * 匹配优先级（从强到弱）：
 *   1. 完全等于 text（name 或 label）
 *   2. 去掉空白后完全相等
 *   3. 包含 text（取面积最小的那个 —— 更可能是真正可点的叶子元素，
 *      而不是把整屏包住的应用根节点）
 *
 * @param {Array}  nodes      parseElementTree 的结果
 * @param {String} text       要查找的文案
 * @param {Object} opts       { index } 同名元素取第几个（默认 0，按 y 再按 x 排序）
 */
function findElementByText(nodes, text, opts) {
  const want = decodeText(text);
  if (!want) return { ok: false, reason: 'empty_text' };
  const index = Math.max(0, parseInt((opts || {}).index || 0, 10) || 0);

  const cands = nodes.filter((n) => {
    const name = decodeText(n.name);
    const label = decodeText(n.label);
    return n.width > 0 && n.height > 0 && (name || label);
  });

  const norm = (s) => decodeText(s).replace(/\s+/g, '');
  const target = norm(want);

  // ⚠️ "包含匹配"的多重收紧（2026-09-21 两次实测误命中后定型）：
  //   ① 键盘按键 name 是单个字母（q/w/e…）→ 短词包含匹配会误命中键盘
  //      ⇒ 目标文本长度 < 3 不启用包含匹配；
  //   ② 即便 >= 3 字，若"包含"命中了多个元素，**大概率是误命中**
  //      （实测「写日记」被命中到键盘区 (71,618)，属于歪打正着）。
  //      ⇒ 包含匹配**只在唯一命中时采用**；多个候选一律视为不可靠，宁可回退视觉模型。
  //   ③ 键盘/输入法元素整体排除出"包含匹配"候选。
  const allowContains = want.length >= 3;
  const isKeyboardish = (n) => {
    const t = n.type || '';
    if (t === 'XCUIElementTypeKey' || t === 'XCUIElementTypeKeyboard') return true;
    // 输入法候选栏 Cell（label 形如「跑步, 跑车的跑」）
    if (t === 'XCUIElementTypeCell' && /[,，]/.test(n.label || '')) return true;
    const nm = decodeText(n.name);
    // 单个 ascii 字母/数字的按键
    if (/^[A-Za-z0-9]$/.test(nm)) return true;
    return false;
  };

  // 命中分组：exact(1) 优先于 contains(3)
  const groups = [[], [], []];
  // ⚠️ 容器类元素绝不能当点击目标（实测坑）：
  //   「万年历」既是 App 根节点（Application, 0,0,393x852）也是底部 Button，
  //   只按 y 排序会把**全屏根节点**排在前面 → 点到屏幕正中 (197,426)。
  //   容器类先剔除；若某文本只有容器命中，再退回用它们。
  const CONTAINER_TYPES = [
    'XCUIElementTypeApplication', 'XCUIElementTypeWindow',
    'XCUIElementTypeOther', 'XCUIElementTypeScrollView',
    'XCUIElementTypeTable', 'XCUIElementTypeCollectionView',
    'XCUIElementTypeNavigationBar', 'XCUIElementTypeTabBar',
  ];
  const isContainer = (n) => CONTAINER_TYPES.includes(n.type);

  // ⚠️⚠️ **几何兜底：类型白名单挡不住的"伪叶子全屏容器"（2026-09-22 生产实测）**
  //
  // 坑的表现：第 1 步「点击底部万年历 tab」**精确定位命中后点到 (197,426)**，
  // 而 393/2=196.5、852/2=426 —— 这是**整屏中心**，不是底部 tab（正确值 (40,794)）。
  // 日志只说"精确定位命中"，看起来像正常命中，极难发现点错了。
  //
  // 根因：广告页/某些页面里存在**类型不在白名单、但尺寸≈全屏**的元素
  // （如 `XCUIElementTypeImage`/`Button` 撑满全屏），
  // 类型白名单拦不住 → 被当"叶子"选中 → 点在屏幕正中。
  //
  // 判据（**尺寸维度**，比类型更可靠）：面积 ≥ 屏 90% 或宽 ≥ 屏 95% 或高 ≥ 屏 95%
  // 的元素**不可能是"某个可点的具体控件"**，一律按容器排除。
  // 取不到屏幕尺寸时退化为原逻辑（只靠类型），不误杀。
  const screenW = Number(opts && opts.screenWidth) || 0;
  const screenH = Number(opts && opts.screenHeight) || 0;
  const isFullScreenish = (n) => {
    if (!screenW || !screenH || !n.width || !n.height) return false;
    const areaRatio = (n.width * n.height) / (screenW * screenH);
    return areaRatio >= 0.9 || n.width >= screenW * 0.95 || n.height >= screenH * 0.95;
  };
  cands.forEach((n) => {
    const name = decodeText(n.name);
    const label = decodeText(n.label);
    if (name === want || label === want) groups[0].push(n);
    else if (norm(name) === target || norm(label) === target) groups[1].push(n);
    else if (allowContains && !isKeyboardish(n)
             && ((name && name.includes(want)) || (label && label.includes(want)))) {
      groups[2].push(n);
    }
  });

  let hits = [];
  let matchedBy = '';
  for (let i = 0; i < groups.length; i++) {
    if (groups[i].length) {
      // ⚠️ "包含匹配"只在**唯一命中**时采用：多个候选说明文案太模糊
      //    （实测「写日记」误命中了键盘区），宁可判定未命中让调用方回退视觉模型，
      //    也不要赌一个可能错误的坐标。
      if (i === 2 && groups[2].length > 1) {
        return {
          ok: false,
          reason: 'ambiguous_contains',
          text: want,
          ambiguousCount: groups[2].length,
          candidates: groups[2].slice(0, 8).map((n) => ({
            type: n.type, name: decodeText(n.name),
            center: [Math.round(n.x + n.width / 2), Math.round(n.y + n.height / 2)],
          })),
        };
      }
      hits = groups[i];
      matchedBy = ['exact', 'exact_trim', 'contains'][i];
      break;
    }
  }
  if (!hits.length) {
    return {
      ok: false,
      reason: 'not_found',
      text: want,
      // 回传前 30 个可见文案，方便前端/日志排查"到底页面上有哪些字"
      available: cands.slice(0, 30).map((n) => decodeText(n.name) || decodeText(n.label)),
    };
  }

  // 先剔除容器类（类型白名单 + 全屏几何兜底），再按面积从小到大
  // —— 保证选中的是**真正的叶子可点元素**。
  // ⚠️ 若剔除后一个都不剩，说明该文本**只有容器命中**：这属于"无可靠可点目标"，
  //    必须返回未命中让调用方回退视觉模型，**绝不能退回用容器**
  //    （退回=点在屏幕正中，正是 (197,426) 那个坑）。
  const leaves = hits.filter((n) => !isContainer(n) && !isFullScreenish(n));
  if (leaves.length) {
    hits = leaves;
  } else {
    return {
      ok: false,
      reason: 'only_container_match',
      text: want,
      candidates: hits.slice(0, 5).map((n) => ({
        type: n.type, name: decodeText(n.name),
        size: [n.width, n.height],
        center: [Math.round(n.x + n.width / 2), Math.round(n.y + n.height / 2)],
      })),
    };
  }

  // 页面同名元素很常见（实测底部 tab「黄历」与顶部按钮「黄历」同名）。
  // 支持用 region 缩小范围，避免选错那一个：
  //   bottom/top   —— 取屏幕下/上半区
  //   lowest/highest —— 直接取 y 最大/最小的那个（比 region 更宽容）
  const region = String((opts || {}).region || '').toLowerCase();
  if (region && hits.length > 1) {
    const maxY = Math.max(...hits.map((n) => n.y + n.height));
    if (region === 'bottom') hits = hits.filter((n) => n.y + n.height / 2 > maxY / 2);
    else if (region === 'top') hits = hits.filter((n) => n.y + n.height / 2 <= maxY / 2);
    if (!hits.length) return { ok: false, reason: 'region_no_match', text: want, region };
  }

  // 排序：默认按面积小的优先（叶子元素），同面积再从上到下、从左到右。
  // region=lowest/highest 时改为按 y 排，直接取最下/最上那个。
  if (region === 'lowest') {
    hits = hits.slice().sort((a, b) => (b.y + b.height) - (a.y + a.height));
  } else if (region === 'highest') {
    hits = hits.slice().sort((a, b) => a.y - b.y);
  } else {
    hits = hits.slice().sort((a, b) =>
      (a.width * a.height) - (b.width * b.height) || (a.y - b.y) || (a.x - b.x));
  }

  const picked = hits[Math.min(index, hits.length - 1)];
  const cx = Math.round(picked.x + picked.width / 2);
  const cy = Math.round(picked.y + picked.height / 2);
  // ⚠️⚠️ 坐标语义统一约定（2026-09-22 定型，别再改回去）：
  //   1. **WDA 元素树（/source）里的 x/y/width/height 本来就是【逻辑点】**，
  //      所以这里**刻意不除以 dpr**（设备逻辑尺寸 ≈ 元素树坐标量级，实测 393x852 一致）。
  //   2. 但对外一律**多返回一个 `dpr` 字段**（元素树路径恒为 1），
  //      让 Python 侧能用 `center / dpr = 逻辑点` 这一条**统一公式**处理所有来源。
  //   3. 这样「落屏护栏」就能**同时挡住两类错误**：
  //      - dpr 漏乘（把逻辑点当物理像素）→ center/dpr 偏小；
  //      - dpr 漏除（把物理像素当逻辑点）→ center/dpr 越界（aiLocate 那种）。
  //   为什么需要护栏：实测生产用例 id=73 第 1 步在「元素树显示像广告页」时
  //   回退到视觉路径，而 aiLocate 的 dpr 偶发为 1 → 采到物理像素 → 固化点空。
  return {
    ok: true,
    matchedBy,
    matchCount: hits.length,
    candidates: hits.slice(0, 5).map((n) => ({
      type: n.type, name: decodeText(n.name),
      center: [Math.round(n.x + n.width / 2), Math.round(n.y + n.height / 2)],
      size: [n.width, n.height],
    })),
    node: picked,
    center: [cx, cy],
    dpr: 1,
    rect: [picked.x, picked.y, picked.width, picked.height],
  };
}

/** 按坐标滑动（点）。同样做多版本兼容探测。 */
async function swipePoint(device, fromX, fromY, toX, toY, duration) {
  if (typeof device.swipeCoordinates === 'function') {
    await device.swipeCoordinates(fromX, fromY, toX, toY, duration);
  } else if (typeof device.swipe === 'function') {
    await device.swipe(fromX, fromY, toX, toY, duration);
  } else if (typeof device.swipePoint === 'function') {
    await device.swipePoint({ x: fromX, y: fromY }, { x: toX, y: toY }, duration);
  } else {
    throw new Error('当前 @midscene/ios 版本的 device 不支持坐标滑动，无法执行 back');
  }
}

const handlers = {
  async ping() {
    return { ok: true, sessions: sessions.size };
  },

  async createSession(params) {
    if (!IOSDevice || !IOSAgent) {
      throw new Error('@midscene/ios 未安装，请在服务目录执行 npm install');
    }
    const wdaHost = params.wdaHost || 'localhost';
    const wdaPort = parseInt(params.wdaPort || 8100, 10);
    const device = new IOSDevice({ wdaHost, wdaPort });
    const agent = new IOSAgent(device, {
      aiActionContext: params.aiActionContext || '',
    });
    log('connecting WDA ' + wdaHost + ':' + wdaPort + ' ...');
    await device.connect();
    const sessionId = nextSessionId();
    sessions.set(sessionId, { device, agent });
    log('session created: ' + sessionId);
    return { sessionId: sessionId, wdaHost, wdaPort };
  },

  async launch(params) {
    const s = getSession(params.sessionId);
    const uri = params.uri || '';
    if (!uri) throw new Error('launch 需要 uri（bundle id 或 URL）');
    log('launch: ' + uri);
    await s.device.launch(uri);
    return { ok: true };
  },

  async screenshot(params) {
    const s = getSession(params.sessionId);
    const base64 = await s.device.screenshotBase64();
    return { base64: base64 };
  },

  /**
   * 返回屏幕**逻辑**尺寸（点）。
   *
   * 用途：Python 侧用「逻辑点坐标是否落在 [0,W]x[0,H]」来丢弃明显错误的
   * 采样坐标（2026-09-22 实测把「万年历」采成 (590,1280)，超出 393x852，
   * 固化下来回放必然点空）。取不到时返回 ok:false，绝不返回默认值 ——
   * 拿错机型尺寸做越界判断反而会误杀正确坐标。
   */
  async screenSize(params) {
    const s = getSession(params.sessionId);
    const size = await deviceLogicalSize(s);
    if (!size) return { ok: false, error: 'device screen size unavailable' };
    return { ok: true, width: size.width, height: size.height };
  },

  async aiAct(params) {
    await invoke(params.sessionId, 'aiAct', params);
    return { ok: true };
  },
  async aiTap(params) {
    await invoke(params.sessionId, 'aiTap', params);
    return { ok: true };
  },
  async aiInput(params) {
    await invoke(params.sessionId, 'aiInput', params);
    return { ok: true };
  },
  async aiQuery(params) {
    const result = await invoke(params.sessionId, 'aiQuery', params);
    return { result: result };
  },

  // ---- 真正的元素定位：查 accessibility 树按文本找坐标，不走视觉模型 ----
  // 与 aiTap 的区别：
  //   aiTap      = 让视觉模型**看图猜坐标**（密集图标条上会猜偏，且点错不报错）
  //   findByText = 读 WDA /source 的元素树，按 name/label **精确匹配**取坐标
  // 面向用户的开关是步骤上的 `locate_by_text`。
  async findByText(params) {
    const s = getSession(params.sessionId);
    const rawText = params.text || '';
    if (!rawText) throw new Error('findByText 需要 text');
    const res = await s.device.runWdaRequest('GET', '/source');
    const xml = (res && res.value) || '';
    const nodes = parseElementTree(xml);

    // 多候选逐个尝试：用户写的常是"描述"（底部导航栏从左数第1个「万年历」图标），
    // 而元素树里按钮的 name 就是「万年历」。先把描述拆成候选文案，命中最靠前的就返回。
    // params.exactText=true 时只用原文（调用方明确知道自己给的就是元素文本）。
    const candidates = params.exactText
      ? [String(rawText).trim()]
      : extractTextCandidates(rawText);

    // 描述里带方位词时**自动推断 region**，解决同名元素（如顶部与底部都有「黄历」）。
    // 用户没显式指定 region 时才有意义。
    let region = String(params.region || '').toLowerCase();
    if (!region) {
      const d = String(rawText);
      if (/底部|下方|下边|下端|bottom|导航栏|标签栏|tab\s*栏|最下/.test(d)) region = 'lowest';
      else if (/顶部|上方|上边|上端|top|最上|下拉/.test(d)) region = 'highest';
    }

    // 取屏幕逻辑尺寸传给匹配器：用于"全屏几何兜底"排除伪叶子容器
    // （实测广告页上有尺寸≈全屏的元素，类型白名单拦不住 → 点在屏幕正中 (197,426)）。
    let screenW = 0;
    let screenH = 0;
    try {
      const size = await deviceLogicalSize(s);
      if (size) { screenW = size.width; screenH = size.height; }
    } catch (e) {
      log('findByText: 取屏幕尺寸失败（几何兜底降级）: ' + (e && e.message));
    }

    let found = null;
    let usedText = '';
    const tried = [];
    for (const cand of candidates) {
      const r = findElementByText(nodes, cand, {
        index: params.index || 0, region,
        screenWidth: screenW, screenHeight: screenH,
      });
      tried.push(cand);
      if (r.ok) { found = r; usedText = cand; break; }
    }

    // 全都没命中时，退回最后一次的结果（用于给出"页面上有什么文案"的提示）
    const last = found || findElementByText(nodes, candidates[candidates.length - 1] || rawText, {});

    log('findByText: ' + JSON.stringify({
      text: rawText, usedText, ok: !!(found && found.ok),
      matchedBy: found && found.matchedBy, nodeCount: nodes.length,
      center: found && found.center, tried: tried.slice(0, 8),
      available: (found && found.ok) ? undefined : (last.available || []).slice(0, 10),
    }));

    if (!found || !found.ok) {
      const hint = '（页面上可见的文案有: '
        + ((found || last).available || []).slice(0, 12).join(' / ') + '）';
      throw new Error(
        '元素定位失败：按「' + rawText + '」在页面元素树里没找到可点元素\n'
        + '尝试过的候选文案: ' + tried.slice(0, 8).join(' / ') + '\n' + hint
      );
    }
    found.usedText = usedText;
    return found;
  },

  // 导出当前页面的完整可访问性树（排查用）：
  // 看这个 app 到底把哪些元素/文案暴露给了 WDA —— 精确定位失败时靠它定位原因。
  async dumpTree(params) {
    const s = getSession(params.sessionId);
    const res = await s.device.runWdaRequest('GET', '/source');
    const xml = (res && res.value) || '';
    const nodes = parseElementTree(xml);
    const onlyNamed = params.onlyNamed !== false;
    const list = nodes
      .filter((n) => !onlyNamed || n.name || n.label)
      .filter((n) => n.width > 0 && n.height > 0)
      .map((n) => ({
        type: n.type.replace('XCUIElementType', ''),
        name: decodeText(n.name),
        label: decodeText(n.label),
        value: decodeText(n.value),
        rect: [n.x, n.y, n.width, n.height],
        center: [Math.round(n.x + n.width / 2), Math.round(n.y + n.height / 2)],
      }));
    log('dumpTree: total=' + nodes.length + ' returned=' + list.length);
    return { total: nodes.length, count: list.length, nodes: list };
  },

  async tapByText(params) {
    const found = await handlers.findByText(params);
    const s = getSession(params.sessionId);
    log('tapByText: ' + params.text + ' -> ' + found.center.join(','));
    await s.device.tap(found.center[0], found.center[1]);
    return {
      ok: true, text: params.text, center: found.center,
      rect: found.rect, matchedBy: found.matchedBy,
    };
  },

  /**
   * 只定位、不操作 —— 返回目标元素的坐标（2026-09-22 新增）。
   *
   * 为什么需要它（**这是"首次探索 → 自动固化"能成立的关键**）：
   *   `aiTap` 走视觉模型时**返回 void**，Python 侧拿不到"点到哪了"，
   *   于是 `steps_completed[i].location` 为空 → `_freeze_case_steps`
   *   判定"有步骤没采到坐标"→ 整体不固化 → 下次还要重新烧一遍模型。
   *   `aiLocate` 是同一套视觉定位能力的"纯查询"入口，返回坐标但不点击。
   *
   * ⚠️ 这是**真会调模型**的（和 aiTap 一样走视觉定位），所以：
   *   - 只在"首次探索"路径调用，固化后的回放路径绝不调用；
   *   - 调用失败**不抛异常**，返回 ok:false 让调用方继续原流程，
   *     绝不能因为"采坐标失败"把用例本身跑挂了。
   *
   * ⚠️⚠️ **返回结构必须照 SDK 源码抄，别凭直觉**（我在这里错过一次）：
   *   `agent.aiLocate()` 的实现在 @midscene/ios 打包产物里是：
   *     return { rect, center: element?.center, dpr }
   *   **`center` 在【顶层】**，不是 `res.element.center`！
   *   我第一版按 `res.element.center` 取 → 永远拿不到 → 白调一次模型。
   *
   *   center 可能为空（模型没定位到），此时 center === undefined；
   *   rect 在缺 rect 时 SDK 会自动兜一个 8x8 的小框（用 center 推出来的），
   *   所以 **不能用 rect 判断"定位成功"，只能看 center**。
   */
  async aiLocate(params) {
    const s = getSession(params.sessionId);
    const text = params.prompt || params.text || '';
    if (!text) {
      return { ok: false, error: 'aiLocate 需要 prompt' };
    }
    const agent = s.agent;
    /**
     * ⭐⭐ **第一优先：元素树（确定性、零模型、零成本）**
     *
     * 2026-09-22 生产实测（用例 id=73）暴露的问题：
     *   第 1 步「万年历 tab」的元素树定位在**广告落地页上失败**（找不到同名元素）
     *   → 回退视觉路径 → `agent.aiTap()` 真把广告关掉、App 露出真正的主界面。
     *   此时固化采样若只信 `aiLocate`，模型面对的是「已经切好的新页面」，
     *   而且 dpr 偶发为 1 → **采到物理像素 (590,1280) → 固化必然点空**。
     *
     * 元素树能命中时，拿到的就是该元素**当下**的精确逻辑点，既稳又免费。
     * 节点里 `name`/`label` 与 `findByText` 同源，两个方法结果天然一致。
     */
    let treeHit = null;
    for (const cand of extractTextCandidates(text)) {
      try {
        const r = await handlers.findByText(Object.assign({}, params, {
          sessionId: s && s.id ? s.id : params.sessionId,
          text: cand,
          region: params.region || '',
        }));
        if (r && r.ok && Array.isArray(r.center) && r.center.length >= 2) {
          treeHit = Object.assign({}, r, { usedText: cand });
          break;
        }
      } catch (e) {
        // 元素树没命中很正常（自定义绘制/弹窗元素树里没有）→ 继续走视觉路径
      }
    }
    if (treeHit) {
      const out = {
        ok: true,
        center: treeHit.center,
        rawCenter: treeHit.center,
        dpr: 1,
        rect: treeHit.rect,
        target: text,
        usedText: treeHit.usedText,
        onScreen: true,
        source: 'tree',
      };
      log('aiLocate: ' + text + ' [元素树命中「' + treeHit.usedText + '」] -> 逻辑点 '
        + out.center.join(',') + '（零模型）');
      return out;
    }

    /**
     * ⚠️⚠️ **坐标语义必须与 aiTap 完全一致，否则固化出来的坐标是错的。**
     *
     * 2026-09-22 生产实测（真机 ios-14）踩到的坑：
     *   步骤 prompt 是**整句描述**「点击屏幕底部导航栏中，文字为"万年历"的图标」。
     *   - `aiTap` 走的是 midscene SDK 内部：先视觉定位、再 `device.tap()`，
     *     而 `device.tap()` 内部会做 dpr 换算，所以 **aiTap 点到的是逻辑点**；
     *   - 本方法直接用 agent.aiLocate 的返回值，SDK 给的是 **物理像素**，
     *     必须自己除以 dpr 才是逻辑点。
     *
     * 于是「aiTap 点击 + aiLocate 采样」两件事在**同一屏同一目标**上得到两个
     * 不同数值：aiTap 点 (197,426)（逻辑点，正确），aiLocate 采到 (590,1280)
     * （物理像素 ×3），固化回放时按 590,1280 点 → 必然点空/点错。
     * 之前的 dpr 换算本意是对的，但**整句描述会让模型在"全屏范围内"定位**，
     * 返回的 rect 是整屏、dpr 兜底成 1，换算也就失效了。
     *
     * 所以这里做两件事：
     *   ① **文本候选逐个定位**：与 findByText 同一套 `extractTextCandidates`，
     *      先拿「万年历」这种纯文案去定位，避免整句描述导致定位范围过宽；
     *      优先返回坐标最小的候选（在屏幕内、面积小 = 真正那个控件）。
     *   ② **候选全部落到屏幕外时，按逻辑尺寸裁剪**：用 WDA 的逻辑尺寸
     *      `/ (rect.width / screenWidth)` 反推 dpr，而不是盲信 res.dpr。
     */
    const candidates = extractTextCandidates(text);
    if (!candidates.length) candidates.push(text);

    let screenW = 0;
    let screenH = 0;
    try {
      const size = await deviceLogicalSize(s);
      screenW = size.width;
      screenH = size.height;
    } catch (e) {
      // 取不到逻辑尺寸不阻断，下面的换算/裁剪会退化为"原样返回"
    }

    let best = null;
    const tried = [];
    for (const cand of candidates) {
      let res = null;
      try {
        res = await agent.aiLocate(cand) || {};
      } catch (e) {
        const msg = (e && e.message) ? e.message : String(e);
        tried.push(cand + '(失败:' + msg.slice(0, 60) + ')');
        continue;
      }
      let center = res.center;
      if (!center && res.element) center = res.element.center;
      if (!Array.isArray(center) || center.length < 2) {
        // rect 兜底（注意 SDK 会造 8x8 假框，所以放在最后，且必须验 center 缺失）
        const r = res.rect;
        if (r && Number.isFinite(r.left) && Number.isFinite(r.top)
            && Number.isFinite(r.width) && Number.isFinite(r.height)
            && !(r.width === 8 && r.height === 8)) {
          center = [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
        }
      }
      if (!Array.isArray(center) || center.length < 2) {
        tried.push(cand + '(无坐标)');
        continue;
      }

      let dpr = Number(res.dpr) > 0 ? Number(res.dpr) : 1;
      let rect = res.rect || null;
      let logical = [Math.round(center[0] / dpr), Math.round(center[1] / dpr)];

      // ---- dpr 可信度校验（2026-09-22 生产实测：dpr 会偶发为 1）----
      // 判据：**元素树（/source）用的是逻辑点**，同一个 App 的前台窗口尺寸
      // 必然 ≈ 元素树坐标系量级 ≈ 屏幕逻辑尺寸；而 **aiLocate 的 raw center 是
      // 物理像素**，量级 = 逻辑尺寸 × dpr（iPhone 上约 ×3）。
      // ⇒ 若 `rawCenter` 已经在屏幕逻辑尺寸内，那它其实**本来就是逻辑点**
      //   （模型偶尔会直接给逻辑点），此时再除 dpr 反而缩小 3 倍 → 强制 dpr=1。
      const rawX = Number(center[0]);
      const rawY = Number(center[1]);
      if (screenW > 0 && screenH > 0
          && rawX > 0 && rawY > 0 && rawX <= screenW && rawY <= screenH) {
        if (dpr !== 1) {
          log('aiLocate: rawCenter ' + center.join(',') + ' 已在逻辑尺寸 '
            + screenW + 'x' + screenH + ' 内 → dpr ' + dpr + ' 判为不可信，按 1 处理');
        }
        dpr = 1;
        logical = [Math.round(rawX), Math.round(rawY)];
      }

      // 换算后仍超出屏幕 → dpr 偏小（典型：整句描述定位到全屏、dpr 兜底成 1）。
      // 用"定位框宽度 / 屏幕宽度"反推真实倍率，这是最可靠的一手信息。
      if (screenW > 0 && screenH > 0
          && (logical[0] > screenW || logical[1] > screenH)) {
        const rw = (rect && Number(rect.width)) || 0;
        const rh = (rect && Number(rect.height)) || 0;
        let guess = 0;
        if (rw >= screenW) guess = rw / screenW;
        else if (rh >= screenH) guess = rh / screenH;
        if (guess > 1.001) {
          dpr = guess;
          logical = [Math.round(center[0] / dpr), Math.round(center[1] / dpr)];
        }
      }

      // 兜底反推：dpr=1 时若 rawCenter 明显是"整屏的物理像素"
      // （raw 远超逻辑屏但 raw/dprDefault 落在屏内），按 raw/screenW 推。
      if (screenW > 0 && screenH > 0 && dpr === 1
          && (logical[0] > screenW || logical[1] > screenH)) {
        const guess = Math.max(rawX / screenW, rawY / screenH);
        if (guess > 1.5) {
          dpr = guess;
          logical = [Math.round(rawX / dpr), Math.round(rawY / dpr)];
          log('aiLocate: 用 rawCenter/屏幕尺寸 反推 dpr=' + dpr.toFixed(3));
        }
      }

      const onScreen = screenW > 0 && screenH > 0
        ? (logical[0] >= 0 && logical[0] <= screenW
           && logical[1] >= 0 && logical[1] <= screenH)
        : false;
      const node = {
        ok: true,
        center: logical,
        rawCenter: [Math.round(center[0]), Math.round(center[1])],
        dpr: dpr,
        rect: rect,
        target: text,
        usedText: cand,
        onScreen: onScreen,
        area: (rect && Number(rect.width) && Number(rect.height))
          ? (rect.width / dpr) * (rect.height / dpr) : Number.MAX_SAFE_INTEGER,
      };
      tried.push(cand + '->' + logical.join(','));

      // 优先"落在屏幕内"且"定位框最小"的候选（＝真正的那个控件，而不是整屏容器）
      if (!best) best = node;
      else if (onScreen && !best.onScreen) best = node;
      else if (onScreen === best.onScreen && node.area < best.area) best = node;
      if (onScreen && node.area < 40000) break; // 已经找到足够小的可点控件，不必再试
    }

    if (!best) {
      log('aiLocate: 未拿到坐标, candidates=' + JSON.stringify(candidates.slice(0, 6))
        + ' tried=' + JSON.stringify(tried.slice(0, 6)));
      return { ok: false, error: 'locate returned no center' };
    }

    {
      const center = best.rawCenter;
      const dpr = best.dpr;
      // rect 同源，也要换算（left/top/width/height 一起除）
      let rectOut = null;
      const r = best.rect;
      if (r && Number.isFinite(r.left) && Number.isFinite(r.top)) {
        rectOut = {
          left: Math.round(r.left / dpr), top: Math.round(r.top / dpr),
          width: Math.round((r.width || 0) / dpr),
          height: Math.round((r.height || 0) / dpr),
        };
      }
      const out = {
        ok: true,
        center: best.center,
        rawCenter: center,
        dpr: dpr,
        rect: rectOut,
        target: text,
        usedText: best.usedText,
        onScreen: best.onScreen,
        source: 'vision',
      };
      log('aiLocate: ' + text + ' [用「' + best.usedText + '」] -> 逻辑点 '
        + out.center.join(',') + '（原 ' + out.rawCenter.join(',')
        + ' / dpr=' + dpr.toFixed(3) + ' / 屏 ' + screenW + 'x' + screenH + '）');
      return out;
    }

  },

  // ---- 纯坐标回放：不经过视觉模型 ----
  // 用例第一次跑通后会把每步的目标坐标固化下来，之后回放直接按坐标操作。
  // 这两个方法只碰 WDA，不触发任何 AI 调用。
  async tapPoint(params) {
    const s = getSession(params.sessionId);
    const x = parseInt(params.x, 10);
    const y = parseInt(params.y, 10);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      throw new Error('tapPoint 需要合法的 x/y');
    }
    log('tapPoint: ' + x + ',' + y);
    if (typeof s.device.tap === 'function') {
      await s.device.tap(x, y);
    } else if (typeof s.device.click === 'function') {
      await s.device.click(x, y);
    } else {
      throw new Error('当前 @midscene/ios 版本的 device 不支持坐标点击');
    }
    return { ok: true, x: x, y: y };
  },

  async inputText(params) {
    const s = getSession(params.sessionId);
    const text = params.text == null ? '' : String(params.text);
    log('inputText: ' + text);
    if (typeof s.device.inputText === 'function') {
      await s.device.inputText(text);
    } else if (typeof s.device.typeText === 'function') {
      await s.device.typeText(text);
    } else {
      throw new Error('当前 @midscene/ios 版本的 device 不支持文本输入');
    }
    return { ok: true };
  },
  async aiAssert(params) {
    await invoke(params.sessionId, 'aiAssert', params);
    return { pass: true };
  },
  async aiWaitFor(params) {
    await invoke(params.sessionId, 'aiWaitFor', params);
    return { ok: true };
  },

  // ---- 系统级动作：返回 / 回桌面 ----
  // iOS 没有 Android 那种全局「返回键」：
  //   - 「返回上一页」在 iOS 上是**从左边缘向右滑**的系统手势（UINavigationController
  //     的交互式返回），App 的返回按钮走的也是同一条链路，所以手势是最通用的等价物。
  //   - 「回桌面」用 WDA 的 home 能力（device.home() / pressHomeButton()）。
  // ⚠️ 不走视觉模型：这两个是确定性系统动作，用 AI 去"找返回按钮"既慢又不可靠
  //   （不同页面返回按钮位置/形态都不一样），直接用手势才对。
  async back(params) {
    const s = getSession(params.sessionId);
    const { width, height } = await viewportSize(s.device);
    // 从左边缘约 2% 处起滑，横向划过大半屏，纵向取屏幕中部。
    // 起点必须贴边（<= 5%），否则不会触发 iOS 的边缘返回手势。
    const fromX = Math.max(1, Math.round(width * 0.02));
    const toX = Math.round(width * 0.85);
    const y = Math.round(height * 0.5);
    log('back: swipe ' + fromX + ',' + y + ' -> ' + toX + ',' + y);
    await swipePoint(s.device, fromX, y, toX, y, 320);
    return { ok: true, from: [fromX, y], to: [toX, y] };
  },

  async home(params) {
    const s = getSession(params.sessionId);
    log('home: press home button');
    const d = s.device;
    if (typeof d.home === 'function') {
      await d.home();
    } else if (typeof d.pressHomeButton === 'function') {
      await d.pressHomeButton();
    } else {
      throw new Error('当前 @midscene/ios 版本的 device 不支持回到桌面');
    }
    return { ok: true };
  },

  async destroySession(params) {
    const s = sessions.get(params.sessionId);
    if (!s) return { ok: true };
    try {
      await s.device.destroy();
    } catch (e) {
      log('destroy error: ' + (e && e.message));
    }
    sessions.delete(params.sessionId);
    log('session destroyed: ' + params.sessionId);
    return { ok: true };
  },

  async shutdown() {
    setTimeout(() => process.exit(0), 200);
    return { ok: true };
  },
};

function sendJson(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && (req.url === '/health' || req.url === '/')) {
    sendJson(res, 200, { ok: true, sessions: sessions.size });
    return;
  }
  if (req.method !== 'POST' || req.url !== '/rpc') {
    sendJson(res, 404, { ok: false, error: 'not found' });
    return;
  }

  let raw = '';
  req.on('data', (chunk) => {
    raw += chunk;
    if (raw.length > 20 * 1024 * 1024) req.destroy();
  });
  req.on('end', async () => {
    let rpcRequest = {};
    try {
      rpcRequest = JSON.parse(raw || '{}');
    } catch (e) {
      sendJson(res, 400, { jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Invalid JSON' } });
      return;
    }
    const { id = null, method, params = {} } = rpcRequest;
    const handler = handlers[method];
    if (!handler) {
      sendJson(res, 200, { jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found: ' + method } });
      return;
    }
    try {
      const result = await handler(params);
      sendJson(res, 200, { jsonrpc: '2.0', id, result: result || {} });
    } catch (e) {
      log('rpc ' + method + ' error: ' + (e && e.message));
      sendJson(res, 200, { jsonrpc: '2.0', id, error: { code: -32000, message: (e && e.message) || String(e) } });
    }
  });
});

// iOS 上一步操作（尤其 aiAct 多步规划）可能很久，关掉默认超时
server.timeout = 0;
server.requestTimeout = 0;
server.headersTimeout = 0;

const port = parsePort();
server.listen(port, '127.0.0.1', () => {
  const actual = server.address().port;
  log('midscene-ios service listening on 127.0.0.1:' + actual);
  try {
    const infoFile = process.env.MIDSCENE_IOS_PORT_FILE || '/root/.midscene/ios/service.json';
    fs.mkdirSync(path.dirname(infoFile), { recursive: true });
    fs.writeFileSync(infoFile, JSON.stringify({ port: actual, pid: process.pid }), 'utf-8');
  } catch (e) {
    log('write port file failed: ' + (e && e.message));
  }
});
