/*
 * nes_shot.mjs - run N frames of the running Mesen ROM and save a screenshot.
 * Run: node tests/nes_shot.mjs [out.png] [frames]
 * Needs Mesen started with --mcp (see info/MESEN_MCP_NOTES.md).
 */
import path from 'node:path';
import { init, callTool } from './mcp_client.mjs';

const out = path.resolve(process.argv[2] || 'build/nes_shot.png');
const frames = Number(process.argv[3] || 30);
await init();
for (let i = 0; i < frames; i++) await callTool('mesen_step', { cpuType: 'Nes', count: 1, stepType: 'PpuFrame' });
await callTool('mesen_take_screenshot', { outputFile: out });
console.log('saved', out);
