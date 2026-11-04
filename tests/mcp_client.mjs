/*
 * mcp_client.mjs - minimal MesenCE-MCP Streamable HTTP client.
 *
 * Start Mesen first, e.g.:
 *   .\MesenCE-MCP\MesenCE-MCP-Windows.exe --mcp --mcp-port=9100 \
 *       --enableStdout --doNotSaveSettings --nes.region=Ntsc
 *
 * The handshake is: initialize (no session id) -> capture Mcp-Session-Id
 * -> notifications/initialized -> tools/call with the session id.
 */
import fs from 'node:fs';

export const MCP_URL = process.env.MESEN_MCP_URL || 'http://localhost:9100/mcp';

let sessionId = null;
let nextId = 1;

export const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function parseSse(text) {
    const out = [];
    for (const block of text.split(/\r?\n\r?\n/)) {
        const data = block.split(/\r?\n/)
            .filter(line => line.startsWith('data:'))
            .map(line => line.slice(5).trimStart())
            .join('\n');
        if (data) out.push(JSON.parse(data));
    }
    return out;
}

async function post(body, useSession = true) {
    const headers = {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
    };
    if (useSession && sessionId) headers['Mcp-Session-Id'] = sessionId;

    const res = await fetch(MCP_URL, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
    });
    const text = await res.text();
    const sid = res.headers.get('mcp-session-id');
    if (sid) sessionId = sid;
    if (!res.ok) throw new Error(`MCP HTTP ${res.status}: ${text}`);
    return parseSse(text);
}

export async function init() {
    await post({
        jsonrpc: '2.0',
        id: nextId++,
        method: 'initialize',
        params: {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'river-raid-nes-smoke', version: '1.0' },
        },
    }, false);
    await post({
        jsonrpc: '2.0',
        method: 'notifications/initialized',
        params: {},
    });
}

export async function callTool(name, args = {}) {
    const messages = await post({
        jsonrpc: '2.0',
        id: nextId++,
        method: 'tools/call',
        params: { name, arguments: args },
    });

    const msg = messages.find(m => m && m.result);
    if (!msg) {
        const err = messages.find(m => m && m.error);
        throw new Error(`${name}: ${err ? err.error.message : 'no result'}`);
    }
    if (msg.result.isError) {
        const detail = (msg.result.content || [])
            .filter(c => c.type === 'text')
            .map(c => c.text)
            .join('\n');
        throw new Error(`${name}: ${detail || 'tool error'}`);
    }
    return msg.result.content
        ?.filter(c => c.type === 'text')
        .map(c => c.text)
        .join('\n') ?? '';
}

export async function readBytes(address, length, memoryType = 'NesMemory') {
    const text = await callTool('mesen_read_memory', {
        address: `0x${address.toString(16)}`,
        length,
        memoryType,
    });
    return text.trim().split(/\s+/).filter(Boolean).map(h => parseInt(h, 16));
}

export async function writeBytes(address, bytes, memoryType = 'NesMemory') {
    const hexData = bytes.map(b => b.toString(16).padStart(2, '0')).join('');
    return callTool('mesen_write_memory', {
        address: `0x${address.toString(16)}`,
        hexData,
        memoryType,
    });
}

export async function readU8(address, memoryType = 'NesMemory') {
    return (await readBytes(address, 1, memoryType))[0];
}

export async function readU16(address, memoryType = 'NesMemory') {
    const b = await readBytes(address, 2, memoryType);
    return b[0] | (b[1] << 8);
}

export function readU16From(bytes, offset = 0) {
    return bytes[offset] | (bytes[offset + 1] << 8);
}

export function symbolsFromNoi(file) {
    const out = {};
    for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
        const m = line.match(/^\s*DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)\s*$/);
        if (m) out[m[1]] = parseInt(m[2], 16);
    }
    return out;
}

export function requireSymbol(symbols, name) {
    const value = symbols[name] ?? symbols[`_${name}`];
    if (value === undefined) {
        throw new Error(`Symbol not found in .noi: ${name}`);
    }
    return value;
}

/* The cart boots into attract mode (no jet, no lives).  Tests that need a game
 * call this right after pausing: it presses START on port 0 and releases it. */
export async function startGame() {
    const step = async n => { for (let i = 0; i < n; i++) await callTool('mesen_step', { cpuType: 'Nes', count: 1, stepType: 'PpuFrame' }); };
    await step(60);
    await callTool('mesen_input_override', { action: 'set', port: 0, buttons: 'Start' });
    await step(8);
    await callTool('mesen_input_override', { action: 'set', port: 0, buttons: '' });
    await step(2);
}
