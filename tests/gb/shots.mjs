/*
 * shots.mjs - run a list of steps against a running Gearboy and save screenshots (for looking at the game
 * in both machines; nothing is compared).  Steps are a JSON array in a file (argv[3], after the unused
 * mode argument run_emu.ps1 passes first):
 *   {"wait": ms} {"press": "start"} {"release": "start"} {"tap": "start"} {"shot": "out.png"}
 *   {"poke": "_symbol", "bytes": "01"}  (WRAM write by .noi symbol)  {"cont": true} {"pause": true}
 *   {"peek": "_symbol", "n": 2}  prints WRAM bytes   {"step": n} run n frames while paused (sync)
 *   {"apu": true} prints the APU state
 * GB_NOI selects the .noi.
 */
import { readFileSync, writeFileSync } from 'fs';
import * as c from './gearboy_client.mjs';

const sleep = ms => new Promise(r => setTimeout(r, ms));
const txt = r => r.map(x => x.text || '').join('');
const noi = readFileSync(process.env.GB_NOI, 'utf8');
const sym = n => parseInt(new RegExp(`DEF ${n} 0x([0-9A-Fa-f]+)`).exec(noi)[1], 16);
const hex = v => v.toString(16).toUpperCase().padStart(4, '0');
const steps = JSON.parse(readFileSync(process.argv[3], 'utf8'));

await c.init();
await c.call('debug_continue');
for (const s of steps) {
    if (s.wait) await sleep(s.wait);
    else if (s.press) await c.call('controller_button', { action: 'press', button: s.press, player: 1 });
    else if (s.release) await c.call('controller_button', { action: 'release', button: s.release, player: 1 });
    else if (s.tap) {
        await c.call('controller_button', { action: 'press', button: s.tap, player: 1 });
        await sleep(200);
        await c.call('controller_button', { action: 'release', button: s.tap, player: 1 });
    } else if (s.poke) await c.call('write_memory', { area: 6, offset: hex(sym(s.poke) - 0xC000), bytes: s.bytes });
    else if (s.peek) {
        const r = JSON.parse(txt(await c.call('read_memory', { area: 6, offset: hex(sym(s.peek) - 0xC000), size: s.n || 1 })));
        console.log(`${s.peek} = ${r.data}`);
    } else if (s.apu) {
        const a = JSON.parse(txt(await c.call('get_apu_status', {})));
        console.log('apu', JSON.stringify(a).slice(0, 1500));
    } else if (s.step) await c.call('debug_step_frame', { frames: s.step, mode: 'sync' });
    else if (s.pause) await c.call('debug_pause');
    else if (s.cont) await c.call('debug_continue');
    else if (s.shot) {
        for (const x of await c.call('get_screenshot', {})) {
            if (x.type === 'image') writeFileSync(s.shot, Buffer.from(x.data, 'base64'));
        }
    }
}