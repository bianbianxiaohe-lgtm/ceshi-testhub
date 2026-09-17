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
      return await fn.call(agent, prompt);
    default:
      throw new Error('unhandled method: ' + method);
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
