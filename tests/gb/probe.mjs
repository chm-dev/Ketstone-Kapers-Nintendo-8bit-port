/*
 * probe.mjs - ad-hoc Gearboy MCP probe: lists tools (argv 'tools') or calls one tool with JSON args:
 *   node tests/gb/probe.mjs call get_cpu_registers '{}'
 * Steps for longer runs: tests/gb/shots.mjs.
 */
import * as c from './gearboy_client.mjs';
await c.init();
const [cmd, name, args] = process.argv.slice(2);
if (cmd === 'tools') {
    for (const t of await c.listTools()) console.log(t.name, '-', (t.description || '').slice(0, 100), JSON.stringify(t.inputSchema?.properties || {}));
} else if (cmd === 'call') {
    const r = await c.call(name, args ? JSON.parse(args) : {});
    for (const x of r) console.log(x.type === 'text' ? x.text : `[${x.type}]`);
}
