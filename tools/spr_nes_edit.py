#!/usr/bin/env python3
"""Export / import a hand-editable sheet of the NES (13 px) sprite frames.

`--export` (default) writes assets/data/spr_nes_edit.png at 1:1 - one image pixel per sprite pixel,
transparent background, every frame twice (facing right, facing left), no grid, no text - plus
assets/data/spr_nes_edit.json, which holds the layout the importer needs (do not edit it).

Each 8x8 tile of every frame keeps the sprite palette the generator gave it, so a pixel may only use
that palette's 4 colours (index 0 = transparent).  The allowed colours are printed by --export and
listed in the JSON.  Colours are exact NES 2C02 approximations (RGB), e.g. (212,136,32) = $27.

`--import` reads the edited PNG, checks every pixel against its tile's palette, writes
assets/data/spr_nes_overrides.json (only frames that really changed) and rebuilds src/spr_nes.c/.h
through tools/gen_assets.py.  gen_assets.py --emit re-applies the overrides, so hand edits survive
art regeneration.  The image cannot change the tile layout, frame pivots or collision boxes - only
the pixels inside each tile.

Usage:
  python -I tools/spr_nes_edit.py --export          # plain 1:1 sheet (default)
  python -I tools/spr_nes_edit.py --annotated       # reference sheet: 6x zoom, grid, palette digits
  python -I tools/spr_nes_edit.py --import [--snap] # apply the edited sheet
  python -I tools/spr_nes_edit.py --reset           # drop the overrides, re-emit the generated data
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
IMGP = ROOT / 'assets/data/spr_nes_edit.png'
JSONP = ROOT / 'assets/data/spr_nes_edit.json'
REFP = ROOT / 'assets/data/spr_nes_edit_ref.png'
OVP = ROOT / 'assets/data/spr_nes_overrides.json'
MAGENTA = (255, 0, 255)


def load_gen_assets():
    spec = importlib.util.spec_from_file_location('gen_assets', ROOT / 'tools/gen_assets.py')
    ga = importlib.util.module_from_spec(spec)
    sys.modules['gen_assets'] = ga
    sys.argv = ['gen_assets.py']              # the module parses no args itself
    spec.loader.exec_module(ga)
    return ga


def build(ga, ov=True):
    frames, pals, chr_list, argb, D = ga.build()
    nes_chr = ga.build_nes(frames, pals, D, ga.load_overrides() if ov else {})
    return frames, pals, chr_list, nes_chr


def layout(ga, frames, pals, zoom, y0):
    """Where each frame/facing sits in the image, and its tile cells (row/col in 8 px units)."""
    plain = zoom == 1
    block = 1 if plain else zoom
    pitch = 1 if plain else zoom + 1
    gap_x = 2 if plain else 34
    gap_y = 4 if plain else 34
    fw = ga.NES_W * pitch
    x0 = 8 if plain else 176
    out, y = [], y0
    for f in frames:
        cells = []
        for flip in (0, 1):
            items = sorted(f['nes_items'][flip], key=lambda it: (it['dy'], it['dx']))
            dy0 = items[0]['dy']
            rows = max((it['dy'] - dy0) // 8 for it in items) + 1
            cells.append(dict(flip=flip, x=x0 + flip * (fw + gap_x), y=y, rows=rows,
                              items=[dict(dy=it['dy'], dx=it['dx'], pal=it['pal'],
                                          row=(it['dy'] - dy0) // 8, col=it['dx'] // 8) for it in items]))
        out.append(dict(name=f['name'], cells=cells))
        y += max(c['rows'] for c in cells) * 8 * pitch + gap_y
    return dict(version=2, image=str(IMGP.relative_to(ROOT)).replace('\\', '/'),
                zoom=zoom, block=block, pitch=pitch, width=ga.NES_W, transparent=list(MAGENTA),
                palettes=[[list(MAGENTA)] + [[int(v) for v in ga.NES_RGB[c]] for c in p] for p in pals],
                frames=out)


def cell_pixels(ga, frame, flip, pals, nes_chr):
    """rows*8 x 13 grid of RGB (None = transparent) as the ROM draws it for that facing."""
    items = sorted(frame['nes_items'][flip], key=lambda it: (it['dy'], it['dx']))
    dy0 = items[0]['dy']
    rows = max((it['dy'] - dy0) // 8 for it in items) + 1
    img = [[None] * ga.NES_W for _ in range(rows * 8)]
    for it in items:
        t = nes_chr[it['tile']]
        if it['flip']:
            t = [list(reversed(r)) for r in t]
        pal = pals[it['pal']]
        for yy in range(8):
            for xx in range(8):
                fx = it['dx'] + xx
                if fx >= ga.NES_W:
                    continue
                v = int(t[yy][xx])
                img[(it['dy'] - dy0) + yy][fx] = None if v == 0 else ga.nes_rgb(pal[v - 1])
    return img


def export(ga, frames, pals, nes_chr, zoom, annotated):
    if not annotated:
        zoom = 1
    header = 66 + 26 * len(pals) + 18 if annotated else 0
    lay = layout(ga, frames, pals, zoom, header)
    pitch, block = lay['pitch'], lay['block']
    w = lay['frames'][0]['cells'][1]['x'] + ga.NES_W * pitch + 8
    if annotated:
        w = max(w, 580)
    last = lay['frames'][-1]
    if annotated:
        h = header + sum(max(c['rows'] for c in fr['cells']) * 8 * pitch + 34 for fr in lay['frames'])
    else:
        h = last['cells'][0]['y'] + max(c['rows'] for c in last['cells']) * 8 * pitch + 8
    bg = (0, 0, 0, 0) if not annotated else (32, 32, 32, 255)
    im = Image.new('RGBA', (w, h), bg)
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default()

    if annotated:
        d.text((10, 6), 'Keystone Kapers NES - 13 px sprite frames (reference sheet)', font=font,
               fill=(240, 240, 240))
        for i, line in enumerate([
                'The plain 1:1 sheet is the editable one (python -I tools/spr_nes_edit.py --export).',
                'Magenta = transparent. Digits left of each tile row = sprite palette of left | right tile.',
                'Each 8x8 tile may only use its palette\u2019s 4 colours; tile boundaries are the bright lines.']):
            d.text((10, 22 + i * 13), line, font=font, fill=(170, 190, 170))
        y = 66
        for pi, pal in enumerate(lay['palettes']):
            d.text((10, y + 6), f'palette {pi}', font=font, fill=(230, 230, 230))
            for ci, rgb in enumerate(pal):
                x = 80 + ci * 64
                col = (MAGENTA if ci == 0 else tuple(rgb)) + (255,)
                d.rectangle([x, y, x + 26, y + 22], fill=col, outline=(90, 90, 90))
                d.text((x + 30, y + 6), f'idx{ci}', font=font, fill=(200, 200, 200))
            y += 26

    for fr in lay['frames']:
        f = next(x for x in frames if x['name'] == fr['name'])
        if annotated:
            d.text((10, fr['cells'][0]['y'] + 4), fr['name'], font=font, fill=(240, 240, 240))
        for cell in fr['cells']:
            x0 = cell['x']
            y0 = cell['y'] + (14 if annotated else 0)
            img = cell_pixels(ga, f, cell['flip'], pals, nes_chr)
            if annotated:
                for r in range(cell['rows']):
                    pl = [it['pal'] for it in cell['items'] if it['row'] == r]
                    label = f'{pl[0]}|{pl[1]}' if len(pl) > 1 else f'{pl[0]}'
                    d.text((x0 - 26, y0 + r * 8 * pitch + 2 * pitch), label, font=font, fill=(150, 190, 230))
                d.text((x0 + 14, cell['y']), 'facing right' if cell['flip'] == 0 else 'facing left',
                       font=font, fill=(160, 160, 160))
            for yy in range(len(img)):
                for xx in range(len(img[0])):
                    c = img[yy][xx]
                    col = (0, 0, 0, 0) if c is None else tuple(c) + (255,)
                    px, py = x0 + xx * pitch, y0 + yy * pitch
                    d.rectangle([px, py, px + block - 1, py + block - 1], fill=col)
            if annotated:
                for xx in range(len(img[0]) + 1):
                    col = (120, 120, 120) if (xx % 8) == 0 else (58, 58, 58)
                    px = x0 + xx * pitch - 1
                    d.line([px, y0, px, y0 + len(img) * pitch - 2], fill=col)
                for yy in range(len(img) + 1):
                    col = (120, 120, 120) if (yy % 8) == 0 else (58, 58, 58)
                    py = y0 + yy * pitch - 1
                    d.line([x0, py, x0 + len(img[0]) * pitch - 2, py], fill=col)
    target = IMGP if not annotated else REFP
    im.save(target)
    if not annotated:
        JSONP.write_text(json.dumps(lay, indent=1))
    print(f'wrote {target.relative_to(ROOT)} ({im.width}x{im.height}, '
          f'{"1:1, transparent background" if not annotated else f"{zoom}x reference, layout untouched"})'
          + (f' and {JSONP.relative_to(ROOT)}' if not annotated else ''))
    if not annotated:
        print('sprite palettes (index 0 = transparent), per 8x8 tile:')
        for pi, pal in enumerate(lay['palettes']):
            print(f'  palette {pi}: idx1 {tuple(pal[1])}  idx2 {tuple(pal[2])}  idx3 {tuple(pal[3])}')
        print('edit, then: python -I tools/spr_nes_edit.py --import')


def snap(rgb, colours):
    return min(colours, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, rgb)))


def do_import(ga, frames, pals, nes_chr, base, nes_base, allow_snap):
    if not IMGP.exists() or not JSONP.exists():
        raise SystemExit(f'missing {IMGP.name}/{JSONP.name}: run --export first')
    lay = json.loads(JSONP.read_text())
    im = Image.open(IMGP).convert('RGBA')
    pitch, block = lay['pitch'], lay['block']
    trans = tuple(lay['transparent'])
    by_name = {f['name']: f for f in frames}
    base_by_name = {f['name']: f for f in base}
    out, errors, snapped, changed = {}, [], 0, []
    for fr in lay['frames']:
        f = by_name[fr['name']]
        fb = base_by_name[fr['name']]
        for cell in fr['cells']:
            x0, y0 = cell['x'], cell['y'] + (14 if lay['zoom'] > 1 else 0)
            items = sorted(f['nes_items'][cell['flip']], key=lambda i: (i['dy'], i['dx']))
            items_b = sorted(fb['nes_items'][cell['flip']], key=lambda i: (i['dy'], i['dx']))
            cells, same = [], True
            for it, itb, meta in zip(items, items_b, sorted(cell['items'], key=lambda i: (i['row'], i['col']))):
                pal = pals[it['pal']]
                cols = [None] + [tuple(int(v) for v in ga.NES_RGB[c]) for c in pal]
                px = []
                for yy in range(8):
                    row = []
                    for xx in range(8):
                        fx, fy = meta['col'] * 8 + xx, meta['row'] * 8 + yy
                        if fx >= lay['width']:
                            row.append(0)
                            continue
                        dot = im.getpixel((x0 + fx * pitch + block // 2, y0 + fy * pitch + block // 2))
                        c = tuple(dot[:3])
                        if dot[3] == 0 or c == trans:
                            row.append(0)
                        elif c in cols:
                            row.append(cols.index(c))
                        elif allow_snap:
                            row.append(cols.index(snap(c, cols[1:])))
                            snapped += 1
                        else:
                            errors.append(f'{fr["name"]} {("L" if cell["flip"] else "R")} tile r{meta["row"]}c'
                                          f'{meta["col"]} +{xx},{yy}: {c} not in palette {it["pal"]} '
                                          f'({[f"{v}" for v in cols[1:]]})')
                            row.append(0)
                    px.append(row)
                cur = nes_base[itb['tile']]
                if itb['flip']:
                    cur = [list(reversed(r)) for r in cur]
                if [list(map(int, r)) for r in cur] != px:
                    same = False
                cells.append(dict(dy=it['dy'], dx=it['dx'], pal=it['pal'], px=px))
            if not same:
                out.setdefault(fr['name'], {})[str(cell['flip'])] = cells
                changed.append(f'{fr["name"]}{"-L" if cell["flip"] else "-R"}')
    if errors:
        print(f'{len(errors)} pixel(s) outside their palette, nothing written:')
        for e in errors[:12]:
            print('  ', e)
        if len(errors) > 12:
            print(f'   ... {len(errors) - 12} more')
        raise SystemExit(1)
    if snapped:
        print(f'warning: {snapped} pixel(s) snapped to the nearest palette colour')
    if not out:
        if OVP.exists():
            OVP.unlink()
            print(f'no edited frame found: removed {OVP.name}')
        reemit(ga)
        return 0
    OVP.write_text(json.dumps(out, indent=0))
    print(f'wrote {OVP.relative_to(ROOT)}: {len(changed)} frame(s) edited -> {" ".join(changed)}')
    reemit(ga)
    return 0


def reemit(ga):
    frames, pals, chr_list, nes_chr = build(ga)
    ga.emit_nes(frames, pals, nes_chr)
    print(f'wrote src/spr_nes.c/.h ({len(nes_chr)} tiles); run .\\build.ps1')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--export', action='store_true')
    ap.add_argument('--annotated', action='store_true', help='reference sheet (zoom/grid/labels)')
    ap.add_argument('--import', dest='imp', action='store_true')
    ap.add_argument('--reset', action='store_true')
    ap.add_argument('--snap', action='store_true', help='accept off-palette colours (nearest match)')
    ap.add_argument('--zoom', type=int, default=6, help='zoom for --annotated')
    a = ap.parse_args()
    ga = load_gen_assets()
    if a.reset:
        if OVP.exists():
            OVP.unlink()
        reemit(ga)
        print('overrides removed')
        return
    frames, pals, chr_list, nes_chr = build(ga)
    if a.imp:
        base = build(ga, ov=False)
        raise SystemExit(do_import(ga, frames, pals, nes_chr, base[0], base[3], a.snap) or 0)
    export(ga, frames, pals, nes_chr, a.zoom, a.annotated)


if __name__ == '__main__':
    main()
