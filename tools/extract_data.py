#!/usr/bin/env python3
"""Dump named ROM tables and measured sequences to assets/data/keystone_data.json (input for Phase 2).

Sources: assets/atari/keystone_image_9f80_bfff.bin (all `rom` entries) and tests/golden/ball1.txt (ball cycle).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
img = (ROOT / "assets/atari/keystone_image_9f80_bfff.bin").read_bytes()


def rom(addr, n):
    return list(img[addr - 0x9F80: addr - 0x9F80 + n])


rows = [l.split() for l in (ROOT / "tests/golden/ball1.txt").read_text().splitlines()[1:]]
data = {
    "_note": "rom entries are bytes at the given Atari address; see docs/ATARI_RE_SPEC.md for meaning",
    "rom": {
        "points_per_floor_BCD_hundreds_B5F7": rom(0xB5F7, 4),
        "escalator_base_x_B8D4": rom(0xB8D4, 4),
        "escalator_face_B8D7": rom(0xB8D7, 4),
        "escalator_screen_B9E3": rom(0xB9E3, 4),
        "elevator_path_by_car_floor_BBA1": rom(0xBBA1, 4),
        "elevator_thief_block_path_BBA2": rom(0xBBA2, 4),
        "floor_y_base_BE50": rom(0xBE50, 4),
        "pickup_screen_choices_B9AF": rom(0xB9AF, 8),
        "gravity_mask_B9A7": rom(0xB9A7, 8),
        "initial_state_B9BB_to_1B": rom(0xB9BB, 6),
        "bgm_ch3_audf_B700": rom(0xB700, 0x64),
        "bgm_ch4_audf_B763": rom(0xB763, 0x64),
        "sound_effect_ptr_lo_B8F5": rom(0xB8F5, 16),
        "sound_data_page_BA00": rom(0xBA00, 0x100),
        "obstacle_param_BCC0": rom(0xBCC0, 0x14),
        "digit_glyphs_BE34": rom(0xBE34, 16),
    },
    "measured": {
        "jump_height_events": "9 INC then 9 DEC of $1C; see spec 6",
        "ball_height_71_cycle_96_frames": [int(r[8], 16) for r in rows[80:176]],
        "ball_speed_px_per_frame": 0.5,
        "walk_speed_px_per_frame": 1,
        "thief_speed_px_per_frame": 0.5,
        "timer_start_BCD": 0x50,
        "timer_tick_frames": 128,
        "stun_frames": 36,
        "start_lives_spare": 3,
        "extra_life_every_points": 10000,
        "bonus_hundreds_per_time_unit_by_tier": {"level_idx_lt_8": 1, "level_idx_8_to_15": 2, "level_idx_ge_16": 3},
        "escalator_ticks": "one per 4 frames, 29..32 ticks",
        "elevator_closed_frames": 120,
        "elevator_open_ticks": 112,
    },
}
out = ROOT / "assets/data/keystone_data.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(data, indent=1))
print("wrote", out, out.stat().st_size, "bytes")
