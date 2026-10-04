// Qoder 加密推理请求的**本地签名桥**（我方代码；本文件不含任何第三方产物）。
//
// ## 它解决什么
//
// Qoder 的加密端点 `agent_chat_generation` 要求请求体经客户端内嵌 WASM 加密、
// 且 `Authorization` 是 WASM 生成的 `Bearer COSY.<载荷>.<签名>`（用普通
// `Bearer <token>` 覆盖必回 `403 Signature invalid`）。Python 侧没有 wasm 运行时，
// 因此本桥以**子进程**形式跑在 Node 上，做且仅做一件事：
//
//     明文请求体（我方 ask.py 构造）→ {url, headers, body}（WASM 加密 + 签名）
//
// ## 为什么明文由 Python 造、不由这里造
//
// 上游那份 wasm-bindgen 桥（`qoder-wasm.js`）里 `prepareInfer(ask)` 会**顺手**把
// ask 拼成明文请求体（`buildQoderInferPayload`）。我方把同一件事移植在
// `ask.py::build_infer_payload` 并有 pytest 覆盖 —— 若本桥去吃 `prepareInfer`，
// 请求形态就有**两份实现**（一份在盘上有测试、一份在外部依赖里没人管）。
// 所以本桥只调 wasm 的导出函数（`qodercontext_prepareInferRequest` 等），
// **payload 一律用调用方送来的那一份**。
//
// 由此得到一条外部依赖的**形状契约**（不是它的私有字段名单）：`QoderEncryptedInfer.create()`
// 的产物须暴露 `{g, context}`，且 `g.exports` 须含下列五个符号。不满足即 fail closed
// 并说明缺什么 —— 绝不退回"用 ask 让上游自己拼"（那会让外部依赖悄悄接管请求形态）。
//
// ## 用法与协议
//
//     node qoder_bridge.mjs --glue <dir>        # dir 内含 qoder-wasm.js + qoder-auth-wasm.wasm
//
// stdin/stdout 行分隔 JSON（一问一答、按 id 配对，stdout 只放协议帧）：
//
//     → {"id":1,"op":"info"}
//     ← {"id":1,"ok":true,"result":{"gluePath":"…","wasmPath":"…"}}
//     → {"id":2,"op":"prepare","accountKey":"qoder:…","user":{…},"machineId":"…",
//        "metadata":{…},"host":"https://api2.qoder.sh","payload":{…},"modelKey":"qfmodel","source":"system"}
//     ← {"id":2,"ok":true,"result":{"url":"…","headers":{…},"body":"…"}}
//     ← {"id":2,"ok":false,"error":"一句话原因"}

import { createInterface } from 'node:readline'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

/** 协议帧是 stdout 的唯一内容：被依赖方若 console.log，改道 stderr，不污染流。 */
console.log = (...args) => console.error(...args)

function arg(name) {
  const i = process.argv.indexOf(`--${name}`)
  return i >= 0 ? process.argv[i + 1] : undefined
}

const GLUE_DIR = arg('glue')
if (!GLUE_DIR) {
  process.stderr.write('qoder_bridge: 缺少 --glue <目录>\n')
  process.exit(2)
}
const GLUE_PATH = resolve(GLUE_DIR, 'qoder-wasm.js')
const WASM_PATH = resolve(GLUE_DIR, 'qoder-auth-wasm.wasm')
if (!existsSync(GLUE_PATH) || !existsSync(WASM_PATH)) {
  process.stderr.write(
    `qoder_bridge: 目录里没有 ${existsSync(GLUE_PATH) ? '' : 'qoder-wasm.js '}${existsSync(WASM_PATH) ? '' : 'qoder-auth-wasm.wasm'}（${GLUE_DIR}）\n`)
  process.exit(2)
}

const wasm = await import(pathToFileURL(GLUE_PATH).href)
const QoderEncryptedInfer = wasm.QoderEncryptedInfer
if (typeof QoderEncryptedInfer?.create !== 'function') {
  process.stderr.write('qoder_bridge: 该模块没有导出 QoderEncryptedInfer.create\n')
  process.exit(2)
}

/** wasm 调用面的必需符号（缺任何一个 = 这份桥接产物不认识，拒绝服务而不是猜）。 */
const REQUIRED_EXPORTS = ['qodercontext_prepareInferRequest', 'requestresult_headers',
                          'requestresult_url', 'requestresult_body',
                          '__wbindgen_add_to_stack_pointer']
/** GLUE 形状的必需方法（同上：逐项点名缺什么）。 */
const REQUIRED_GLUE = ['writeString', 'lastLength', 'readString', 'takeObject',
                       'callPointer', 'view']

/**
 * 账号 → 已建好的 wasm 上下文（官方约定「一个账号一个实例」，实例不保证并发安全）。
 * 值 = `{g, context}`，由 `create()` 的产物经形状校验后取出。
 */
const clients = new Map()

async function clientFor(req) {
  const cached = clients.get(req.accountKey)
  if (cached) return cached
  const inst = await QoderEncryptedInfer.create({
    user: {
      uid: req.user.uid,
      securityOauthToken: req.user.securityOauthToken,
      ...(req.user.organizationId === undefined ? {} : { organizationId: req.user.organizationId }),
      ...(req.user.organizationTags === undefined ? {} : { organizationTags: req.user.organizationTags }),
      ...(req.user.dataPolicyAgreed === undefined ? {} : { dataPolicyAgreed: req.user.dataPolicyAgreed }),
    },
    machineId: req.machineId,
    metadata: req.metadata,
    host: req.host,
  })
  const g = inst?.g
  const context = inst?.context
  const missing = []
  if (!g || typeof g !== 'object') missing.push('glue 对象(instd.g)')
  else {
    for (const fn of REQUIRED_GLUE) if (typeof g[fn] !== 'function') missing.push(`g.${fn}`)
    for (const fn of REQUIRED_EXPORTS) if (typeof g.exports?.[fn] !== 'function') missing.push(`g.exports.${fn}`)
  }
  if (typeof context !== 'number') missing.push('context(inst.context)')
  if (missing.length) {
    throw new Error(`签名器形状不符（缺 ${missing.join(', ')}）：${GLUE_PATH}`)
  }
  const built = { g, context }
  clients.set(req.accountKey, built)
  return built
}

/** 加密 + 签名（逐步对应上游 `prepareInfer`，差别只在 payload 由调用方给定）。 */
function prepare(client, req) {
  const { g, context } = client
  const result = g.callPointer((stack) => {
    const host = g.writeString(req.host); const hostLen = g.lastLength()
    const body = g.writeString(JSON.stringify(req.payload)); const bodyLen = g.lastLength()
    const key = g.writeString(req.modelKey); const keyLen = g.lastLength()
    const source = g.writeString(req.source ?? 'system'); const sourceLen = g.lastLength()
    // ⚠️ 参数顺序 (sp, ctx, host, hostLen, body, bodyLen, key, keyLen, source, sourceLen)
    g.exports.qodercontext_prepareInferRequest(
      stack, context, host, hostLen, body, bodyLen, key, keyLen, source, sourceLen)
  })
  const headerMap = g.takeObject(g.exports.requestresult_headers(result))
  const headers = {}
  if (headerMap instanceof Map) {
    for (const [k, v] of headerMap) headers[String(k)] = String(v)
  }
  const readResultString = (invoke) => {
    const v = g.view()
    const stack = g.exports.__wbindgen_add_to_stack_pointer(-16)
    try {
      invoke(stack, result)
      const ptr = v.getInt32(stack + 0, true)
      const len = v.getInt32(stack + 4, true)
      return ptr ? g.readString(ptr, len) : ''
    } finally {
      g.exports.__wbindgen_add_to_stack_pointer(16)
    }
  }
  return {
    // ⚠️ 参数顺序 (栈指针, ptr) —— 与直觉相反（上游同处有同一条注释）
    url: readResultString((stack, ptr) => g.exports.requestresult_url(stack, ptr)),
    headers,
    body: readResultString((stack, ptr) => g.exports.requestresult_body(stack, ptr)),
  }
}

const out = (frame) => process.stdout.write(JSON.stringify(frame) + '\n')

const rl = createInterface({ input: process.stdin, terminal: false })
rl.on('line', async (line) => {
  const trimmed = line.trim()
  if (!trimmed) return
  let req = null
  try {
    req = JSON.parse(trimmed)
  } catch {
    out({ id: null, ok: false, error: 'bad-json-line' })
    return
  }
  try {
    if (req.op === 'info') {
      out({ id: req.id, ok: true, result: { gluePath: GLUE_PATH, wasmPath: WASM_PATH,
                                             accounts: clients.size } })
      return
    }
    if (req.op === 'prepare') {
      const client = await clientFor(req)
      out({ id: req.id, ok: true, result: prepare(client, req) })
      return
    }
    if (req.op === 'build') {
      // **反漂移核对**用：把上游参考实现的明文请求体原样吐回给 Python 比对
      // （`tests/unit/test_qoder_wasm_signer.py` 的等价性判据；不发网络、不建上下文）。
      if (typeof wasm.buildQoderInferPayload !== 'function') {
        throw new Error('该签名器产物没有导出 buildQoderInferPayload，无法做等价性核对')
      }
      out({ id: req.id, ok: true, result: { payload: wasm.buildQoderInferPayload(req.ask) } })
      return
    }
    out({ id: req.id, ok: false, error: `未知 op：${String(req.op)}` })
  } catch (e) {
    // 只回**类名 + 消息**：消息里可能带账号标识，故 Python 侧还要再脱敏一次。
    out({ id: req.id, ok: false, error: `${e?.name || 'Error'}: ${e?.message || String(e)}` })
  }
})
rl.on('close', () => process.exit(0))
