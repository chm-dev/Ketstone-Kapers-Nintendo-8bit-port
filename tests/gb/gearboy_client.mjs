/*
 * gearboy_client.mjs - minimal Gearboy MCP HTTP client.
 * Start: gearboy/Gearboy.exe --headless --mcp-http --mcp-http-port 7777 rom.gb rom.noi
 */
let sid = null, id = 1;
const URL_ = process.env.GEARBOY_MCP_URL || 'http://127.0.0.1:7777/mcp';

async function post(body) {
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' };
    headers['MCP-Protocol-Version'] = '2025-11-25';
    if (sid) headers['Mcp-Session-Id'] = sid;
    const res = await fetch(URL_, { method: 'POST', headers, body: JSON.stringify(body) });
    const text = await res.text();
    const s = res.headers.get('mcp-session-id');
    if (s) sid = s;
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${text}`);
    if (!text) return null;
    const data = text.startsWith('{') ? text
        : text.split(/\r?\n/).filter(l => l.startsWith('data:')).map(l => l.slice(5)).join('\n');
    return data ? JSON.parse(data) : null;
}

export async function init() {
    await post({ jsonrpc: '2.0', id: id++, method: 'initialize', params: {
        protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'gb-bench', version: '1' } } });
    await post({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
}
export async function listTools() {
    return (await post({ jsonrpc: '2.0', id: id++, method: 'tools/list', params: {} })).result.tools;
}
export async function call(name, args = {}) {
    const m = await post({ jsonrpc: '2.0', id: id++, method: 'tools/call', params: { name, arguments: args } });
    if (m.error) throw new Error(`${name}: ${m.error.message}`);
    return m.result.content;
}
