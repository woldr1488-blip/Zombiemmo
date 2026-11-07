import os
os.environ["SDL_TOUCH_MOUSE_EVENTS"] = "0"
os.environ["SDL_MOUSE_TOUCH_EVENTS"] = "0"
import pygame
import numpy as np
pygame.init()
import socket, threading, math, time, random, json, traceback, queue, sys
import ast
import hashlib

def discover_mods():
    import os, json
    found = []
    if os.path.isdir("addon"):
        for name in os.listdir("addon"):
            path = os.path.join("addon", name)
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "manifest.json")):
                desc = ""
                script = "main.py"
                sha = ""
                try:
                    import json as _json
                    with open(os.path.join(path, "manifest.json"), "r", encoding="utf-8") as _mf:
                        _man = _json.load(_mf)
                    if isinstance(_man, dict):
                        desc = str(_man.get("description", ""))
                        script = str(_man.get("script", "main.py"))
                except Exception:
                    pass
                try:
                    import hashlib as _hl
                    _sp = os.path.join(path, script)
                    if os.path.isfile(_sp):
                        with open(_sp, "rb") as _sf:
                            sha = _hl.sha256(_sf.read()).hexdigest()
                except Exception:
                    pass
                found.append({"id": name, "dir": path, "name": name,
                              "description": desc, "script": script, "sha256": sha})
    return found



def encode(msg):
    d = json.dumps(msg, default=list, separators=(",", ":")).encode("utf-8")
    return len(d).to_bytes(4, "big") + d

def decode_from_buffer(buf):
    out = []
    while len(buf) >= 4:
        L = int.from_bytes(buf[:4], "big")
        if len(buf) < 4 + L: break
        d = bytes(buf[4:4 + L]); del buf[:4 + L]
        out.append(json.loads(d.decode("utf-8")))
    return out

SETTINGS_FILE = "zombie_settings.json"
GAMESTATE_FILE = "gamestate.dat"
GAMESTATE_MAGIC = b"ZSUR"; GAMESTATE_VERSION = 1

DEFAULT_KEYBINDS = {
    "shop": "z",
    "build": "q",
    "slot1": "1",
    "slot2": "2",
    "slot3": "3",
    "slot4": "4",
    "slot5": "5",
    "apple": "e",
    "lightning": None,
    "minigun": None,
    "firedoom": None,
    "crazy": None,
    "drop": "r",
}
KEYBIND_LABELS = {
    "shop": "Магазин",
    "build": "Строй. слот",
    "slot1": "Слот 1",
    "slot2": "Слот 2",
    "slot3": "Слот 3",
    "slot4": "Слот 4",
    "slot5": "Слот 5",
    "apple": "Яблоко",
    "lightning": "Ускорение",
    "minigun": "Миниган",
    "firedoom": "Огненное дуло",
    "crazy": "Сумасшествие",
    "drop": "Выбросить",
}
KEYBIND_ORDER = ["shop","build","slot1","slot2","slot3","slot4","slot5",
                 "apple","lightning","minigun","firedoom","crazy","drop"]

def load_settings():
    try:
        with open(SETTINGS_FILE, "r") as f:
            d = json.load(f)
            if "keybinds" not in d or not isinstance(d.get("keybinds"), dict):
                d["keybinds"] = dict(DEFAULT_KEYBINDS)
            if "pixelate" not in d:
                d["pixelate"] = True
            return d
    except Exception:
        return {"button_mode": "default", "show_barricade_preview": False,
                "pixelate": True,
                "keybinds": dict(DEFAULT_KEYBINDS)}
def save_settings(d):
    try:
        with open(SETTINGS_FILE, "w") as f: json.dump(d, f)
    except Exception: pass

def _gs_xor(data, key): return bytes(b ^ key for b in data)
def _gs_checksum(data): return sum(data) & 0xFFFFFFFF

def load_gamestate():
    default = {"kills": 0, "wins": 0, "deaths": 0, "stage": 0, "unlocks": [], "achievements": [],
               "not_first": False, "input_mode": "touch",
               "tutorial_step": -1, "tutorial_seen": [],
               "bosses_killed": 0}
    try:
        with open(GAMESTATE_FILE, "rb") as f: raw = f.read()
    except Exception: return default
    if len(raw) < 14 or raw[:4] != GAMESTATE_MAGIC or raw[4] != GAMESTATE_VERSION: return default
    xor_key = raw[5]; plen = int.from_bytes(raw[6:10], "big")
    if len(raw) < 10 + plen + 4: return default
    payload = raw[10:10 + plen]
    if int.from_bytes(raw[10 + plen:10 + plen + 4], "big") != _gs_checksum(payload): return default
    try: data = json.loads(_gs_xor(payload, xor_key).decode("utf-8"))
    except Exception: return default
    out = dict(default)
    for k in ("kills","wins","deaths","stage"):
        v = data.get(k, 0)
        if isinstance(v, int) and v >= 0: out[k] = v
    ul = data.get("unlocks", [])
    if isinstance(ul, list): out["unlocks"] = [str(x) for x in ul]
    ach = data.get("achievements", [])
    if isinstance(ach, list): out["achievements"] = [str(x) for x in ach]
    out["not_first"] = bool(data.get("not_first", False))
    im = data.get("input_mode", "touch")
    if im not in ("pc", "touch"): im = "touch"
    out["input_mode"] = im
    return out

def save_gamestate(data):
    payload_json = json.dumps({
        "kills": int(data.get("kills", 0)), "wins": int(data.get("wins", 0)),
        "deaths": int(data.get("deaths", 0)), "stage": int(data.get("stage", 0)),
        "unlocks": list(data.get("unlocks", [])),
        "achievements": list(data.get("achievements", [])),
        "not_first": bool(data.get("not_first", False)),
        "input_mode": str(data.get("input_mode", "touch")),
    }, separators=(",", ":"))
    xor_key = random.randint(1, 255)
    payload = _gs_xor(payload_json.encode("utf-8"), xor_key)
    raw = (GAMESTATE_MAGIC + bytes([GAMESTATE_VERSION, xor_key]) + len(payload).to_bytes(4, "big")
           + payload + _gs_checksum(payload).to_bytes(4, "big"))
    try:
        with open(GAMESTATE_FILE, "wb") as f: f.write(raw)
    except Exception: pass

def _init_mixer():
    try: pygame.mixer.pre_init(44100, -16, 2, 1024); pygame.mixer.init(); pygame.mixer.music.set_volume(0.35); return True
    except Exception: return False
def _load_sound(path):
    try: return pygame.mixer.Sound(path)
    except Exception: return None
def _play_sound(snd, volume=1.0):
    if snd is None: return
    try:
        ch = snd.play()
        if ch is not None and volume != 1.0: ch.set_volume(volume)
    except Exception: pass


# ============================================================
#  МУЗЫКА — общий помощник
# ============================================================
_HERE = os.path.dirname(os.path.abspath(__file__))

def _find_music(name):
    """Ищет файл рядом с game.py и в music/ рядом с ним.
    Возвращает абсолютный путь или None."""
    candidates = [
        os.path.join(_HERE, "music", name),
        os.path.join(_HERE, name),
        os.path.join(_HERE, "game", "music", name),
        os.path.join(os.getcwd(), "music", name),
        os.path.join(os.getcwd(), name),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None

MUSIC_MENU_NAME = "menu_music.wav"
MUSIC_GAME_NAME = "fon.wav"

# Кэш путей (находим один раз)
_MUSIC_MENU_PATH = _find_music(MUSIC_MENU_NAME)
_MUSIC_GAME_PATH = _find_music(MUSIC_GAME_NAME)

if _MUSIC_MENU_PATH:
    print("[music] menu:", _MUSIC_MENU_PATH)
else:
    print("[music] menu не найден:", MUSIC_MENU_NAME)
if _MUSIC_GAME_PATH:
    print("[music] game:", _MUSIC_GAME_PATH)
else:
    print("[music] game не найден:", MUSIC_GAME_NAME)

# ============================================================
#  ИНФОРМАЦИЯ ОБ ОБНОВЛЕНИИ
# ============================================================
current_update  = "бездонная дыра"
current_version = "1.0"

# версия последнего патча — вручную поднимается каждый патч
patch_version = "v61"

WIDTH, HEIGHT = 1463, 700
PIXEL_SCALE = 2
FPS = 60; TICK_RATE = 20; SEND_RATE = 20
DEFAULT_PORT = 5555; DISCOVERY_PORT = 5556
MAP_W, MAP_H = 5000, 5000
PLAYER_R = 40; PLAYER_SPEED = 600; MAX_HP = 100
SHOOT_CD = 0.35; RESPAWN_DELAY = 5.0
CHAT_DURATION = 3.0; CHAT_MAX_LEN = 50; MAX_WEAPON_SLOTS = 5

STAGE_WAVES = {0: 10, 1: 50, 2: 100}
STAGE_NAMES = {0: "10 волн", 1: "50 волн", 2: "100 волн"}
UNLOCK_BOSSRUSH = "bossrush"; UNLOCK_PVP = "pvp"; UNLOCK_HARD = "hard"
UNLOCK_STAGE100 = "stage100"; UNLOCK_FORBIDDEN = "forbidden"
UNLOCK_NAMES = {UNLOCK_BOSSRUSH: "Босс-раш", UNLOCK_PVP: "ПвП", UNLOCK_HARD: "Сложный режим",
                UNLOCK_STAGE100: "Этап 100 волн", UNLOCK_FORBIDDEN: "Запретное знание"}
ACH_ONE_MAN_ARMY = "one_man_army"; ACH_NOT_FUNNY = "not_funny"; ACH_HORRORS_OF_PAST = "horrors_of_past"
ACHIEVEMENT_NAMES = {ACH_ONE_MAN_ARMY: "Один в поле воин", ACH_NOT_FUNNY: "Несмешной",
                      ACH_HORRORS_OF_PAST: "Ужасы прошлого"}
ACHIEVEMENT_DESCS = {ACH_ONE_MAN_ARMY: "Пройди игру без друзей будучи хостом",
                      ACH_NOT_FUNNY: "Убей первого зомби волны последним",
                      ACH_HORRORS_OF_PAST: "Пройди 100 волн"}
ACHIEVEMENT_EFFECTS = {ACH_ONE_MAN_ARMY: "Миниган +1 сек", ACH_NOT_FUNNY: "Сумасшествие x20",
                        ACH_HORRORS_OF_PAST: "Открывает Запретное знание"}
def stage_max_wave(stage): return STAGE_WAVES.get(stage, 100)

XP_BASE = 100; XP_GROWTH = 1.7
def xp_for_level(n):
    if n <= 0: return 0
    return int(XP_BASE * (XP_GROWTH ** n - 1) / (XP_GROWTH - 1))
def level_from_xp(xp):
    lvl = 0
    while xp_for_level(lvl + 1) <= xp:
        lvl += 1
        if lvl > 10000: break
    return lvl
def xp_to_next_level(lvl): return xp_for_level(lvl + 1) - xp_for_level(lvl)
def level_damage_bonus(lvl): return lvl

MAX_WAVE = 100
WAVE_BREAK_TIME = 10.0; WAVE_SPAWN_INTERVAL = 0.25
MAX_ZOMBIES_ON_MAP = 200; MAX_ZOMBIES_PER_WAVE = 800
def zombie_reward(wave): return 10 + int((wave - 1) * 790 / 99)
ZOMBIE_HP = 100; ZOMBIE_R = 40; ZOMBIE_SPEED = 100; ZOMBIE_DMG = 10; ZOMBIE_HIT_CD = 0.6
ZOMBIE_TYPES = {
    "normal":    {"chance": 0.60, "hp_mult": 1.0, "speed_mult": 1.0, "dmg_mult": 1.0, "r_mult": 1.0, "color": (70, 140, 70)},
    "runner":    {"chance": 0.15, "hp_mult": 0.5, "speed_mult": 2.0, "dmg_mult": 0.8, "r_mult": 0.9, "color": (240, 220, 60)},
    "tank":      {"chance": 0.10, "hp_mult": 3.0, "speed_mult": 0.5, "dmg_mult": 1.5, "r_mult": 1.3, "color": (45, 50, 60)},
    "enraged":   {"chance": 0.07, "hp_mult": 1.0, "speed_mult": 1.0, "dmg_mult": 1.0, "r_mult": 1.0, "color": (139, 69, 19)},
    "spitter":   {"chance": 0.07, "hp_mult": 1.0, "speed_mult": 0.8, "dmg_mult": 1.0, "r_mult": 1.0, "color": (200, 200, 60)},
    "infected":  {"chance": 0.05, "hp_mult": 1.0, "speed_mult": 1.0, "dmg_mult": 1.0, "r_mult": 1.0, "color": (60, 100, 60)},
    "kamikaze":  {"chance": 0.03, "hp_mult": 0.7, "speed_mult": 1.0, "dmg_mult": 1.0, "r_mult": 1.0, "color": (255, 100, 0)},
}
BOMBER_EXPLODE_R = 140; BOMBER_EXPLODE_DMG = 30
SPITTER_RANGE = 500; SPITTER_CD = 3.0; SPITTER_DMG = 15; SPITTER_SPEED = 500
INFECTED_PUDDLE_R = 80; INFECTED_PUDDLE_LIFE = 10.0; INFECTED_PUDDLE_DPS = 5.0

BOSS_WAVE_INTERVAL = 10
BOSS_R = int(ZOMBIE_R * 6.5); BOSS_HP = 10000
BOSS_SPEED_MULT = 0.8; BOSS_DMG = 30; BOSS_HIT_CD = 0.8
BOSS_XP_REWARD = 2000; BOSS_COINS_REWARD = 2000
STAGE50_BOSS_HP = 20000
STAGE50_BOSS_DASH_CD = 10.0; STAGE50_BOSS_DASH_DIST = 200
STAGE50_BOSS_DASH_DMG = 20; STAGE50_BOSS_TELEGRAPH = 0.5
STAGE50_BOSS_DASH_DURATION = 0.25
FINAL_BOSS_HP = 1000000; FINAL_BOSS_R = int(ZOMBIE_R * 20)
FINAL_BOSS_SPEED_MULT = 1.2; FINAL_BOSS_DMG = 50; FINAL_BOSS_HIT_CD = 0.6
FINAL_BOSS_XP_REWARD = 100000; FINAL_BOSS_COINS_REWARD = 100000
# --- финальный босс: самонаводящаяся пуля ---
FINAL_BOSS_HOMING_CD = 5.0
FINAL_BOSS_HOMING_LIFE = 15.0
FINAL_BOSS_HOMING_SPEED = 350
FINAL_BOSS_HOMING_TURN = 2.0
FINAL_BOSS_HOMING_DMG_FRAC = 0.5
FINAL_BOSS_HOMING_R = 18

def is_boss_wave(wave): return wave > 0 and wave % BOSS_WAVE_INTERVAL == 0
def is_final_wave(wave): return wave == MAX_WAVE

MODE_NORMAL = "normal"; MODE_BOSS_RUSH = "boss_rush"; MODE_PVP = "pvp"
MODE_NAMES = {MODE_NORMAL: "Обычный", MODE_BOSS_RUSH: "Босс-раш", MODE_PVP: "ПвП"}

DIFF_EASY = "easy"; DIFF_NORMAL = "normal"; DIFF_HARD = "hard"
DIFFICULTY_MODS = {
    DIFF_EASY:   {"hp_mult": 0.7, "dmg_mult": 0.7, "speed_mult": 0.9, "count_mult": 0.7, "reward_mult": 0.8},
    DIFF_NORMAL: {"hp_mult": 1.0, "dmg_mult": 1.0, "speed_mult": 1.0, "count_mult": 1.0, "reward_mult": 1.0},
    DIFF_HARD:   {"hp_mult": 1.5, "dmg_mult": 1.4, "speed_mult": 1.15,"count_mult": 1.5, "reward_mult": 1.5},
}
DIFF_NAMES = {DIFF_EASY: "Лёгкий", DIFF_NORMAL: "Обычный", DIFF_HARD: "Сложный"}

BUILD_BARRICADE = "barricade"; BUILD_TURRET = "turret"; BUILD_FIRE_TURRET = "fire_turret"
BUILD_REPAIR_TURRET = "repair_turret"
BUILD_ELECTRIC_TURRET = "electric_turret"
BUILD_HAMMER = "hammer"
BUILD_DOOR = "door"
BUILD_LABELS = {BUILD_BARRICADE: "Баррикада", BUILD_TURRET: "Турель", BUILD_FIRE_TURRET: "Огненная турель", BUILD_REPAIR_TURRET: "Ремонтная турель", BUILD_ELECTRIC_TURRET: "Электрическая турель", BUILD_DOOR: "Дверь"}
BUILD_PRICES = {BUILD_BARRICADE: 200, BUILD_TURRET: 500, BUILD_FIRE_TURRET: 900, BUILD_REPAIR_TURRET: 1500, BUILD_ELECTRIC_TURRET: 2000, BUILD_DOOR: 300}
BUILD_HP = {BUILD_BARRICADE: 50, BUILD_TURRET: 100, BUILD_FIRE_TURRET: 100, BUILD_REPAIR_TURRET: 100, BUILD_ELECTRIC_TURRET: 100, BUILD_DOOR: 100}
BUILD_MAX_PER_PLAYER = {BUILD_BARRICADE: 300, BUILD_TURRET: 100, BUILD_FIRE_TURRET: 1, BUILD_REPAIR_TURRET: 1, BUILD_ELECTRIC_TURRET: 1, BUILD_DOOR: 999}
BARRICADE_GRID = 40; BARRICADE_DMG = 1; BARRICADE_HIT_CD = 1.0; BARRICADE_RANGE = 2
TURRET_RANGE = 600; TURRET_SHOOT_CD = 2.5; TURRET_DMG = 25; TURRET_BULLET_SPEED = 1100
FIRE_TURRET_SHOOT_CD = 7.0; FIRE_TURRET_DMG = 50
FIRE_TURRET_BULLET_SPEED = 900; FIRE_TURRET_PIERCE = 10
SPITTER_BUILDING_DMG = 5
ELECTRIC_TURRET_CD = 3.0
ELECTRIC_TURRET_DMG = 50
ELECTRIC_TURRET_BULLET_SPEED = 1200
ELECTRIC_CHAIN_RANGE = 300
ELECTRIC_CHAIN_COUNT = 5
ELECTRIC_CHAIN_DMG = 34
REPAIR_TURRET_CD = 3.0
REPAIR_TURRET_RANGE = 600

CRATE_R = 35; CRATE_TOUCH_R = 70; CRATE_SPAWN_CENTER_R = 1200
CRATE_RARITIES = [
    ("rare", 0.400, 1, 3, 10, 50, 100, 200, (60, 200, 60)),
    ("superrare", 0.200, 2, 7, 30, 80, 100, 200, (60, 120, 240)),
    ("epic", 0.100, 10,10, 300, 300, 500, 500, (160, 60, 220)),
    ("mythic", 0.050, 20,20, 500, 500, 1000, 1000, (220, 40, 40)),
    ("legendary", 0.025, 30,30, 2000, 2000, 5000, 5000, (255, 220, 40)),
]
CRATE_RARITY_NAMES = {"rare": "РЕДКИЙ ЯЩИК", "superrare": "СВЕРХРЕДКИЙ ЯЩИК",
                       "epic": "ЭПИЧЕСКИЙ ЯЩИК", "mythic": "МИФИЧЕСКИЙ ЯЩИК",
                       "legendary": "ЛЕГЕНДАРНЫЙ ЯЩИК"}
CRATE_BUFF_CHANCES = [("apple", 0.400), ("lightning", 0.200), ("firedoom", 0.100),
                       ("minigun", 0.050), ("crazy", 0.025)]
CRATES_PER_WAVE_MIN = 1
CRATES_PER_WAVE_MAX = 10

FORBIDDEN_DROP_CHANCE = 0.01; FORBIDDEN_BOSS_DROP_CHANCE = 0.50
FORBIDDEN_R = 25; FORBIDDEN_TOUCH_R = 60

PRISM_SHARD_R = 25; PRISM_SHARD_TOUCH_R = 60
PRISM_SHARD_DROP_CHANCE = 0.02
PRISM_SHARDS_NEEDED = 9
STARDUST_R = 25; STARDUST_TOUCH_R = 60
STARDUST_DROP_CHANCE = 0.20
STARDUST_NEEDED = 10

MEDKIT_HEAL = 10
APPLE_EAT_DURATION = 0.8
LIGHTNING_DURATION = 30.0; LIGHTNING_SPEED_MULT = 1.5
MINIGUN_DURATION = 10.0; MINIGUN_SHOOT_MULT = 3.0
FIREDOOM_DURATION = 30.0
FIRE_DURATION = 5.0
FIRE_DPS = 10          # было 1 — огненное дуло теперь реально наносит урон
FIRE_VULN_MULT = 2.0   # горящий зомби получает ×2 урона
CRAZY_DURATION = 5.0; CRAZY_MULT = 19.0
CRAZY_MULT_ACH = 20.0; MINIGUN_DURATION_ACH = 11.0
STAR_HOMING_RADIUS = 600; STAR_TURN_RATE = 4.0; STAR_SPEED = 700
STAR_SPLASH_R = 120; STAR_SPLASH_DMG = 80
STAR_SPECIAL_EVERY = 10; STAR_SPECIAL_MIN_LEVEL = 5
METEOR_DELAY = 3.0; METEOR_DMG = 50; STONE_FREEZE_DURATION = 3.0
LASER_RANGE = 1000; LASER_WIDTH = 20; LASER_TICK = 0.01; LASER_BASE_DMG = 1
SHIELD_DMG_REDUCTION = 0.60

WAVE_BUTTON_R = 60

ARSENAL = {
    "base":         {"price": 300,    "label": "Пистолет"},
    "rifle":        {"price": 300,    "label": "Автомат"},
    "shotgun":      {"price": 800,    "label": "Дробовик"},
    "smg":          {"price": 2000,   "label": "ПП «Вихрь»"},
    "shield":       {"price": 4000,   "label": "Щит"},
    "first_prism":  {"price": 4000,   "label": "Первая призма"},
    "sniper":       {"price": 5000,   "label": "Снайперка"},
    "sword":        {"price": 8000,   "label": "Меч"},
    "laser":        {"price": 12000,  "label": "Лазер"},
    "stone":        {"price": 15000,  "label": "Каменный посох"},
    "charm_sword":  {"price": 20000,  "label": "Меч очарования"},
    "meteor":       {"price": 20000,  "label": "Метеоритный посох"},
    "charm_staff":  {"price": 28000,  "label": "Посох очарования"},
    "plasma":       {"price": 30000,  "label": "Плазмаган"},
    "star":         {"price": 50000,  "label": "Звёздная пушка"},
    "cursed_sword": {"price": 100000, "label": "Проклятый меч"},
    "hexagon":      {"price": 100000, "label": "Гексагон"},
    "secret_beam":  {"price": 100000, "label": "Секретное излучение"},
    "last_prism":   {"price": 500000, "label": "Последняя призма"},
    "true_star":    {"price": 500000, "label": "Истинная звёздная пушка"},
    "bow":          {"price": 18000,  "label": "Лук охотника"},
}
WEAPON_DESCS = {
    "base":         "За каждый уровень +2 урона вместо 1. При убийстве пистолетом есть шанс на выпадение сундука с 1 предметом.",
    "rifle":        "Огромная скорострельность, отлично подходит для начала.",
    "shotgun":      "Убойный урон вблизи, для профессионалов. Урон дроби растёт, чем ближе цель к стрелку.",
    "smg":          "Очень быстрый темп стрельбы, малый урон за пулю. Хорош против слабых зомби.",
    "shield":       "Не стреляет. Снижает получаемый урон на 60%. Пассивный защитный слот.",
    "first_prism":  "Луч, прошивающий всех врагов на линии. Урон 15, не требует пуль.",
    "sniper":       "Огромный урон, пробивает до 5 зомби. Урон растёт с дистанцией.",
    "sword":        "Ближний бой. Широкий замах, наносит 55 урона всем в дуге.",
    "laser":        "Непрерывный луч. Урон 6 за тик, тик каждые 0.05 сек.",
    "stone":        "Замораживает цель на 3 секунды. Урон слабый, но контроль сильный.",
    "charm_sword":  "Ближний бой. При убийстве зомби появляется его очарованная копия, сражающаяся за вас.",
    "meteor":       "Вызывает метеорит на голову зомби. Урон по площади 50.",
    "charm_staff":  "Снаряд с 15% шансом очаровать зомби (5% для боссов).",
    "plasma":       "Плазменный шар, взрывается по площади 120. Урон 40.",
    "star":         "Самонаводящаяся звезда. Каждый 10-й выстрел (при Lv5+) — взрыв по площади.",
    "cursed_sword": "Ближний бой. Наносит 4 удара подряд по дуге — суммарно в 4 раза больше урона.",
    "hexagon":      "При попадании призывает 3 теневых клона зомби с 33% HP. Открывается после убийства босса на 50-й волне.",
    "secret_beam":  "Два портала по бокам от игрока стреляют самонаводящимися пулями.",
    "last_prism":   "Бесконечный луч через всю карту. Урон 50 за тик каждые 0.05 сек.",
    "true_star":    "Улучшенная звёздная пушка: урон 100, скорострельность как у автомата.",
    "bow":          "Заряжаемое оружие. Урон и скорость стрелы зависят от времени натяжения (до 3 сек).",
    "hammer":       "Сносит вашу постройку и возвращает её в инвентарь.",
    "wrench":       "Чинит вашу постройку за монеты (1 монета = 1 HP).",
}
ARSENAL_LABELS = {k: v.get("label", k) for k, v in ARSENAL.items()}

SHOP_BUFFS = {
    "apple":     {"price": 50,   "label": "Яблоко"},
    "lightning": {"price": 100,  "label": "Ускорение"},
    "minigun":   {"price": 200,  "label": "Миниган"},
    "firedoom":  {"price": 300,  "label": "Огненное дуло"},
    "crazy":     {"price": 1000, "label": "Сумасшествие"},
}
PASSIVES = {
    "coin_volley":  {"price": 20000, "label": "Залп монет",
                     "desc": "За каждый удар (даже по воздуху) даётся 1 монета. На лазере — 1 монета каждые 0.01с."},
    "first_number": {"price": 5000, "label": "Первый номер",
                     "desc": "Первый зомби волны рендерится золотым и даёт ×20 монет.",
                     "requires_achievement": ACH_NOT_FUNNY},
    "скорострел":  {"price": 5000, "label": "Скорострел",
                     "desc": "Все ваши турели стреляют на 30% быстрее. Открывается за достижение «Боб строитель».",
                     "requires_achievement": "bob_builder"},

    "фиксик":      {"price": 5000, "label": "Фиксик",
                     "desc": "Ремонтные турели чинят на 20% быстрее."},

    "алаказам":    {"price": 1000, "label": "Алаказам",
                     "desc": "1% шанс выстрелить пулей с уроном 10^15 (гарантированное убийство)."},
    "казуал":     {"price": 10000, "label": "Казуал",
                     "desc": "Копи эйфорию. 100 эйфории → 10 сек безумия. Плюс пистолет +2 урона за уровень.",
                     "requires_wave": 50},
}
WEAPON_STATS = {
    "fist":         {"dmg": 10, "cooldown": 0.8,  "pellets": 0, "spread": 0.0,
                      "life": 0.0,  "speed": 0,    "melee": True, "reach": 120,
                      "arc": math.pi * 0.7},
    "base":         {"dmg": 8,  "cooldown": 0.35, "pellets": 1, "spread": 0.02, "life": 1.2,  "speed": 1100, "lvl_bonus": 2},
    "rifle":        {"dmg": 6,  "cooldown": 0.11, "pellets": 1, "spread": 0.05, "life": 1.2,  "speed": 1300},
    "shotgun":      {"dmg": 5,  "cooldown": 0.9,  "pellets": 7, "spread": 0.30, "life": 0.35, "speed": 1400},
    "smg":          {"dmg": 4,  "cooldown": 0.06, "pellets": 1, "spread": 0.10, "life": 1.0,  "speed": 1500},
    "sniper":       {"dmg": 45, "cooldown": 1.1,  "pellets": 1, "spread": 0.0,  "life": 2.5,  "speed": 2600, "pierce": 5},
    "laser":        {"dmg": 6,  "cooldown": 0.10, "pellets": 0, "spread": 0.0,  "life": 0.0,  "speed": 0, "beam": True},
    "plasma":       {"dmg": 40, "cooldown": 0.5,  "pellets": 1, "spread": 0.03, "life": 1.8,  "speed": 1500, "explosive": 120},
    "sword":        {"dmg": 55, "cooldown": 0.35, "pellets": 0, "spread": 0.0,  "life": 0.0,  "speed": 0,    "melee": True, "reach": 130, "arc": math.pi * 0.7},
    "charm_sword":  {"dmg": 55, "cooldown": 0.35, "pellets": 0, "spread": 0.0,  "life": 0.0,  "speed": 0,    "melee": True, "reach": 130, "arc": math.pi * 0.7, "charm_on_kill": True},
    "shield":       {"dmg": 0,  "cooldown": 10.0, "pellets": 0, "spread": 0.0,  "life": 0.0,  "speed": 0, "no_shoot": True},
    "stone":        {"dmg": 2,  "cooldown": 3.0,  "pellets": 1, "spread": 0.0,  "life": 1.5,  "speed": 950, "freeze": 3.0},
    "meteor":       {"dmg": 1,  "cooldown": 1.0,  "pellets": 1, "spread": 0.0,  "life": 1.5,  "speed": 1000, "meteor": True},
    "charm_staff":  {"dmg": 7,  "cooldown": 1.0,  "pellets": 1, "spread": 0.0,  "life": 1.5,  "speed": 1000, "charm": True, "charm_chance": 0.15, "charm_boss_chance": 0.05},
    "star":         {"dmg": 10, "cooldown": 2.0,  "pellets": 1, "spread": 0.0,  "life": 4.0,  "speed": 700, "homing": True, "special_every": 10, "special_min_lvl": 5},
    "cursed_sword": {"dmg": 55, "cooldown": 0.35, "pellets": 0, "spread": 0.0,  "life": 0.0,  "speed": 0,    "melee": True, "reach": 130, "arc": math.pi * 0.7, "multi_hits": 4, "multi_delay": 0.05},
    "hexagon":      {"dmg": 7,  "cooldown": 1.0,  "pellets": 1, "spread": 0.0,  "life": 1.5,  "speed": 1000, "hexagon": True, "hexagon_min_wins": 10},
    "secret_beam":  {"dmg": 20, "cooldown": 0.8,  "pellets": 2, "spread": 0.0,
                      "life": 2.5,  "speed": 700,  "homing": True, "secret_beam": True,
                      "portal_offset": 70},
    "first_prism":  {"dmg": 15, "cooldown": 0.2,  "pellets": 0, "spread": 0.0,  "life": 0.0,  "speed": 0, "beam": True, "prism_beam": True},
    "last_prism":   {"dmg": 50, "cooldown": 0.05, "pellets": 0, "spread": 0.0,  "life": 0.0,  "speed": 0, "beam": True, "prism_beam": True, "prism_last": True},
    "true_star":    {"dmg": 100, "cooldown": 0.11, "pellets": 1, "spread": 0.05, "life": 4.0, "speed": 900, "homing": True, "true_star": True},
    "bow":          {"dmg": 35, "cooldown": 0.8,  "pellets": 1, "spread": 0.0,  "life": 2.0,  "speed": 1500, "chargeable": True, "max_charge": 1.0},
}



# ============================================================
#  ХАОС — новые константы / унлоки / оружие
# ============================================================
UNLOCK_CRYSTAL = "crystal"
UNLOCK_ENDLESS = "endless"
ACH_BOB = "bob_builder"
ACHIEVEMENT_NAMES[ACH_BOB] = "Боб строитель"
ACHIEVEMENT_DESCS[ACH_BOB] = "Поставь все виды построек за один забег"
ACHIEVEMENT_EFFECTS[ACH_BOB] = "Открывает «Скорострел» и «Защиту кристалла»"
UNLOCK_NAMES[UNLOCK_CRYSTAL] = "Защита кристалла"
UNLOCK_NAMES[UNLOCK_ENDLESS] = "Бесконечный"

BOB_BUILD_KINDS = (BUILD_BARRICADE, BUILD_TURRET, BUILD_FIRE_TURRET,
                   BUILD_REPAIR_TURRET, BUILD_ELECTRIC_TURRET, BUILD_DOOR)

CRYSTAL_R = 70
CRYSTAL_HP = 1000
CRYSTAL_DMG = 10
CRYSTAL_HIT_CD = 1.0
CRYSTAL_PUSH_ACCEL = 200.0
CRYSTAL_FRICTION = 4.0
CRYSTAL_MAX_SPEED = 120.0

ARSENAL["hammer"] = {"price": 1000, "label": "Молоток"}
WEAPON_STATS["hammer"] = {"dmg": 10, "cooldown": 0.5, "pellets": 0, "spread": 0.0,
                          "life": 0.0, "speed": 0, "melee": True, "reach": 100,
                          "arc": math.pi * 0.7, "hammer": True}

ARSENAL["wrench"] = {"price": 1500, "label": "Гаечный ключ"}
WEAPON_STATS["wrench"] = {"dmg": 8, "cooldown": 0.6, "pellets": 0, "spread": 0.0,
                          "life": 0.0, "speed": 0, "melee": True, "reach": 110,
                          "arc": math.pi * 0.7, "wrench": True}

DIFF_ENDLESS = "endless"
DIFFICULTY_MODS[DIFF_ENDLESS] = {"hp_mult": 1.0, "dmg_mult": 1.0,
                                  "speed_mult": 1.0, "count_mult": 1.0,
                                  "reward_mult": 1.0}
DIFF_NAMES[DIFF_ENDLESS] = "Бесконечный"

MODE_CRYSTAL = "crystal"
MODE_NAMES[MODE_CRYSTAL] = "Защита кристалла"

def weapon_dmg_with_level(stats, lvl):
    """Урон с учётом уровня. Для пистолета (lvl_bonus=2) +2/ур,
    для остальных — +1/ур."""
    bonus = stats.get("lvl_bonus", 1)
    return stats["dmg"] + bonus * lvl

def _hexagon_allowed(host_wins, achievements):
    return host_wins >= 10

def _hard_weapons_allowed(host_wins, achievements):
    return ACH_HORRORS_OF_PAST in achievements

CLIENT_WEAPON_GATES = {
    "hexagon": _hexagon_allowed,
    "cursed_sword": _hard_weapons_allowed,
}

# ============================================================
#  СОХРАНЕНИЕ СОЛО
# ============================================================
SOLO_SAVE_FILE = "solo_save.dat"
SOLO_SAVE_MAGIC = b"ZSOLO"
SOLO_SAVE_VERSION = 1

def _solo_save_raw(data_dict):
    """Сериализует dict в bytes: magic + version + xor_key + len + payload + checksum."""
    payload_json = json.dumps(data_dict, separators=(",", ":"), default=list)
    xor_key = random.randint(1, 255)
    payload = _gs_xor(payload_json.encode("utf-8"), xor_key)
    return (SOLO_SAVE_MAGIC + bytes([SOLO_SAVE_VERSION, xor_key])
            + len(payload).to_bytes(4, "big") + payload
            + _gs_checksum(payload).to_bytes(4, "big"))

def _solo_save_parse(raw):
    """Возвращает dict или None."""
    if not raw or len(raw) < 14: return None
    if raw[:5] != SOLO_SAVE_MAGIC: return None
    if raw[5] != SOLO_SAVE_VERSION: return None
    xor_key = raw[6]; plen = int.from_bytes(raw[7:11], "big")
    if len(raw) < 11 + plen + 4: return None
    payload = raw[11:11 + plen]
    if int.from_bytes(raw[11 + plen:11 + plen + 4], "big") != _gs_checksum(payload): return None
    try:
        return json.loads(_gs_xor(payload, xor_key).decode("utf-8"))
    except Exception:
        return None

def load_solo_save():
    try:
        with open(SOLO_SAVE_FILE, "rb") as f: raw = f.read()
    except Exception:
        return None
    data = _solo_save_parse(raw)
    if data is None:
        print("[solo_save] повреждён, новая игра")
    return data

def write_solo_save(data_dict):
    try:
        with open(SOLO_SAVE_FILE, "wb") as f:
            f.write(_solo_save_raw(data_dict))
    except Exception as e:
        print("[solo_save] ошибка записи:", e)

def delete_solo_save():
    try: os.remove(SOLO_SAVE_FILE)
    except Exception: pass


COLOR_NAMES = [
    ("black", (0, 0, 0)), ("white", (255, 255, 255)), ("green", (0, 180, 0)),
    ("lime", (150, 255, 120)), ("purple", (150, 60, 220)), ("pink", (255, 130, 200)),
    ("sakura", (255, 200, 220)), ("gray", (140, 140, 140)), ("blue", (40, 90, 220)),
    ("orange", (255, 140, 0)), ("red", (220, 40, 40)), ("brown", (140, 90, 60)),
    ("cyan", (90, 200, 255)), ("coral", (255, 120, 100)),
]
PLAYER_COLORS = [c for _, c in COLOR_NAMES]
MAX_PLAYERS = len(COLOR_NAMES)
def color_name_of(rgb):
    t = tuple(rgb)
    for n, c in COLOR_NAMES:
        if c == t: return n
    return None
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close()
        if ip and not ip.startswith("127."): return ip
    except Exception: pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."): return ip
    except Exception: pass
    return "127.0.0.1"

CHEAT_CODES = ("ALLDUST31", "FCKGRAYFRICK", "YOUCANT")


# =====================================================================
#  ПЕСОЧНИЦА МОДОВ v2 — белый список атрибутов + изоляция builtins
#  (установлено патчем patch_sandbox.py)
# =====================================================================

# Белый список атрибутов, доступных моду. Всё, чего тут нет, — AttributeError.
# Ключ — имя корневого модуля, значение — set разрешённых имён.
_MOD_ALLOWED = {
    "math": {
        "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "hypot", "pi", "e", "tau", "inf", "nan",
        "floor", "ceil", "trunc", "fabs", "fmod", "copysign",
        "pow", "log", "log2", "log10", "exp",
        "radians", "degrees", "isnan", "isinf", "isfinite",
        "gcd", "factorial", "comb", "perm",
    },
    "random": {
        "random", "randint", "randrange", "choice", "choices",
        "shuffle", "uniform", "gauss", "seed", "sample",
    },
    "pygame": {
        # только рисование, события, шрифты, время, Rect, Surface, Color
        "draw", "Rect", "Surface", "SRCALPHA", "transform", "time",
        "mouse", "key", "font", "image", "Color", "display",
        "FINGERDOWN", "FINGERUP", "FINGERMOTION",
        "MOUSEBUTTONDOWN", "MOUSEBUTTONUP", "MOUSEMOTION",
        "KEYDOWN", "KEYUP",
        "K_ESCAPE", "K_RETURN", "K_BACKSPACE", "K_w", "K_a", "K_s", "K_d",
        "QUIT",
        # намеренно НЕ включены: pygame.sys, pygame.os, pygame.constants
        # (constants содержит строки и числа — не опасно, но не нужно),
        # pygame.mixer (может писать в звуковую карту — пусть будет),
        # pygame.__builtins__, pygame.__loader__, pygame.__spec__, pygame.__file__,
        # pygame.__dict__, pygame.__getattribute__, pygame.__class__.
    },
}

# Эти имена нельзя запрашивать ни у какого прокси, даже если они есть
# у настоящего модуля. Страховка на случай, если в будущем кто-то
# расширит _MOD_ALLOWED по неосторожности.
_MOD_DENY_ALWAYS = {
    "__dict__", "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__loader__", "__spec__", "__file__",
    "__name__", "__package__", "__path__", "__import__", "__getattr__",
    "__setattr__", "__delattr__", "__init_subclass__", "__reduce__",
    "__reduce_ex__", "__code__", "__closure__", "__func__", "__self__",
    "__module__", "__qualname__", "__annotations__", "__kwdefaults__",
    "sys", "os", "subprocess", "builtins", "importlib", "ctypes",
    "gc", "inspect", "pickle", "marshal", "socket", "shutil",
    "tempfile", "pathlib", "io", "code", "codeop", "platform",
}


class _ModProxy:
    """Прокси над настоящим модулем: пускает только атрибуты из белого
    списка. Никакие dunder-атрибуты и никакие известные опасные модули
    не отдаёт."""
    __slots__ = ("_real", "_allowed")

    def __init__(self, real, allowed):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_allowed", frozenset(allowed))

    def __getattr__(self, name):
        if name in _MOD_DENY_ALWAYS or name.startswith("__"):
            raise AttributeError(f"[mod] атрибут '{name}' запрещён")
        if name not in self._allowed:
            raise AttributeError(f"[mod] атрибут '{name}' не разрешён")
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        raise AttributeError("[mod] изменение модулей запрещено")

    def __delattr__(self, name):
        raise AttributeError("[mod] изменение модулей запрещено")

    def __dir__(self):
        return sorted(self._allowed)

    def __repr__(self):
        return f"<ModProxy {self._real.__name__}>"


def _mod_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Импорт внутри мода: разрешены math, random, pygame (через прокси)
    и локальные .py-файлы папки мода (тоже через прокси, но без
    доступа к атрибутам вне белого списка — их просто нет в _MOD_ALLOWED,
    так что локальный модуль вернётся как обычный, но без dunder'ов
    получить к нему доступ нельзя, потому что доступ — через тот же
    прокси)."""
    if level != 0:
        raise ImportError(f"[mod] относительный импорт '{name}' запрещён")
    base = name.split(".")[0]
    if base in _MOD_ALLOWED:
        real = __import__(name, globals, locals, fromlist, level)
        return _ModProxy(real, _MOD_ALLOWED[base])
    raise ImportError(f"[mod] импорт '{name}' запрещён")


def _make_safe_open(mod_dir):
    """open() внутри мода: только чтение, только внутри папки мода.
    Никаких 'w', 'a', 'x', '+'."""
    base = os.path.abspath(mod_dir)

    def _safe_open(path, mode="r", *args, **kwargs):
        if not isinstance(mode, str):
            raise TypeError("[mod] режим open() должен быть строкой")
        # разрешаем только r и rb
        if mode not in ("r", "rb"):
            raise PermissionError(f"[mod] режим open('{mode}') запрещён (только 'r'/'rb')")
        p = os.path.abspath(str(path))
        if not (p == base or p.startswith(base + os.sep)):
            raise PermissionError(f"[mod] доступ к '{path}' запрещён")
        return open(p, mode, *args, **kwargs)

    return _safe_open


def _make_mod_builtins(mod_dir):
    """Фиксированный __builtins__ для мода. Здесь НЕТ:
    exec, eval, compile, __import__ (импортёр подставляется отдельно),
    globals, locals, vars, dir, type, object, super, __build_class__,
    __loader__, breakpoint, help, exit, quit, input."""
    safe_open = _make_safe_open(mod_dir)
    return {
        # разрешённые типы и конструкторы
        "int": int, "float": float, "bool": bool, "str": str,
        "bytes": bytes, "bytearray": bytearray, "list": list,
        "dict": dict, "tuple": tuple, "set": set, "frozenset": frozenset,
        "complex": complex, "range": range, "slice": slice,
        "memoryview": memoryview,
        # числа
        "abs": abs, "min": min, "max": max, "sum": sum,
        "round": round, "pow": pow, "divmod": divmod,
        # последовательности
        "len": len, "iter": iter, "next": next, "reversed": reversed,
        "sorted": sorted, "enumerate": enumerate, "zip": zip,
        "map": map, "filter": filter, "all": all, "any": any,
        # предикаты
        "isinstance": isinstance, "issubclass": issubclass,
        "hasattr": hasattr, "getattr": getattr, "setattr": setattr,
        # repr/format
        "repr": repr, "ascii": ascii, "format": format, "hash": hash,
        "id": id, "callable": callable,
        # строки/байты
        "chr": chr, "ord": ord,
        # исключения
        "Exception": Exception, "BaseException": BaseException,
        "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError,
        "AttributeError": AttributeError, "RuntimeError": RuntimeError,
        "StopIteration": StopIteration, "ZeroDivisionError": ZeroDivisionError,
        "ArithmeticError": ArithmeticError, "LookupError": LookupError,
        "NotImplementedError": NotImplementedError,
        "PermissionError": PermissionError, "ImportError": ImportError,
        "NameError": NameError, "OSError": OSError, "IOError": IOError,
        "Warning": Warning,
        # полезное
        "print": print, "open": safe_open,
        "True": True, "False": False, "None": None,
        # __import__ подменяется в load_all_mods на _mod_import;
        # здесь его НЕТ — чтобы нельзя было вызвать до подстановки.
    }


class _ModApiProxy:
    """Тонкий прокси, который передаётся в on_start(host, api).
    Даёт моду то, что нельзя достать из host."""
    __slots__ = ("host",)
    def __init__(self, host):
        object.__setattr__(self, "host", host)
    def register_weapon_renderer(self, key, icon_fn=None, sprite_fn=None, desc=None):
        """Мод отдаёт рисование своего оружия.
        icon_fn(screen, rect) — рисует иконку в магазине/хотбаре.
        sprite_fn(angle) -> Surface — спрайт в руках.
        desc — описание (если ещё не задано в register_weapon)."""
        entry = self.weapon_renderers.setdefault(key, {})
        if icon_fn is not None and callable(icon_fn):
            entry["icon"] = icon_fn
        if sprite_fn is not None and callable(sprite_fn):
            entry["sprite"] = sprite_fn
        if desc is not None:
            entry["desc"] = str(desc)
            try:
                WEAPON_DESCS[key] = str(desc)
            except Exception:
                pass
        return True

    def register_ammo_type(self, kind, sprite_fn):
        """Мод регистрирует свой тип снаряда.
        sprite_fn() -> Surface (один раз, дальше кешируется)."""
        if not isinstance(kind, str) or not callable(sprite_fn):
            return False
        self.ammo_renderers[kind] = {"sprite": sprite_fn}
        return True

    def register_ammo_hit(self, kind, handler):
        """Коллизия. Когда пуля мода касается зомби,
        вызывается handler(host, ammo, zombie). Мод сам решает,
        сколько урона нанести (через host._zombie_take_damage и т.п.)."""
        if not isinstance(kind, str) or not callable(handler):
            return False
        self.ammo_hits[kind] = handler
        return True

    def spawn_ammo(self, host, kind, x, y, vx, vy, life=1.5, extra=None):
        """Мод запускает свою пулю.
        Она попадает в host.bullets, но с полем ammo_kind=kind.
        Коллизия обрабатывается через register_ammo_hit."""
        if not isinstance(kind, str):
            return False
        b = {
            "x": float(x), "y": float(y),
            "vx": float(vx), "vy": float(vy),
            "owner": None, "life": float(life), "dmg": 0,
            "weapon": "__mod_ammo__",
            "ammo_kind": kind,
            "firedoom": False, "traveled": 0.0,
        }
        if isinstance(extra, dict):
            b.update(extra)
        try:
            host.bullets.append(b)
            return True
        except Exception:
            return False

    def register_weapon(self, key, info, stats, desc=None):
        return MOD_API.register_weapon(key, info, stats, desc)
    def register_weapon_renderer(self, key, icon_fn=None, sprite_fn=None, desc=None):
        return MOD_API.register_weapon_renderer(key, icon_fn, sprite_fn, desc)
    def register_ammo_type(self, kind, sprite_fn):
        return MOD_API.register_ammo_type(kind, sprite_fn)
    def register_ammo_hit(self, kind, handler):
        return MOD_API.register_ammo_hit(kind, handler)
    def spawn_ammo(self, host, kind, x, y, vx, vy, life=1.5, extra=None):
        return MOD_API.spawn_ammo(host, kind, x, y, vx, vy, life, extra)
    def get_weapon(self, key):
        return ARSENAL.get(key), WEAPON_STATS.get(key)
    def list_weapons(self):
        return list(ARSENAL.keys())
    def __getattr__(self, name):
        # остальное — прямо к host, но только атрибуты без подчёркивания
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.host, name)
    def __setattr__(self, name, value):
        raise AttributeError("[mod] изменение api запрещено")

def _make_mod_api_proxy(host):
    return _ModApiProxy(host)

def load_all_mods(enabled_ids):
    """Загружает включённые моды в изолированном окружении.
    exec/compile вызываются отсюда, из game.py; в builtins мода их нет."""
    found = discover_mods()
    loaded = []
    for mod in found:
        if mod["id"] not in enabled_ids:
            continue
        try:
            script_path = os.path.join(mod["dir"], mod["script"])
            with open(script_path, "r", encoding="utf-8") as f:
                code = f.read()
            env = {
                "__name__": f"addon_{mod['id']}",
                "__file__": script_path,
                "__builtins__": _make_mod_builtins(mod["dir"]),
            }
            env["__builtins__"]["__import__"] = _mod_import
            for _forbidden in ("exec", "eval", "compile", "globals", "locals",
                               "vars", "dir", "type", "object", "super",
                               "__build_class__", "breakpoint", "help",
                               "exit", "quit", "input"):
                env["__builtins__"].pop(_forbidden, None)
            exec(compile(code, script_path, "exec"), env, env)
            mod["_env"] = env
            loaded.append(mod)
            print(f"[mods] загружен: {mod['name']} ({mod['id']})")
        except Exception as e:
            print(f"[mods] ошибка загрузки {mod['id']}: {e}")
            traceback.print_exc()
    return found, loaded




class ModAPI:
    HOOKS = (
        "on_start", "on_tick", "on_draw", "on_event", "on_kill", "on_boss_killed",
        "on_wave_start", "on_wave_end", "on_player_join", "modify_damage",
        "modify_speed", "on_player_death", "on_player_respawn",
        "on_zombie_spawn", "on_victory", "on_game_over", "on_crate_opened",
        "on_item_used", "on_weapon_bought", "on_build_bought",
        "on_build_destroyed", "on_bullet_hit", "on_laser_hit", "on_melee_hit",
        "modify_coin_reward", "modify_xp_reward", "filter_zombie_spawn",
        "filter_weapon_purchase", "filter_build_place",
        "on_custom_message",
    )
    def __init__(self):
        self.mods = []
        self.registered_weapons = {}   # key -> {"info":..., "stats":...}
        self.weapon_renderers = {}     # key -> {"icon": fn, "sprite": fn, "desc": str}
        self.ammo_renderers = {}       # kind -> {"sprite": fn}
        self.ammo_hits = {}            # kind -> handler(host, ammo, zombie)
    def register(self, loaded_mods):
        self.mods = list(loaded_mods)
    def register_weapon(self, key, info, stats, desc=None):
        """Мод регистрирует новое оружие.
        info = {price, label}, stats = {dmg, cooldown, ...}, desc = строка (необязательно).
        Возвращает True, если оружие добавлено."""
        if not isinstance(key, str) or not isinstance(info, dict) or not isinstance(stats, dict):
            return False
        try:
            ARSENAL[key] = dict(info)
            WEAPON_STATS[key] = dict(stats)
            if desc is None:
                desc = info.get("desc", "") or info.get("label", key)
            WEAPON_DESCS[key] = str(desc)
            return True
        except Exception as e:
            print("[mods] register_weapon error:", e)
            return False
    def register_weapon_renderer(self, key, icon_fn=None, sprite_fn=None, desc=None):
        if not hasattr(self, "weapon_renderers") or self.weapon_renderers is None:
            self.weapon_renderers = {}
        entry = self.weapon_renderers.setdefault(key, {})
        if icon_fn is not None and callable(icon_fn):
            entry["icon"] = icon_fn
        if sprite_fn is not None and callable(sprite_fn):
            entry["sprite"] = sprite_fn
        if desc is not None:
            entry["desc"] = str(desc)
            try:
                WEAPON_DESCS[key] = str(desc)
            except Exception:
                pass
        return True

    def register_ammo_type(self, kind, sprite_fn):
        if not isinstance(kind, str) or not callable(sprite_fn):
            return False
        if not hasattr(self, "ammo_renderers") or self.ammo_renderers is None:
            self.ammo_renderers = {}
        self.ammo_renderers[kind] = {"sprite": sprite_fn}
        return True

    def register_ammo_hit(self, kind, handler):
        if not isinstance(kind, str) or not callable(handler):
            return False
        if not hasattr(self, "ammo_hits") or self.ammo_hits is None:
            self.ammo_hits = {}
        self.ammo_hits[kind] = handler
        return True

    def spawn_ammo(self, host, kind, x, y, vx, vy, life=1.5, extra=None):
        if not isinstance(kind, str):
            return False
        b = {
            "x": float(x), "y": float(y),
            "vx": float(vx), "vy": float(vy),
            "owner": None, "life": float(life), "dmg": 0,
            "weapon": "__mod_ammo__",
            "ammo_kind": kind,
            "firedoom": False, "traveled": 0.0,
        }
        if isinstance(extra, dict):
            b.update(extra)
        try:
            host.bullets.append(b)
            return True
        except Exception:
            return False

    def call(self, hook, *args, **kwargs):
        if hook not in self.HOOKS:
            return None
        results = []
        for mod in self.mods:
            env = mod.get("_env")
            if not env:
                continue
            fn = env.get(hook)
            if callable(fn):
                try:
                    results.append(fn(*args, **kwargs))
                except Exception as e:
                    print(f"[mods] {mod['id']}.{hook} error: {e}")
                    traceback.print_exc()
        return results
    def first_truthy(self, hook, *args, **kwargs):
        for r in (self.call(hook, *args, **kwargs) or []):
            if r:
                return r
        return None
    def on_custom_message(self, host_or_client, msg):
        """Любое сообщение, которое не понял Host._handle / Client._recv."""
        return self.call("on_custom_message", host_or_client, msg)

MOD_API = ModAPI()



def _seg_rect_hit(x1, y1, x2, y2, rx, ry, rw, rh):
    """Liang-Barsky: пересекает ли отрезок прямоугольник."""
    dx = x2 - x1; dy = y2 - y1
    p = [-dx, dx, -dy, dy]
    q = [x1 - rx, rx + rw - x1, y1 - ry, ry + rh - y1]
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0: return False
        else:
            t = qi / pi
            if pi < 0:
                if t > u2: return False
                if t > u1: u1 = t
            else:
                if t < u1: return False
                if t < u2: u2 = t
    return u1 <= u2

def _seg_circle_hit(x1, y1, x2, y2, cx, cy, r):
    """Пересекает ли отрезок (x1,y1)-(x2,y2) окружность (cx,cy,r).
    Возвращает True/False."""
    dx = x2 - x1; dy = y2 - y1
    fx = x1 - cx; fy = y1 - cy
    a = dx*dx + dy*dy
    if a < 1e-9:
        return (fx*fx + fy*fy) <= r*r
    b = 2.0 * (fx*dx + fy*dy)
    c = fx*fx + fy*fy - r*r
    disc = b*b - 4*a*c
    if disc < 0: return False
    sq = disc ** 0.5
    t1 = (-b - sq) / (2*a)
    t2 = (-b + sq) / (2*a)
    if t2 < 0.0 or t1 > 1.0: return False
    return True


def _seg_blocked_by_buildings(x1, y1, x2, y2, buildings, ignore_kind=None):
    """Есть ли постройка на пути отрезка? Дверь игнорируется,
    если ignore_kind == BUILD_DOOR. Возвращает True/False."""
    half = BARRICADE_GRID / 2
    for b in buildings:
        if ignore_kind is not None and b.get("kind") == ignore_kind: continue
        left = b["x"] - half; top = b["y"] - half
        rw = BARRICADE_GRID; rh = BARRICADE_GRID
        if _seg_rect_hit(x1, y1, x2, y2, left, top, rw, rh):
            return True
    return False

def _first_block_along_segment(x1, y1, x2, y2, buildings, ignore_kind=None, steps=40):
    """Идёт по отрезку шагами, возвращает (x, y) — точку ДО первого
    столкновения с постройкой. Если столкновения нет — возвращает (x2, y2)."""
    for i in range(1, steps + 1):
        t = i / steps
        px = x1 + (x2 - x1) * t
        py = y1 + (y2 - y1) * t
        if _seg_blocked_by_buildings(x1, y1, px, py, buildings, ignore_kind):
            t_prev = (i - 1) / steps
            return x1 + (x2 - x1) * t_prev, y1 + (y2 - y1) * t_prev
    return x2, y2


def is_cheat_line(line):
    ls = line.strip()
    if not ls: return False
    if ls.startswith("/"): return True
    if ls in CHEAT_CODES: return True
    return False


def make_player_dict(cid, color, x, y):
    return {
        "id": cid, "x": x, "y": y, "angle": 0.0,
        "hp": MAX_HP, "name": f"P{cid}", "color": color,
        "dead": False, "respawn_at": 0.0,
        "xp": 0, "level": 0, "coins": 0,
        "weapon": "base", "owned_weapons": ["base"],
        "weapon_slots": ["base", None, None, None, None],
        "inventory": {"apple": 0, "lightning": 0, "minigun": 0, "firedoom": 0, "crazy": 0},
        "forbidden_count": 0,
        "build_inventory": {BUILD_BARRICADE: 0, BUILD_TURRET: 0, BUILD_FIRE_TURRET: 0},
        "build_slot": None,
        "passive_owned": [], "passive": None,
        "prism_shards": 0, "stardust": 0,
        "last_prism_unlocked": False, "true_star_unlocked": False,
        "client_stage": 0, "client_unlocks": [], "client_achievements": [], "client_wins": 0,
        "speed_until": 0.0, "shoot_until": 0.0, "firedoom_until": 0.0,
        "medkit_cd_until": 0.0, "apple_eat_until": 0.0, "apple_eat_start": 0.0,
        "fire_until": 0.0, "fire_next_tick": 0.0,
        "crazy_until": 0.0, "star_counter": 0,
        "euphoria": 0,
        "charge_start": 0.0,
        "melee_until": 0.0, "melee_angle": 0.0,
        "multi_hit_queue": [], "frozen_until": 0.0,
        "laser_until": 0.0, "laser_angle": 0.0, "laser_next_tick": 0.0,
        "wanish": False,
        "is_admin_for_session": False,
        "chat_text": "", "chat_until": 0.0,
        "choosing_weapon": True,
        "no_stats": False,
    }


class Host:
    def __init__(self, port=DEFAULT_PORT, name="Хост", mode=MODE_NORMAL,
                 difficulty=DIFF_NORMAL, cheats=False, stage=0,
                 host_achievements=None, solo=False, host_wins=0,
                 host_unlocks=None, save_snapshot=None):
        self.port = port; self.name = name
        self.mode = mode; self.difficulty = difficulty
        self.cheats_enabled = cheats; self.stage = stage
        self.max_wave = 999999 if difficulty == DIFF_ENDLESS else stage_max_wave(stage)
        self.host_achievements = set(host_achievements or [])
        self.host_wins = int(host_wins); self.solo = solo
        self.host_unlocks = list(host_unlocks or [])
        mods = DIFFICULTY_MODS[difficulty]
        self.hp_mult = mods["hp_mult"]; self.dmg_mult = mods["dmg_mult"]
        self.speed_mult = mods["speed_mult"]; self.count_mult = mods["count_mult"]
        self.reward_mult = mods["reward_mult"]
        self.lock = threading.RLock()
        self.clients = {}; self.players = {}
        self.bullets = []; self.zombies = []; self.spitter_bullets = []
        self.final_boss_bullets = []
        self.puddles = []
        self.buildings = []; self.building_cells = set()
        self.crates = []; self.damage_popups = []
        self.meteors = []; self.lasers = []; self.turret_bullets = []
        self.electric_turret_bullets = []
        self.forbidden_items = []
        self.prism_shards = []; self.stardust_items = []
        self.next_prism_id = 1; self.next_stardust_id = 1
        self.next_id = 1; self.next_zombie_id = 1
        self.next_building_id = 1; self.next_crate_id = 1; self.next_forbidden_id = 1
        self.running = True
        self.admin_cid = None; self.youcant_used = set()
        self.wave = 0; self.wave_state = "break"
        self.wave_break_until = time.time() + 99999
        self.wave_spawn_left = 0; self.wave_next_spawn_at = 0.0
        self.wave_killed = 0; self.wave_total = 0
        self.victory = False; self.game_over = False
        self.session_had_other_clients = False
        self.wave_first_zombie_id = None
        self.achievements_earned_this_session = []
        self.wave_button_active = True
        self.wave_button_x = MAP_W / 2
        self.wave_button_y = MAP_H / 2
        # === ХАОС ===
        self.builds_by_player = {}
        self.crystal = None
        self.crystal_next_hit = 0.0
        self.bosses_killed_this_session = 0
        self.local_cid = None
        self.local_events = []
        self.server_code = str(random.randint(10000, 99999))
        # === МОДЫ ===
        self.mods_info = []
        try:
            _s = load_settings()
            _enabled_ids = list(_s.get("enabled_mods", []))
        except Exception:
            _enabled_ids = []
        if _enabled_ids:
            try:
                _found, _loaded = load_all_mods(_enabled_ids)
                MOD_API.register(_loaded)
                for _m in _loaded:
                    self.mods_info.append({"id": _m["id"], "name": _m["name"],
                                           "description": _m["description"],
                                           "sha256": _m["sha256"]})
                if _loaded:
                    _start_api = _make_mod_api_proxy(self)
                MOD_API.call("on_start", self, _start_api)
            except Exception as _e:
                print("[mods] ошибка загрузки:", _e)
        with self.lock:
            cid = self.next_id; self.next_id += 1
            color = self._pick_free_color()
            x, y = self._spawn()
            p = make_player_dict(cid, color, x, y)
            p["choosing_weapon"] = True
            p["is_admin_for_session"] = True
            self.players[cid] = p
            self.local_cid = cid
            self.admin_cid = cid
        # === ХАОС: если режим кристалла — спавним сразу ===
        if self.mode == MODE_CRYSTAL and self.crystal is None:
            self.crystal = {"x": MAP_W / 2, "y": MAP_H / 2, "vx": 0.0, "vy": 0.0,
                            "hp": CRYSTAL_HP, "max_hp": CRYSTAL_HP}        # === СОЛО: применяем снапшот, если передан ===
        self.solo_save_timer = 0.0
        if save_snapshot is not None:
            try:
                self._apply_solo_snapshot(save_snapshot)
                print("[solo_save] мир загружен")
            except Exception as e:
                print("[solo_save] ошибка применения снапшота:", e)
                traceback.print_exc()

        if not self.solo:
            self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.srv.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.srv.bind(("0.0.0.0", port)); self.srv.listen(32)
            threading.Thread(target=self._accept_loop, daemon=True).start()
            threading.Thread(target=self._announce_loop, daemon=True).start()
        else:
            self.srv = None
        threading.Thread(target=self._tick_loop, daemon=True).start()

    def local_send(self, msg):
        self._handle(self.local_cid, msg)

    def drain_local_events(self):
        with self.lock:
            out = self.local_events[:]
            self.local_events.clear()
        return out

    def start_console(self):
        threading.Thread(target=self._console_loop, daemon=True).start()

    def _console_loop(self):
        while self.running:
            try: line = input()
            except (EOFError, KeyboardInterrupt): return
            except Exception: continue
            if not line: continue
            self._execute_console_command(line, from_cid=None)

    def _execute_console_command(self, line, from_cid=None):
        line = line.strip()
        if not line: return
        if line in CHEAT_CODES:
            self._handle_cheat_code(line, from_cid); return
        if line.startswith("/"):
            if not self.cheats_enabled: return
            if from_cid is not None and from_cid != self.admin_cid: return
            parts = line[1:].split()
            if not parts: return
            cmd = parts[0].lower()
            try:
                if cmd == "xp": self._cmd_xp(parts[1:], from_cid)
                elif cmd == "coins": self._cmd_coins(parts[1:], from_cid)
                elif cmd == "hp": self._cmd_hp(parts[1:], from_cid)
                elif cmd == "weapon": self._cmd_weapon(parts[1:], from_cid)
                elif cmd == "give": self._cmd_give(parts[1:], from_cid)
                elif cmd == "wave": self._cmd_wave(parts[1:])
                elif cmd == "wanish": self._cmd_wanish(parts[1:], from_cid)
                elif cmd == "help":
                    print("команды: /xp /coins /hp /weapon /give /wave /wanish")
            except Exception as e: print(f"ошибка: {e}")
            _tgt = from_cid if from_cid is not None else self.local_cid
            if _tgt is not None:
                self._send(_tgt, {"type": "cheat_used"})
            return
        target_cid = from_cid if from_cid is not None else self.admin_cid
        text = line[:CHAT_MAX_LEN]
        with self.lock:
            pl = self.players.get(target_cid)
            if pl:
                pl["chat_text"] = text; pl["chat_until"] = time.time() + CHAT_DURATION

    def _resolve_targets(self, cname, from_cid):
        cname = cname.lower()
        if cname == "all":
            with self.lock: return list(self.players.keys()), None
        if cname == "me":
            if from_cid is None: return [], "me без cid"
            with self.lock:
                if from_cid in self.players: return [from_cid], None
            return [], "не найден"
        target = None
        for name, c in COLOR_NAMES:
            if name == cname: target = c; break
        if target is None: return [], "нет цвета"
        with self.lock:
            for pid, pl in self.players.items():
                if tuple(pl["color"]) == tuple(target): return [pid], None
        return [], "не найден"

    def _parse_int(self, s):
        try: return int(s), None
        except Exception: return None, "нужно число"

    def _cmd_xp(self, args, from_cid=None):
        if len(args) != 3: return
        color, action, val_s = args
        val, err = self._parse_int(val_s)
        if err: return
        tids, err = self._resolve_targets(color, from_cid)
        if err: return
        with self.lock:
            for pid in tids:
                pl = self.players.get(pid)
                if not pl: continue
                if action == "add": pl["xp"] = max(0, pl["xp"] + val)
                elif action == "set": pl["xp"] = max(0, val)
                elif action == "del": pl["xp"] = max(0, pl["xp"] - val)
                pl["level"] = level_from_xp(pl["xp"])

    def _cmd_coins(self, args, from_cid=None):
        if len(args) != 3: return
        color, action, val_s = args
        val, err = self._parse_int(val_s)
        if err: return
        tids, err = self._resolve_targets(color, from_cid)
        if err: return
        with self.lock:
            for pid in tids:
                pl = self.players.get(pid)
                if not pl: continue
                if action == "add": pl["coins"] = max(0, pl["coins"] + val)
                elif action == "set": pl["coins"] = max(0, val)
                elif action == "del": pl["coins"] = max(0, pl["coins"] - val)

    def _cmd_hp(self, args, from_cid=None):
        if len(args) != 3: return
        color, action, val_s = args
        val, err = self._parse_int(val_s)
        if err: return
        tids, err = self._resolve_targets(color, from_cid)
        if err: return
        with self.lock:
            for pid in tids:
                pl = self.players.get(pid)
                if not pl: continue
                if action == "add": pl["hp"] = min(MAX_HP, max(0, pl["hp"] + val))
                elif action == "set": pl["hp"] = min(MAX_HP, max(0, val))
                elif action == "del": pl["hp"] = max(0, pl["hp"] - val)
                if pl["hp"] <= 0 and not pl["dead"]:
                    pl["dead"] = True; pl["respawn_at"] = time.time() + RESPAWN_DELAY
                    pl["xp"] = 0; pl["level"] = 0
                    self._send_stats(pl["id"], {"type": "death"})
                    MOD_API.call("on_player_death", self, pl)

    def _cmd_weapon(self, args, from_cid=None):
        if len(args) != 3: return
        color, action, wid = args; wid = wid.lower()
        if wid not in ARSENAL: return
        tids, err = self._resolve_targets(color, from_cid)
        if err: return
        with self.lock:
            for pid in tids:
                pl = self.players.get(pid)
                if not pl: continue
                if action == "add":
                    if wid not in pl["owned_weapons"]:
                        pl["owned_weapons"].append(wid)
                        self._assign_to_first_free_slot(pl, wid)
                elif action == "del":
                    if wid == "base": continue
                    if wid in pl["owned_weapons"]:
                        pl["owned_weapons"].remove(wid)
                        for i, k in enumerate(pl["weapon_slots"]):
                            if k == wid: pl["weapon_slots"][i] = None
                        if pl["weapon"] == wid: pl["weapon"] = "base"

    def _assign_to_first_free_slot(self, pl, wid):
        slots = pl.get("weapon_slots")
        if slots is None: return
        for i in range(MAX_WEAPON_SLOTS):
            if slots[i] is None: slots[i] = wid; return

    def _cmd_give(self, args, from_cid=None):
        if len(args) != 3: return
        color, item, val_s = args; item = item.lower()
        if item not in SHOP_BUFFS: return
        val, err = self._parse_int(val_s)
        if err: return
        tids, err = self._resolve_targets(color, from_cid)
        if err: return
        with self.lock:
            for pid in tids:
                pl = self.players.get(pid)
                if not pl: continue
                cur = pl["inventory"].get(item, 0)
                pl["inventory"][item] = max(0, cur + val)

    def _cmd_wanish(self, args, from_cid=None):
        if len(args) != 1: return
        tids, err = self._resolve_targets(args[0], from_cid)
        if err: return
        with self.lock:
            for pid in tids:
                pl = self.players.get(pid)
                if not pl: continue
                pl["wanish"] = not pl.get("wanish", False)

    def _cmd_wave(self, args):
        if not args: return
        if args[0] == "skip":
            with self.lock:
                self.zombies.clear(); self.spitter_bullets.clear(); self.puddles.clear()
                self.wave_spawn_left = 0; self.wave_state = "break"; self.wave_break_until = time.time() + 99999
                self.wave_button_active = True
                for pl in self.players.values():
                    if not pl["dead"]: pl["hp"] = MAX_HP
            return
        if args[0] == "set" and len(args) == 2:
            try: n = int(args[1])
            except Exception: return
            with self.lock:
                self.wave = max(0, n - 1); self.zombies.clear()
                self.wave_spawn_left = 0; self.wave_state = "break"
                self.wave_break_until = time.time() + 99999
                self.wave_button_active = True

    def _handle_cheat_code(self, code, cid):
        if code == "ALLDUST31":
            if cid is None: cid = self.admin_cid
            with self.lock:
                pl = self.players.get(cid)
                if pl: pl["is_admin_for_session"] = True
            if cid is not None:
                self._send(cid, {"type": "cheat_used"})
        elif code == "FCKGRAYFRICK":
            if cid is None: cid = self.admin_cid
            with self.lock:
                pl = self.players.get(cid)
                if pl: pl["hp"] = MAX_HP
            if cid is not None:
                self._send(cid, {"type": "cheat_used"})
        elif code == "YOUCANT":
            if cid is None: cid = self.admin_cid
            with self.lock:
                if cid in self.youcant_used: return
                pl = self.players.get(cid)
                if not pl: return
                pl["xp"] += 50000; pl["level"] = level_from_xp(pl["xp"])
                pl["coins"] += 100000; self.youcant_used.add(cid)
            if cid is not None:
                self._send(cid, {"type": "cheat_used"})

    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.srv.accept()
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError: return
            except Exception: time.sleep(0.05); continue
            threading.Thread(target=self._client_loop, args=(sock, addr), daemon=True).start()

    def _pick_free_color(self):
        used = {tuple(p["color"]) for p in self.players.values()}
        free = [c for c in PLAYER_COLORS if tuple(c) not in used]
        if not free: return None
        return list(random.choice(free))

    def _client_loop(self, sock, addr):
        client_stage = 0; client_unlocks = []; client_achievements = []; client_wins = 0
        try:
            sock.settimeout(5.0)
            buf = bytearray()
            while len(buf) < 4:
                d = sock.recv(4096)
                if not d: sock.close(); return
                buf.extend(d)
            L = int.from_bytes(buf[:4], "big")
            while len(buf) < 4 + L:
                d = sock.recv(4096)
                if not d: sock.close(); return
                buf.extend(d)
            hello = json.loads(bytes(buf[4:4+L]).decode("utf-8"))
            client_stage = int(hello.get("stage", 0))
            client_wins = int(hello.get("wins", 0))
            cu = hello.get("unlocks", [])
            if isinstance(cu, list): client_unlocks = [str(x) for x in cu]
            ca = hello.get("achievements", [])
            if isinstance(ca, list): client_achievements = [str(x) for x in ca]
            sock.settimeout(None)
        except Exception:
            try: sock.close()
            except Exception: pass
            return
        if client_stage < self.stage:
            try: sock.sendall(encode({"type": "no_stage", "need": self.stage, "you": client_stage}))
            except Exception: pass
            try: sock.close()
            except Exception: pass
            return
        with self.lock:
            if len(self.players) >= MAX_PLAYERS:
                try: sock.sendall(encode({"type": "server_full"}))
                except Exception: pass
                try: sock.close()
                except Exception: pass
                return
            cid = self.next_id; self.next_id += 1
            self.clients[cid] = {"sock": sock, "buf": bytearray(), "out": queue.Queue(maxsize=400)}
            color = self._pick_free_color()
            x, y = self._spawn()
            p = make_player_dict(cid, color, x, y)
            p["client_stage"] = client_stage
            p["client_unlocks"] = client_unlocks
            p["client_achievements"] = client_achievements
            p["client_wins"] = client_wins
            if client_stage > self.stage:
                p["no_stats"] = True
            self.players[cid] = p
            if cid != self.admin_cid and self.admin_cid is not None:
                self.session_had_other_clients = True
            snapshot = dict(self.players[cid])
        try:
            sock.sendall(encode({"type": "welcome", "id": cid, "map": [MAP_W, MAP_H],
                                  "is_admin": False,
                                  "mode": self.mode, "difficulty": self.difficulty,
                                  "cheats": self.cheats_enabled,
                                  "no_stats": client_stage > self.stage,
                                  "stage": self.stage, "max_wave": self.max_wave,
                                  "wins": self.host_wins, "solo": self.solo,
                                  "mods": list(self.mods_info)}))
        except Exception:
            self._drop(cid); return
        self._send(cid, {"type": "join", "player": snapshot})
        MOD_API.call("on_player_join", self, self.players[cid])
        threading.Thread(target=self._sender_loop, args=(cid,), daemon=True).start()
        try:
            while self.running:
                data = sock.recv(16384)
                if not data: break
                buf = self.clients[cid]["buf"]; buf.extend(data)
                try: msgs = decode_from_buffer(buf)
                except Exception as e:
                    print("[host] decode error:", e); buf.clear(); continue
                for msg in msgs: self._handle(cid, msg)
        except Exception: pass
        finally:
            with self.lock:
                if cid != self.admin_cid: self.session_had_other_clients = True
            self._drop(cid)

    def _sender_loop(self, cid):
        while self.running:
            with self.lock: c = self.clients.get(cid)
            if not c: return
            try: data = c["out"].get(timeout=0.5)
            except queue.Empty: continue
            try: c["sock"].sendall(data)
            except Exception: self._drop(cid); return

    def _send_stats(self, cid, msg):
        """Отправляет сообщение только если у игрока не стоит флаг no_stats.
        Используется для kill / death / win / achievement."""
        with self.lock:
            p = self.players.get(cid)
            if p and p.get("no_stats"):
                return
        self._send(cid, msg)

    def _send(self, cid, msg):
        if cid == self.local_cid:
            with self.lock: self.local_events.append(msg)
            return
        try: data = encode(msg)
        except Exception: return
        with self.lock: c = self.clients.get(cid)
        if not c: return
        try: c["out"].put_nowait(data)
        except queue.Full: pass

    def _broadcast(self, msg):
        with self.lock: self.local_events.append(msg)
        try: data = encode(msg)
        except Exception: return
        with self.lock: targets = list(self.clients.values())
        for c in targets:
            try: c["out"].put_nowait(data)
            except queue.Full: pass

    def _drop(self, cid):
        if cid == self.local_cid: return
        with self.lock:
            c = self.clients.pop(cid, None)
            if c:
                try: c["sock"].close()
                except Exception: pass
            self.players.pop(cid, None)
            self.youcant_used.discard(cid)
            if self.admin_cid == cid: self.admin_cid = None
        self._broadcast({"type": "leave", "id": cid})

    def _spawn(self):
        for _ in range(50):
            ang = random.uniform(0, math.tau)
            rad = random.uniform(200, min(MAP_W, MAP_H) / 2 - 100)
            x = MAP_W / 2 + math.cos(ang) * rad; y = MAP_H / 2 + math.sin(ang) * rad
            if 50 <= x <= MAP_W - 50 and 50 <= y <= MAP_H - 50: return x, y
        return 200, 200

    def _add_euphoria(self, p, amount, now=None):
        """Прибавляет эйфорию игроку, если у него активна пассивка казуал.
        При достижении 100 — запускает безумие на 10 сек и сбрасывает."""
        if not p: return
        if p.get("passive") != "казуал": return
        if now is None: now = time.time()
        p["euphoria"] = p.get("euphoria", 0) + amount
        if p["euphoria"] >= 100:
            p["euphoria"] = 0
            # Безумие: то же поле, что и у предмета "crazy", только на 10 сек
            p["crazy_until"] = max(p.get("crazy_until", 0), now) + 10.0
            p["_euphoria_burst"] = True  # для попапа/визуала
            self._popup(p["x"], p["y"] - PLAYER_R - 20, "ЭЙФОРИЯ!", (255, 100, 255))
    # ============================================================
    #  СОЛО: сериализация и применение снапшота
    # ============================================================
    def _serialize_solo(self):
        """Возвращает dict полного состояния мира для сохранения."""
        with self.lock:
            # копируем словари игроков через dict() — чтобы json смог сериализовать
            players_copy = {str(pid): dict(pl) for pid, pl in self.players.items()}
            return {
                "settings": {
                    "mode": self.mode, "difficulty": self.difficulty,
                    "stage": self.stage, "cheats_enabled": self.cheats_enabled,
                    "host_achievements": list(self.host_achievements),
                    "host_wins": self.host_wins,
                },
                "world": {
                    "wave": self.wave, "wave_state": self.wave_state,
                    "wave_break_until": self.wave_break_until,
                    "wave_spawn_left": self.wave_spawn_left,
                    "wave_next_spawn_at": self.wave_next_spawn_at,
                    "wave_killed": self.wave_killed, "wave_total": self.wave_total,
                    "victory": self.victory, "game_over": self.game_over,
                    "session_had_other_clients": self.session_had_other_clients,
                    "wave_first_zombie_id": self.wave_first_zombie_id,
                    "achievements_earned_this_session": list(self.achievements_earned_this_session),
                    "wave_button_active": self.wave_button_active,
                    "wave_button_x": self.wave_button_x,
                    "wave_button_y": self.wave_button_y,
                    "youcant_used": list(self.youcant_used),
                    "next_id": self.next_id,
                    "next_zombie_id": self.next_zombie_id,
                    "next_building_id": self.next_building_id,
                    "next_crate_id": self.next_crate_id,
                    "next_forbidden_id": self.next_forbidden_id,
                    "next_prism_id": self.next_prism_id,
                    "next_stardust_id": self.next_stardust_id,
                },
                "players": players_copy,
                "zombies": list(self.zombies),
                "buildings": list(self.buildings),
                "building_cells": [list(c) for c in self.building_cells],
                "bullets": list(self.bullets),
                "turret_bullets": list(self.turret_bullets),
                "spitter_bullets": list(self.spitter_bullets),
                "final_boss_bullets": list(self.final_boss_bullets),
                "puddles": list(self.puddles),
                "meteors": list(self.meteors),
                "damage_popups": list(self.damage_popups),
                "crates": list(self.crates),
                "forbidden_items": list(self.forbidden_items),
                "prism_shards": list(self.prism_shards),
                "stardust_items": list(self.stardust_items),
            }

    def _apply_solo_snapshot(self, snap):
        """Восстанавливает мир из снапшота. Вызывается под локом."""
        if not isinstance(snap, dict): return
        st = snap.get("settings", {})
        if st:
            self.mode = st.get("mode", self.mode)
            self.difficulty = st.get("difficulty", self.difficulty)
            self.stage = st.get("stage", self.stage)
            self.cheats_enabled = st.get("cheats_enabled", self.cheats_enabled)
            self.host_achievements = set(st.get("host_achievements", list(self.host_achievements)))
            self.host_wins = int(st.get("host_wins", self.host_wins))
            self.max_wave = stage_max_wave(self.stage)
            mods = DIFFICULTY_MODS.get(self.difficulty, DIFFICULTY_MODS[DIFF_NORMAL])
            self.hp_mult = mods["hp_mult"]; self.dmg_mult = mods["dmg_mult"]
            self.speed_mult = mods["speed_mult"]; self.count_mult = mods["count_mult"]
            self.reward_mult = mods["reward_mult"]

        w = snap.get("world", {})
        if w:
            self.wave = int(w.get("wave", self.wave))
            self.wave_state = str(w.get("wave_state", self.wave_state))
            self.wave_break_until = float(w.get("wave_break_until", self.wave_break_until))
            self.wave_spawn_left = int(w.get("wave_spawn_left", self.wave_spawn_left))
            self.wave_next_spawn_at = float(w.get("wave_next_spawn_at", self.wave_next_spawn_at))
            self.wave_killed = int(w.get("wave_killed", self.wave_killed))
            self.wave_total = int(w.get("wave_total", self.wave_total))
            self.victory = bool(w.get("victory", self.victory))
            self.game_over = bool(w.get("game_over", self.game_over))
            self.session_had_other_clients = bool(w.get("session_had_other_clients", self.session_had_other_clients))
            self.wave_first_zombie_id = w.get("wave_first_zombie_id", self.wave_first_zombie_id)
            self.achievements_earned_this_session = list(w.get("achievements_earned_this_session", []))
            self.wave_button_active = bool(w.get("wave_button_active", self.wave_button_active))
            self.wave_button_x = float(w.get("wave_button_x", self.wave_button_x))
            self.wave_button_y = float(w.get("wave_button_y", self.wave_button_y))
            self.youcant_used = set(w.get("youcant_used", []))
            self.next_id = int(w.get("next_id", self.next_id))
            self.next_zombie_id = int(w.get("next_zombie_id", self.next_zombie_id))
            self.next_building_id = int(w.get("next_building_id", self.next_building_id))
            self.next_crate_id = int(w.get("next_crate_id", self.next_crate_id))
            self.next_forbidden_id = int(w.get("next_forbidden_id", self.next_forbidden_id))
            self.next_prism_id = int(w.get("next_prism_id", self.next_prism_id))
            self.next_stardust_id = int(w.get("next_stardust_id", self.next_stardust_id))

        # Игроки: восстанавливаем ПОЛНОСТЬЮ только локального.
        # Сетевые клиенты при загрузке соло-сейва отсутствуют (соло — значит один).
        players = snap.get("players", {})
        if players and self.local_cid is not None:
            saved_local = players.get(str(self.local_cid))
            if saved_local is None:
                # если id сместился — берём первого попавшегося
                saved_local = next(iter(players.values()), None)
            if saved_local is not None:
                base = make_player_dict(self.local_cid, self._pick_free_color(),
                                        saved_local.get("x", MAP_W/2), saved_local.get("y", MAP_H/2))
                base.update(saved_local)
                base["id"] = self.local_cid
                base["is_admin_for_session"] = True
                base["client_stage"] = self.stage
                self.players[self.local_cid] = base
                self.admin_cid = self.local_cid

        # Зомби / постройки / прочее — прямое присваивание
        self.zombies = list(snap.get("zombies", []))
        self.buildings = list(snap.get("buildings", []))
        try:
            self.building_cells = set(tuple(c) for c in snap.get("building_cells", []))
        except Exception:
            self.building_cells = set()
        self.bullets = list(snap.get("bullets", []))
        self.turret_bullets = list(snap.get("turret_bullets", []))
        self.spitter_bullets = list(snap.get("spitter_bullets", []))
        self.final_boss_bullets = list(snap.get("final_boss_bullets", []))
        self.puddles = list(snap.get("puddles", []))
        self.meteors = list(snap.get("meteors", []))
        self.damage_popups = list(snap.get("damage_popups", []))
        self.crates = list(snap.get("crates", []))
        self.forbidden_items = list(snap.get("forbidden_items", []))
        self.prism_shards = list(snap.get("prism_shards", []))
        self.stardust_items = list(snap.get("stardust_items", []))

        # dash_hit_players был set — json вернул list; восстановим
        for z in self.zombies:
            if isinstance(z.get("dash_hit_players"), list):
                z["dash_hit_players"] = set(z["dash_hit_players"])
            elif z.get("dash_hit_players") is None:
                z["dash_hit_players"] = set()

    # ============================================================
    #  УНИВЕРСАЛЬНЫЙ ХЕЛПЕР УБИЙСТВА ЗОМБИ
    #  Все места, где зомби умирает, вызывают его — чтобы не было
    #  8 копий логики "награда → дроп → достижение → эйфория → смерть".
    # ============================================================

    def _pvp_hit_player(self, shooter_id, target_pl, dmg, now):
        """PvP: наносит урон игроку от пули другого игрока.
        Возвращает True, если цель умерла."""
        if target_pl is None: return False
        if target_pl.get("dead"): return False
        if target_pl.get("wanish"): return False
        if target_pl.get("choosing_weapon"): return False
        # щит снижает урон
        d = dmg
        if target_pl.get("weapon") == "shield":
            d = int(d * (1 - SHIELD_DMG_REDUCTION))
        if d < 1: d = 1
        target_pl["hp"] = max(0, target_pl["hp"] - d)
        self._popup(target_pl["x"], target_pl["y"] - PLAYER_R - 10, d, (255, 80, 80))
        if target_pl["hp"] <= 0 and not target_pl["dead"]:
            target_pl["dead"] = True
            target_pl["respawn_at"] = now + RESPAWN_DELAY
            target_pl["xp"] = 0; target_pl["level"] = 0
            self._send_stats(target_pl["id"], {"type": "death"})
            # награда убийце — как за босса
            shooter = self.players.get(shooter_id)
            if shooter is not None and shooter is not target_pl:
                rw = int(zombie_reward(self.wave) * self.reward_mult * 10)
                shooter["coins"] += rw
                shooter["xp"] += rw
                shooter["level"] = level_from_xp(shooter["xp"])
                self._send_stats(shooter_id, {"type": "kill", "boss": False})
            return True
        return False

    def _zombie_take_damage(self, z, dmg, now):
        """Единая точка урона по зомби. Учитывает горение (×FIRE_VULN_MULT).
        Возвращает True, если зомби умер (HP <= 0)."""
        mult = 1.0
        if z.get("fire_until", 0) > now:
            mult *= FIRE_VULN_MULT
        z["hp"] -= dmg * mult
        return z["hp"] <= 0
    def _on_zombie_killed(self, z, killer_id, weapon_key=None, from_source="unknown"):
        MOD_API.call("on_kill", self, z, killer_id)
        if z.get("boss") or z.get("final") or z.get("stage50"):
            MOD_API.call("on_boss_killed", self, z, killer_id)
        """Единая точка обработки смерти зомби.
        MOD_API.call("on_kill", self, z, killer_id)
        if z.get("boss") or z.get("final") or z.get("stage50"):
            MOD_API.call("on_boss_killed", self, z, killer_id)
        z — словарь зомби (должен ещё быть в self.zombies, если хочется чтоб _kill_zombie сработал);
        killer_id — cid игрока-убийцы (может быть None, тогда награда не начисляется);
        weapon_key — строка оружия для _maybe_drop_special / баф-дропа (может быть None);
        from_source — для отладки, в лог не пишется."""
        reward = int(zombie_reward(self.wave) * self.reward_mult)
        shooter = self.players.get(killer_id) if killer_id is not None else None
        if shooter is not None:
            if z.get("boss", False) and not z.get("final", False) and not z.get("stage50", False):
                self.bosses_killed_this_session += 1
            # === Гексагон: убил stage50-босса — открыт ===
            if z.get("stage50", False):
                _app = getattr(self, "_app_ref", None)
                if _app is not None:
                    try:
                        ul = set(_app.trophies.get("unlocks", []))
                        if "hexagon_unlocked" not in ul:
                            ul.add("hexagon_unlocked")
                            _app.trophies["unlocks"] = list(ul)
                            save_gamestate(_app.trophies)
                            _app.info_msg = "★ Открыт Гексагон! ★"
                            _app.info_msg_until = time.time() + 5.0
                    except Exception: pass
                _app = getattr(self, "_app_ref", None)
                if _app is not None:
                    try:
                        _app.trophies["bosses_killed"] = int(_app.trophies.get("bosses_killed", 0)) + 1
                        if _app.trophies["bosses_killed"] >= 5:
                            ul = set(_app.trophies.get("unlocks", []))
                            if UNLOCK_ENDLESS not in ul:
                                ul.add(UNLOCK_ENDLESS)
                                _app.trophies["unlocks"] = list(ul)
                                _app.info_msg = "★ Открыт режим «Бесконечный»! ★"
                                _app.info_msg_until = time.time() + 5.0
                        save_gamestate(_app.trophies)
                    except Exception: pass
            xr = z.get("xp_reward", reward)
            xc = self._coins_reward(z) if z.get("coins_reward") else reward
            _xc = MOD_API.call("modify_coin_reward", self, z, xc)
            if _xc:
                for _v in _xc:
                    if isinstance(_v, (int, float)) and _v >= 0:
                        xc = int(_v); break
            _xr = MOD_API.call("modify_xp_reward", self, z, xr)
            if _xr:
                for _v in _xr:
                    if isinstance(_v, (int, float)) and _v >= 0:
                        xr = int(_v); break
            shooter["xp"] += xr
            shooter["coins"] += xc
            shooter["level"] = level_from_xp(shooter["xp"])
        if killer_id is not None:
            self._send_stats(killer_id, {"type": "kill", "boss": z.get("boss", False)})
        self._maybe_forbidden_drop(z, killer_id)
        self._check_not_funny_on_kill(z)
        if weapon_key is not None:
            self._maybe_drop_special(z, killer_id, weapon_key)
            if weapon_key == "base":
                self._maybe_drop_buff_from_zombie(z, killer_id, time.time())
        _e = 10 if z.get("boss", False) else 1
        self._add_euphoria(shooter, _e)
        if z.get("kind") == "kamikaze" and not z.get("_exploded"):
            self._kamikaze_explode(z["x"], z["y"], time.time())
        if z.get("kind") == "infected":
            self._spawn_infected_puddle(z["x"], z["y"], time.time())
        self._kill_zombie(z)


    def _popup(self, x, y, val, color=(255, 255, 255)):
        self.damage_popups.append({"x": x, "y": y, "v": val, "t": 0.0, "life": 0.9, "color": color})

    def _electric_chain(self, source, owner_id):
        """Молния от убитого зомби в ELECTRIC_CHAIN_COUNT ближайших."""
        candidates = []
        for z in self.zombies:
            if z is source or z.get("charmed"): continue
            d = math.hypot(z["x"] - source["x"], z["y"] - source["y"])
            if d <= ELECTRIC_CHAIN_RANGE:
                candidates.append((d, z))
        candidates.sort(key=lambda x: x[0])
        for _, z in candidates[:ELECTRIC_CHAIN_COUNT]:
            died = self._zombie_take_damage(z, ELECTRIC_CHAIN_DMG, now)
            zr = z.get("r", ZOMBIE_R)
            self._popup(z["x"], z["y"] - zr - 10, ELECTRIC_CHAIN_DMG, (150, 200, 255))
            if died:
                self._on_zombie_killed(z, owner_id, None, "electric_chain")

    def _maybe_drop_buff_from_zombie(self, z, owner_id, now):
        """10% шанс, что при убийстве зомби выпадет случайный расходник."""
        if random.random() >= 0.1: return
        keys = list(SHOP_BUFFS.keys())
        if not keys: return
        bkey = random.choice(keys)
        self.crates.append({
            "id": self.next_crate_id, "x": z["x"], "y": z["y"],
            "rarity": "rare", "color": [220, 200, 60],
            "buffs": [bkey], "coins": 0, "xp": 0,
        })
        self.next_crate_id += 1
        # +10 эйфории за выпавший баф
        shooter = self.players.get(owner_id)
        self._add_euphoria(shooter, 10, now)

    def _damage_building(self, b, dmg, now):
        """Наносит урон постройке. Если hp <= 0 — удаляет её."""
        b["hp"] -= dmg
        half = BARRICADE_GRID / 2
        self._popup(b["x"], b["y"] - half - 10, dmg, (255, 220, 80))
        if b["hp"] <= 0:
            try:
                self.buildings.remove(b)
                self.building_cells.discard((b["gx"], b["gy"]))
            except ValueError:
                pass
            MOD_API.call("on_build_destroyed", self, b)
            return True
        return False

    def _kill_zombie(self, z):
        """Безопасно удаляет зомби, если он ещё в списке.
        Защита от ValueError при двойном убийстве."""
        try:
            self.zombies.remove(z)
            self.wave_killed += 1
            return True
        except ValueError:
            return False
    def _coins_reward(self, z):
        base = z.get("coins_reward", 0)
        return base * 20 if z.get("golden") else base


    def _handle_mod_request(self, cid, msg):
        """Отдаёт файл мода только если он зарегистрирован в self.mods_info.
        Никаких запросов «дай любой мод по имени» — только те, что
        реально загружены сервером."""
        mid = msg.get("id") or msg.get("name")
        if not isinstance(mid, str) or not mid:
            return
        target = None
        for m in getattr(self, "mods_info", []):
            if m.get("id") == mid or m.get("name") == mid:
                target = m; break
        if target is None:
            self._send(cid, {"type": "mod_error", "id": mid, "reason": "not_registered"})
            return
        # путь должен быть внутри addon/ и без ../
        try:
            base = os.path.abspath(ADDON_DIR)
            root = os.path.abspath(os.path.join(base, target["id"]))
            if not (root == base or root.startswith(base + os.sep)):
                self._send(cid, {"type": "mod_error", "id": mid, "reason": "bad_path"})
                return
            # ищем актуальный путь по discover_mods
            mod = None
            for mm in discover_mods():
                if mm["id"] == target["id"]:
                    mod = mm; break
            if mod is None:
                self._send(cid, {"type": "mod_error", "id": mid, "reason": "gone"})
                return
            script_path = os.path.abspath(os.path.join(mod["dir"], mod["script"]))
            if not (script_path == root or script_path.startswith(root + os.sep)):
                self._send(cid, {"type": "mod_error", "id": mid, "reason": "bad_path"})
                return
            with open(script_path, "r", encoding="utf-8") as f:
                script = f.read()
            import hashlib as _hl
            sha = _hl.sha256(script.encode("utf-8")).hexdigest()
            if sha != mod["sha256"]:
                self._send(cid, {"type": "mod_error", "id": mid, "reason": "sha_changed"})
                return
        except Exception as e:
            self._send(cid, {"type": "mod_error", "id": mid, "reason": str(e)})
            return
        self._send(cid, {
            "type": "mod_file", "id": mod["id"], "name": mod["name"],
            "description": mod["description"],
            "script": script, "sha256": sha,
        })

    def _handle(self, cid, msg):
        t = msg.get("type")
        if t == "input":
            with self.lock:
                p = self.players.get(cid)
                if not p or p["dead"] or p.get("choosing_weapon"): return
                new_x = max(PLAYER_R, min(MAP_W - PLAYER_R, msg.get("x", p["x"])))
                new_y = max(PLAYER_R, min(MAP_H - PLAYER_R, msg.get("y", p["y"])))
                ox, oy = p["x"], p["y"]
                # если отрезок (ox,oy)->(new_x,new_y) пересекает постройку — не пускаем
                if (ox != new_x or oy != new_y) and self.buildings:
                    if _seg_blocked_by_buildings(ox, oy, new_x, new_y, self.buildings, BUILD_DOOR):
                        nx2, ny2 = _first_block_along_segment(ox, oy, new_x, new_y, self.buildings, BUILD_DOOR)
                        new_x, new_y = nx2, ny2
                p["x"] = new_x; p["y"] = new_y
                p["angle"] = msg.get("angle", p["angle"])
                self._push_out_of_buildings(p)
        elif t == "shoot":
            with self.lock:
                p = self.players.get(cid)
                if p and p.get("choosing_weapon"): return
            self._handle_shoot(cid, msg)
        elif t == "choose_start_weapon":
            key = msg.get("key")
            if not isinstance(key, str): return
            if key not in ARSENAL and key not in WEAPON_STATS:
                return
            with self.lock:
                p = self.players.get(cid)
                if not p or not p.get("choosing_weapon"): return
                # проверка открытия (используем тот же гейт, что и магазин)
                if key not in ("base", "rifle", "shotgun"):
                    if key == "hexagon":
                        if not ("hexagon_unlocked" in set(p.get("client_unlocks", []))
                                or "hexagon_unlocked" in set(self.host_unlocks or [])):
                            return
                    elif key in CLIENT_WEAPON_GATES:
                        if not self._weapon_allowed_for_player(p, key):
                            return
                    elif key == "last_prism":
                        if not p.get("last_prism_unlocked"): return
                    elif key == "true_star":
                        if not p.get("true_star_unlocked"): return
                p["owned_weapons"] = [key]
                p["weapon_slots"] = [key, None, None, None, None]
                p["weapon"] = key
                p["choosing_weapon"] = False
                x, y = self._spawn()
                p["x"], p["y"] = x, y
        elif t == "buy_weapon": self._handle_buy_weapon(cid, msg)
        elif t == "select_weapon": self._handle_select_weapon(cid, msg)
        elif t == "assign_slot": self._handle_assign_slot(cid, msg)
        elif t == "use_item": self._handle_use_item(cid, msg)
        elif t == "use_forbidden": self._handle_use_forbidden(cid, msg)
        elif t == "buy_buff": self._handle_buy_buff(cid, msg)
        elif t == "buy_build": self._handle_buy_build(cid, msg)
        elif t == "select_build": self._handle_select_build(cid, msg)
        elif t == "place_build": self._handle_place_build(cid, msg)
        elif t == "tool_use":
            gx = msg.get("gx"); gy = msg.get("gy")
            if gx is not None and gy is not None:
                self._try_tool_at_cell(cid, int(gx), int(gy))
        elif t == "drop_weapon": self._handle_drop_weapon(cid, msg)
        elif t == "drop_buff": self._handle_drop_buff(cid, msg)
        elif t == "buy_passive": self._handle_buy_passive(cid, msg)
        elif t == "select_passive": self._handle_select_passive(cid, msg)
        elif t == "console":
            self._execute_console_command(str(msg.get("line", "")), from_cid=cid)
        elif t == "mod_request":
            self._handle_mod_request(cid, msg)
        elif t == "mods_ack":
            pass

    def _weapon_allowed_for_player(self, p, key):
        gate = CLIENT_WEAPON_GATES.get(key)
        if gate is None: return True
        client_unlocks = set(p.get("client_unlocks", []))
        client_ach = set(p.get("client_achievements", []))
        client_wins = int(p.get("client_wins", 0))
        if key == "hexagon":
            # теперь открывается убийством stage50-босса
            return ("hexagon_unlocked" in client_unlocks) or ("hexagon_unlocked" in set(self.host_unlocks or []))
        if key == "cursed_sword":
            return (ACH_HORRORS_OF_PAST in client_ach) or (ACH_HORRORS_OF_PAST in self.host_achievements)
        return gate(client_wins, client_ach) or (key in client_unlocks)

    def _handle_buy_passive(self, cid, msg):
        key = msg.get("key"); info = PASSIVES.get(key)
        if not info: return
        req = info.get("requires_achievement")
        with self.lock:
            p = self.players.get(cid)
            if not p: return
            if req:
                client_ach = set(p.get("client_achievements", []))
                if req not in client_ach and req not in self.host_achievements: return
            if info.get("requires_wave"):
                if int(self.wave) < int(info["requires_wave"]): return
            if key in p.get("passive_owned", []): return
            if p["coins"] < info["price"]: return
            p["coins"] -= info["price"]
            p["passive_owned"].append(key)
            if p.get("passive") is None: p["passive"] = key

    def _handle_select_passive(self, cid, msg):
        key = msg.get("key")
        if key not in PASSIVES: return
        with self.lock:
            p = self.players.get(cid)
            if not p or key not in p.get("passive_owned", []): return
            p["passive"] = None if p.get("passive") == key else key

    def _handle_drop_weapon(self, cid, msg):
        key = msg.get("key")
        if key not in ARSENAL or key == "base": return
        with self.lock:
            p = self.players.get(cid)
            if not p: return
            if key not in p.get("owned_weapons", []): return
            p["owned_weapons"].remove(key)
            for i, k in enumerate(p["weapon_slots"]):
                if k == key: p["weapon_slots"][i] = None
            if p["weapon"] == key: p["weapon"] = "base"
            # === бокс с оружием — рядом с игроком ===
            a = p.get("angle", 0.0)
            bx = max(40, min(MAP_W - 40, p["x"] + math.cos(a) * 80))
            by = max(40, min(MAP_H - 40, p["y"] + math.sin(a) * 80))
            self.crates.append({
                "id": self.next_crate_id, "x": bx, "y": by,
                "rarity": "weapon_drop", "color": [180, 180, 220],
                "buffs": [], "coins": 0, "xp": 0,
                "weapon": key,
            })
            self.next_crate_id += 1

    def _handle_drop_buff(self, cid, msg):
        key = msg.get("key")
        if key not in SHOP_BUFFS: return
        with self.lock:
            p = self.players.get(cid)
            if not p: return
            cur = p["inventory"].get(key, 0)
            if cur <= 0: return
            p["inventory"][key] = cur - 1

    def _handle_buy_build(self, cid, msg):
        key = msg.get("key"); info = BUILD_PRICES.get(key)
        if info is None: return
        with self.lock:
            p = self.players.get(cid)
            if not p or p["coins"] < info: return
            p["coins"] -= info
            p["build_inventory"][key] = p["build_inventory"].get(key, 0) + 1
            if p.get("build_slot") is None: p["build_slot"] = key

    def _handle_select_build(self, cid, msg):
        key = msg.get("key")
        if key not in BUILD_PRICES: return
        with self.lock:
            p = self.players.get(cid)
            if not p or p["build_inventory"].get(key, 0) <= 0: return
            p["build_slot"] = key

    def _count_player_buildings(self, cid, kind):
        return sum(1 for b in self.buildings if b.get("owner") == cid and b.get("kind") == kind)

    def _try_tool_at_cell(self, cid, gx, gy):
        """Тап молотком/ключом по клетке: снести или починить свою постройку."""
        with self.lock:
            p = self.players.get(cid)
            if not p or p["dead"] or p.get("choosing_weapon"): return
            if p.get("frozen_until", 0) > time.time(): return
            weapon = p.get("weapon", "base")
            stats = WEAPON_STATS.get(weapon, {})
            is_hammer = bool(stats.get("hammer"))
            is_wrench = bool(stats.get("wrench"))
            if not (is_hammer or is_wrench): return
            # расстояние до центра клетки — не дальше BARRICADE_RANGE
            cx = gx * BARRICADE_GRID + BARRICADE_GRID / 2
            cy = gy * BARRICADE_GRID + BARRICADE_GRID / 2
            if math.hypot(cx - p["x"], cy - p["y"]) > (BARRICADE_RANGE + 0.5) * BARRICADE_GRID: return
            target_b = None
            for b in self.buildings:
                if b.get("gx") == gx and b.get("gy") == gy:
                    target_b = b; break
            if target_b is None: return
            if target_b.get("owner") != cid: return
            if is_hammer:
                # снос
                kind_back = target_b["kind"]
                self.buildings.remove(target_b)
                self.building_cells.discard((gx, gy))
                p["build_inventory"][kind_back] = p["build_inventory"].get(kind_back, 0) + 1
                self._popup(cx, cy - BARRICADE_GRID / 2 - 10, "МОЛОТ", (255, 200, 120))
            elif is_wrench:
                need = int(target_b["max_hp"] - target_b["hp"])
                if need <= 0: return
                have = int(p.get("coins", 0))
                if have < need: need = have
                if need <= 0: return
                target_b["hp"] = min(target_b["max_hp"], target_b["hp"] + need)
                p["coins"] -= need
                self._popup(cx, cy - BARRICADE_GRID / 2 - 10, f"-{need}$", (255, 220, 120))


    def _handle_place_build(self, cid, msg):
        with self.lock:
            p = self.players.get(cid)
            if not p or p["dead"] or p.get("choosing_weapon"): return
            key = p.get("build_slot")
            if key not in BUILD_PRICES: return
            if p["build_inventory"].get(key, 0) <= 0: return
            if self._count_player_buildings(cid, key) >= BUILD_MAX_PER_PLAYER.get(key, 999): return
            gx = msg.get("gx"); gy = msg.get("gy")
            if gx is None or gy is None: return
            gx = int(gx); gy = int(gy)
            mgx = int(p["x"] // BARRICADE_GRID); mgy = int(p["y"] // BARRICADE_GRID)
            if abs(gx - mgx) > BARRICADE_RANGE or abs(gy - mgy) > BARRICADE_RANGE: return
            if gx < 0 or gy < 0 or (gx+1)*BARRICADE_GRID > MAP_W or (gy+1)*BARRICADE_GRID > MAP_H: return
            cx = gx * BARRICADE_GRID + BARRICADE_GRID / 2
            cy = gy * BARRICADE_GRID + BARRICADE_GRID / 2
            if math.hypot(cx - p["x"], cy - p["y"]) < PLAYER_R + BARRICADE_GRID / 2: return
            if (gx, gy) in self.building_cells: return
            _fb = MOD_API.first_truthy("filter_build_place", self, p, key, gx, gy)
            if _fb is False: return
            p["build_inventory"][key] -= 1
            self.building_cells.add((gx, gy))
            # === трекер построек для Боба ===
            self.builds_by_player.setdefault(cid, set()).add(key)
            if ACH_BOB not in self.achievements_earned_this_session:
                s_ = self.builds_by_player[cid]
                if all(k in s_ for k in BOB_BUILD_KINDS):
                    self._grant_achievement(ACH_BOB)
            self.buildings.append({
                "id": self.next_building_id, "gx": gx, "gy": gy,
                "x": cx, "y": cy, "kind": key,
                "hp": BUILD_HP[key], "max_hp": BUILD_HP[key],
                "owner": cid, "last_hit": 0.0, "next_shot": 0.0, "angle": 0.0,
            })
            self.next_building_id += 1
            MOD_API.call("on_build_bought", self, p, key)

    def _handle_use_forbidden(self, cid, msg):
        with self.lock:
            p = self.players.get(cid)
            if not p or p["dead"]: return
            if p.get("forbidden_count", 0) <= 0 or not self.crates: return
            p["forbidden_count"] -= 1
            for cr in self.crates:
                rar = next((r for r in CRATE_RARITIES if r[0] == "legendary"), None)
                if not rar: continue
                name, _, bmin, bmax, cmin, cmax, xmin, xmax, color = rar
                total_b = sum(b[1] for b in CRATE_BUFF_CHANCES)
                buffs = []
                for _ in range(random.randint(bmin, bmax)):
                    rb = random.random() * total_b; acc = 0.0
                    for bkey, bch in CRATE_BUFF_CHANCES:
                        acc += bch
                        if rb <= acc: buffs.append(bkey); break
                cr["rarity"] = name; cr["color"] = list(color); cr["buffs"] = buffs
                cr["coins"] = random.randint(cmin, cmax); cr["xp"] = random.randint(xmin, xmax)

    def _handle_assign_slot(self, cid, msg):
        key = msg.get("key"); slot = msg.get("slot")
        if key not in ARSENAL: return
        if not isinstance(slot, int) or slot < 0 or slot >= MAX_WEAPON_SLOTS: return
        with self.lock:
            p = self.players.get(cid)
            if not p or key not in p.get("owned_weapons", []): return
            slots = p.get("weapon_slots")
            for i in range(MAX_WEAPON_SLOTS):
                if slots[i] == key: slots[i] = None
            slots[slot] = key

    def _handle_buy_weapon(self, cid, msg):
        key = msg.get("key"); info = ARSENAL.get(key)
        if not info: return
        with self.lock:
            p = self.players.get(cid)
            if not p or key in p.get("owned_weapons", []): return
            if key == "last_prism":
                if not p.get("last_prism_unlocked"): return
            elif key == "true_star":
                if not p.get("true_star_unlocked"): return
            else:
                if not self._weapon_allowed_for_player(p, key): return
            if p["coins"] < info["price"]: return
            _fb = MOD_API.first_truthy("filter_weapon_purchase", self, p, key)
            if _fb is False: return
            p["coins"] -= info["price"]; p["owned_weapons"].append(key)
            self._assign_to_first_free_slot(p, key)
            self._add_euphoria(p, 20)
            MOD_API.call("on_weapon_bought", self, p, key)

    def _handle_buy_buff(self, cid, msg):
        key = msg.get("key"); info = SHOP_BUFFS.get(key)
        if not info: return
        with self.lock:
            p = self.players.get(cid)
            if not p or p["coins"] < info["price"]: return
            p["coins"] -= info["price"]
            p["inventory"][key] = p["inventory"].get(key, 0) + 1

    def _handle_select_weapon(self, cid, msg):
        key = msg.get("key")
        with self.lock:
            p = self.players.get(cid)
            if not p: return
            if key in p.get("weapon_slots", []): p["weapon"] = key
            elif key == "base": p["weapon"] = "base"
            p["charge_start"] = 0.0

    def _handle_use_item(self, cid, msg):
        now = time.time(); key = msg.get("key")
        if key not in SHOP_BUFFS: return
        payload = None
        with self.lock:
            p = self.players.get(cid)
            if not p or p["dead"]: return
            cur = p["inventory"].get(key, 0)
            if cur <= 0: return
            p["inventory"][key] = cur - 1
            if key == "minigun":
                dur = MINIGUN_DURATION_ACH if ACH_ONE_MAN_ARMY in self.host_achievements else MINIGUN_DURATION
                p["shoot_until"] = max(p.get("shoot_until", 0), now) + dur
            elif key == "lightning":
                p["speed_until"] = max(p.get("speed_until", 0), now) + LIGHTNING_DURATION
            elif key == "apple":
                p["hp"] = min(MAX_HP, p["hp"] + MEDKIT_HEAL)
                p["apple_eat_until"] = now + APPLE_EAT_DURATION
                p["apple_eat_start"] = now
                payload = {"type": "apple_eat", "x": p["x"], "y": p["y"]}
            elif key == "firedoom":
                p["firedoom_until"] = max(p.get("firedoom_until", 0), now) + FIREDOOM_DURATION
            elif key == "crazy":
                p["crazy_until"] = max(p.get("crazy_until", 0), now) + CRAZY_DURATION
            MOD_API.call("on_item_used", self, p, key)
        if payload: self._broadcast(payload)

    def _push_out_of_buildings(self, p):
        pr = PLAYER_R; half = BARRICADE_GRID / 2
        for b in self.buildings:
            if b.get("kind") == BUILD_DOOR: continue  # игроки ходят сквозь дверь
            left = b["x"] - half; right = b["x"] + half
            top = b["y"] - half; bottom = b["y"] + half
            nx = max(left, min(p["x"], right)); ny = max(top, min(p["y"], bottom))
            dx = p["x"] - nx; dy = p["y"] - ny; d2 = dx*dx + dy*dy
            if d2 < pr * pr:
                d = math.sqrt(d2) if d2 > 1e-12 else 0.0
                if d < 1e-6:
                    cx = b["x"]; cy = b["y"]; dxs = p["x"] - cx; dys = p["y"] - cy
                    if abs(dxs) > abs(dys): p["x"] = cx + (half + pr) * (1 if dxs > 0 else -1)
                    else: p["y"] = cy + (half + pr) * (1 if dys > 0 else -1)
                    continue
                nx2 = dx / d; ny2 = dy / d; push = pr - d
                p["x"] += nx2 * push; p["y"] += ny2 * push

    def _resolve_zombie_buildings(self, now):
        half = BARRICADE_GRID / 2
        for z in self.zombies:
            zr = z.get("r", ZOMBIE_R)
            for b in list(self.buildings):
                left = b["x"] - half; right = b["x"] + half
                top = b["y"] - half; bottom = b["y"] + half
                nx = max(left, min(z["x"], right)); ny = max(top, min(z["y"], bottom))
                dx = z["x"] - nx; dy = z["y"] - ny; d2 = dx*dx + dy*dy
                if d2 < zr * zr:
                    d = math.sqrt(d2) if d2 > 1e-12 else 0.0
                    if d < 1e-6:
                        cx = b["x"]; cy = b["y"]; dxs = z["x"] - cx; dys = z["y"] - cy
                        if abs(dxs) > abs(dys): z["x"] = cx + (half + zr) * (1 if dxs > 0 else -1)
                        else: z["y"] = cy + (half + zr) * (1 if dys > 0 else -1)
                    else:
                        nx2 = dx / d; ny2 = dy / d; push = zr - d
                        z["x"] += nx2 * push; z["y"] += ny2 * push
                    if now - b.get("last_hit", 0) >= BARRICADE_HIT_CD:
                        b["last_hit"] = now; b["hp"] -= BARRICADE_DMG
                        self._popup(b["x"], b["y"] - half - 10, BARRICADE_DMG, (255, 200, 60))
                        if b["hp"] <= 0:
                            self.buildings.remove(b); self.building_cells.discard((b["gx"], b["gy"]))
                            break

    def _grant_achievement(self, key):
        if key in self.achievements_earned_this_session: return
        self.achievements_earned_this_session.append(key)
        # Рассылаем достижение всем, у кого НЕ стоит флаг no_stats
        with self.lock:
            targets = [pid for pid, p in self.players.items()
                       if not p.get("no_stats")]
        for pid in targets:
            self._send(pid, {"type": "achievement", "key": key})
            if key == ACH_BOB:
                self._send(pid, {"type": "unlock", "key": UNLOCK_CRYSTAL})


    def _check_not_funny_on_kill(self, killed_z):
        if ACH_NOT_FUNNY in self.achievements_earned_this_session: return
        if self.wave_first_zombie_id is None: return
        if killed_z["id"] != self.wave_first_zombie_id: return
        if any(z is not killed_z and not z.get("charmed") for z in self.zombies): return
        self._grant_achievement(ACH_NOT_FUNNY)

    def _hammer_hit(self, p, base_angle):
        """Молот: сносит свою ближайшую постройку в направлении удара."""
        reach = 130
        best = None; best_d = None
        for b in self.buildings:
            if b.get("owner") != p["id"]: continue
            d = math.hypot(b["x"] - p["x"], b["y"] - p["y"])
            if d > reach + BARRICADE_GRID: continue
            to_b = math.atan2(b["y"] - p["y"], b["x"] - p["x"])
            diff = abs(math.atan2(math.sin(to_b - base_angle), math.cos(to_b - base_angle)))
            if diff > math.pi * 0.45: continue
            if best_d is None or d < best_d: best_d = d; best = b
        if best is None: return
        kind_back = best["kind"]
        self.buildings.remove(best)
        self.building_cells.discard((best["gx"], best["gy"]))
        p["build_inventory"][kind_back] = p["build_inventory"].get(kind_back, 0) + 1
        self._popup(best["x"], best["y"] - BARRICADE_GRID / 2 - 10, "МОЛОТ", (255, 200, 120))

    def _wrench_hit(self, p, base_angle):
        """Ключ: чинит свою ближайшую постройку за монеты (1 монета = 1 HP)."""
        reach = 130
        best = None; best_d = None
        for b in self.buildings:
            if b.get("owner") != p["id"]: continue
            if b["hp"] >= b["max_hp"]: continue
            d = math.hypot(b["x"] - p["x"], b["y"] - p["y"])
            if d > reach + BARRICADE_GRID: continue
            to_b = math.atan2(b["y"] - p["y"], b["x"] - p["x"])
            diff = abs(math.atan2(math.sin(to_b - base_angle), math.cos(to_b - base_angle)))
            if diff > math.pi * 0.45: continue
            if best_d is None or d < best_d: best_d = d; best = b
        if best is None: return
        need = int(best["max_hp"] - best["hp"])
        if need <= 0: return
        have = int(p.get("coins", 0))
        if have < need: need = have
        if need <= 0: return
        best["hp"] = min(best["max_hp"], best["hp"] + need)
        p["coins"] -= need
        self._popup(best["x"], best["y"] - BARRICADE_GRID / 2 - 10, f"-{need}$", (255, 220, 120))


    def _apply_melee_hit(self, p, base_angle, dmg, stats, now):
        _md = MOD_API.call("modify_damage", self, p, dmg, "melee", None)
        if _md:
            for _v in _md:
                if isinstance(_v, (int, float)) and _v > 0:
                    dmg = _v; break
        reach = stats.get("reach", 120); arc = stats.get("arc", math.pi * 0.7)
        charm_on_kill = bool(stats.get("charm_on_kill"))
        # === PvP: melee попадание в игрока (только в MODE_PVP) ===
        if self.mode == MODE_PVP:
            for _pid, _pl in self.players.items():
                if _pid == p["id"]: continue
                if _pl.get("dead") or _pl.get("wanish") or _pl.get("choosing_weapon"): continue
                _d = math.hypot(_pl["x"] - p["x"], _pl["y"] - p["y"])
                if _d > reach + PLAYER_R: continue
                _to_t = math.atan2(_pl["y"] - p["y"], _pl["x"] - p["x"])
                _diff = abs(math.atan2(math.sin(_to_t - base_angle), math.cos(_to_t - base_angle)))
                if _diff > arc / 2: continue
                self._pvp_hit_player(p["id"], _pl, dmg, now)
        for z in list(self.zombies):
            if z.get("frozen_until", 0) > now or z.get("charmed"): continue
            zr = z.get("r", ZOMBIE_R)
            d = math.hypot(z["x"] - p["x"], z["y"] - p["y"])
            if d > reach + zr: continue
            to_t = math.atan2(z["y"] - p["y"], z["x"] - p["x"])
            diff = abs(math.atan2(math.sin(to_t - base_angle), math.cos(to_t - base_angle)))
            if diff > arc / 2: continue
            died = self._zombie_take_damage(z, dmg, now)
            MOD_API.call("on_melee_hit", self, p, z, dmg)
            self._popup(z["x"], z["y"] - zr - 10, dmg, (255, 255, 255))
            if died:
                zr_reward = z.get("xp_reward", int(zombie_reward(self.wave) * self.reward_mult))
                zc_reward = self._coins_reward(z) if z.get("coins_reward") else int(zombie_reward(self.wave) * self.reward_mult)
                p["xp"] += zr_reward; p["coins"] += zc_reward
                p["level"] = level_from_xp(p["xp"])
                self._send_stats(p["id"], {"type": "kill", "boss": z.get("boss", False)})
                self._maybe_forbidden_drop(z, p["id"])
                self._check_not_funny_on_kill(z)
                if z.get("kind") == "kamikaze" and not z.get("_exploded"):
                    z["_exploded"] = True
                    self._kamikaze_explode(z["x"], z["y"], now)
                if z.get("kind") == "infected": self._spawn_infected_puddle(z["x"], z["y"], now)
                self._kill_zombie(z)
                if charm_on_kill: self._spawn_charmed_copy(z)

    def _maybe_forbidden_drop(self, z, owner_id):
        if ACH_HORRORS_OF_PAST not in self.host_achievements: return
        is_boss = z.get("boss", False) or z.get("final", False)
        chance = FORBIDDEN_BOSS_DROP_CHANCE if is_boss else FORBIDDEN_DROP_CHANCE
        if random.random() < chance:
            self.forbidden_items.append({"id": self.next_forbidden_id, "x": z["x"], "y": z["y"]})
            self.next_forbidden_id += 1

    def _maybe_drop_special(self, z, killer_id, weapon_key):
        if weapon_key in ("first_prism", "last_prism"):
            if random.random() < PRISM_SHARD_DROP_CHANCE:
                self.prism_shards.append({"id": self.next_prism_id, "x": z["x"], "y": z["y"]})
                self.next_prism_id += 1
        if weapon_key == "star":
            if random.random() < STARDUST_DROP_CHANCE:
                self.stardust_items.append({"id": self.next_stardust_id, "x": z["x"], "y": z["y"]})
                self.next_stardust_id += 1

    def _spawn_charmed_copy(self, killed_z):
        self.zombies.append({
            "id": self.next_zombie_id, "x": killed_z["x"], "y": killed_z["y"],
            "kind": killed_z.get("kind", "normal"),
            "hp": killed_z.get("max_hp", killed_z.get("hp", ZOMBIE_HP)),
            "max_hp": killed_z.get("max_hp", killed_z.get("hp", ZOMBIE_HP)),
            "r": killed_z.get("r", ZOMBIE_R),
            "speed": killed_z.get("speed", ZOMBIE_SPEED),
            "dmg": killed_z.get("dmg", ZOMBIE_DMG),
            "hit_cd": killed_z.get("hit_cd", ZOMBIE_HIT_CD),
            "xp_reward": 0, "coins_reward": 0,
            "boss": False, "final": False, "charmed": True, "shadow": False,
            "golden": False,
            "last_hit": 0.0, "fire_until": 0.0, "fire_next_tick": 0.0,
            "frozen_until": 0.0, "next_sound_at": time.time() + 3.0,
        })
        self.next_zombie_id += 1

    def _spawn_hexagon_shadows(self, source, now):
        if not source: return
        base_hp = source.get("max_hp", ZOMBIE_HP)
        hp = max(1, int(base_hp * 0.33))
        for _ in range(3):
            ang = random.uniform(0, math.tau); rad = random.uniform(20, 60)
            x = max(ZOMBIE_R, min(MAP_W - ZOMBIE_R, source["x"] + math.cos(ang) * rad))
            y = max(ZOMBIE_R, min(MAP_H - ZOMBIE_R, source["y"] + math.sin(ang) * rad))
            self.zombies.append({
                "id": self.next_zombie_id, "x": x, "y": y,
                "kind": source.get("kind", "normal"),
                "hp": hp, "max_hp": hp, "r": source.get("r", ZOMBIE_R),
                "speed": source.get("speed", ZOMBIE_SPEED),
                "dmg": source.get("dmg", ZOMBIE_DMG),
                "hit_cd": source.get("hit_cd", ZOMBIE_HIT_CD),
                "xp_reward": 0, "coins_reward": 0,
                "boss": False, "final": False, "charmed": True, "shadow": True,
                "golden": False,
                "last_hit": 0.0, "fire_until": 0.0, "fire_next_tick": 0.0,
                "frozen_until": 0.0, "next_sound_at": now + 3.0,
            })
            self.next_zombie_id += 1

    def _spawn_infected_puddle(self, x, y, now):
        self.puddles.append({"x": x, "y": y, "r": INFECTED_PUDDLE_R,
                              "until": now + INFECTED_PUDDLE_LIFE,
                              "next_tick": now})

    def _kamikaze_explode(self, x, y, now):
        self._popup(x, y, "BOOM", (255, 100, 0))
        for pl in list(self.players.values()):
            if pl["dead"]: continue
            if pl.get("wanish"): continue
            if math.hypot(pl["x"] - x, pl["y"] - y) < BOMBER_EXPLODE_R:
                dmg = BOMBER_EXPLODE_DMG
                if pl.get("weapon") == "shield": dmg = int(dmg * (1 - SHIELD_DMG_REDUCTION))
                pl["hp"] = max(0, pl["hp"] - dmg)
                self._popup(pl["x"], pl["y"] - PLAYER_R - 10, dmg, (255, 100, 0))
                if pl["hp"] <= 0 and not pl["dead"]:
                    pl["dead"] = True; pl["respawn_at"] = now + RESPAWN_DELAY
                    pl["xp"] = 0; pl["level"] = 0
                    self._send_stats(pl["id"], {"type": "death"})
        for z in list(self.zombies):
            zr = z.get("r", ZOMBIE_R)
            if math.hypot(z["x"] - x, z["y"] - y) < BOMBER_EXPLODE_R + zr:
                died = self._zombie_take_damage(z, BOMBER_EXPLODE_DMG, now)
                if died:
                    z["_exploded"] = True
                    self._on_zombie_killed(z, None, None, "kamikaze_explosion")

    def _charm_zombie(self, z, now):
        if z.get("charmed"): return
        z["charmed"] = True; z["xp_reward"] = 0; z["coins_reward"] = 0
        z["last_hit"] = now
        self._popup(z["x"], z["y"] - z.get("r", ZOMBIE_R) - 10, "♥", (255, 130, 200))

    def _process_multi_hit_queue(self, now):
        for pid, p in self.players.items():
            if not p.get("multi_hit_queue"): continue
            if p["dead"]: p["multi_hit_queue"].clear(); continue
            still = []
            for hit in p["multi_hit_queue"]:
                if now >= hit["at"]: self._apply_melee_hit(p, hit["angle"], hit["dmg"], hit["stats"], now)
                else: still.append(hit)
            p["multi_hit_queue"] = still

    def _star_explode(self, x, y, owner_id, now):
        owner = self.players.get(owner_id)
        reward = int(zombie_reward(self.wave) * self.reward_mult)
        for z in list(self.zombies):
            if z.get("charmed"): continue
            zr = z.get("r", ZOMBIE_R)
            if math.hypot(z["x"] - x, z["y"] - y) < STAR_SPLASH_R + zr:
                died = self._zombie_take_damage(z, STAR_SPLASH_DMG, now)
                self._popup(z["x"], z["y"] - zr - 10, STAR_SPLASH_DMG, (255, 240, 120))
                if died:
                    if owner:
                        xr = z.get("xp_reward", reward); xc = self._coins_reward(z) if z.get("coins_reward") else reward
                        owner["xp"] += xr; owner["coins"] += xc
                        owner["level"] = level_from_xp(owner["xp"])
                    self._send_stats(owner_id, {"type": "kill", "boss": z.get("boss", False)})
                    self._maybe_forbidden_drop(z, owner_id)
                    self._check_not_funny_on_kill(z)
                    if owner:
                        self._maybe_drop_special(z, owner_id, owner.get("weapon", ""))
                    if z.get("kind") == "kamikaze" and not z.get("_exploded"):
                        z["_exploded"] = True
                        self._kamikaze_explode(z["x"], z["y"], now)
                    if z.get("kind") == "infected": self._spawn_infected_puddle(z["x"], z["y"], now)
                    self._kill_zombie(z)

    def _handle_shoot(self, cid, msg):
        new_bullets = []; now = time.time()
        with self.lock:
            p = self.players.get(cid)
            if not p or p["dead"] or p.get("choosing_weapon"): return
            if p.get("frozen_until", 0) > now: return
            if not p.get("weapon"):
                p["weapon"] = "fist"
            weapon = p.get("weapon", "fist")
            stats = WEAPON_STATS.get(weapon, WEAPON_STATS["base"])
            base_angle = msg.get("angle", p["angle"])
            lvl = p.get("level", 0)
            dmg = weapon_dmg_with_level(stats, lvl)
            # === ПАССИВКА "АЛАКАЗАМ": 1% шанс урона 10^15 ===
            if p.get("passive") == "алаказам" and random.random() < 0.01:
                dmg = 10**15
            if stats.get("no_shoot"): return
            if weapon in ("laser", "first_prism", "last_prism"):
                p["laser_until"] = max(p.get("laser_until", 0), now) + 0.5
                p["laser_angle"] = base_angle
                return
            if p.get("passive") == "coin_volley":
                p["coins"] += 1
            if stats.get("melee"):
                p["melee_until"] = now + 0.25
                p["melee_angle"] = base_angle
                self._apply_melee_hit(p, base_angle, dmg, stats, now)
                multi = int(stats.get("multi_hits", 1))
                if multi > 1:
                    delay = float(stats.get("multi_delay", 0.05))
                    for i in range(1, multi):
                        p["multi_hit_queue"].append({"at": now + delay * i, "angle": base_angle, "dmg": dmg, "stats": stats})
                return
            pellets = stats["pellets"]; spread = stats["spread"]
            speed = stats["speed"]; life = stats["life"]
            # === БАФ ДРОБОВИКА: +1 урона дробине за каждые 10 px до ближайшего зомби (радиус 300) ===
            shotgun_bonus = 0
            if weapon == "shotgun":
                best_d2 = None
                for _z in self.zombies:
                    if _z.get("charmed"): continue
                    _d = math.hypot(_z["x"] - p["x"], _z["y"] - p["y"])
                    if _d <= 300 and (best_d2 is None or _d < best_d2):
                        best_d2 = _d
                if best_d2 is not None:
                    shotgun_bonus = int((300 - best_d2) / 10)
            is_star = (weapon == "star"); is_true_star = (weapon == "true_star")
            star_special = False
            if is_star:
                p["star_counter"] = p.get("star_counter", 0) + 1
                if p["star_counter"] % STAR_SPECIAL_EVERY == 0 and lvl >= STAR_SPECIAL_MIN_LEVEL: star_special = True
            firedoom_active = p.get("firedoom_until", 0) > now
            is_secret = (weapon == "secret_beam")
            _portal_off = int(stats.get("portal_offset", 70)) if is_secret else 0
            for _pi in range(pellets):
                a = base_angle if pellets == 1 else base_angle + random.uniform(-spread, spread)
                # секретное излучение: 2 портала по бокам (перпендикулярно углу)
                if is_secret:
                    _side = -1 if _pi == 0 else 1
                    _perp = base_angle + math.pi / 2 * _side
                    _sx = p["x"] + math.cos(_perp) * _portal_off
                    _sy = p["y"] + math.sin(_perp) * _portal_off
                else:
                    _sx = p["x"] + math.cos(a) * (PLAYER_R + 6)
                    _sy = p["y"] + math.sin(a) * (PLAYER_R + 6)
                b = {"x": _sx,
                     "y": _sy,
                     "vx": math.cos(a) * speed, "vy": math.sin(a) * speed,
                     "owner": cid, "life": life, "dmg": int(dmg) + shotgun_bonus,
                     "weapon": weapon, "firedoom": firedoom_active,
                     "traveled": 0.0, "base_dmg": int(dmg)}
                if stats.get("pierce"): b["pierce_left"] = stats["pierce"]
                if stats.get("explosive"): b["explosive"] = stats["explosive"]
                if stats.get("freeze"): b["freeze"] = stats["freeze"]
                if stats.get("meteor"): b["meteor"] = True
                if stats.get("charm"):
                    b["charm"] = True
                    b["charm_chance"] = stats.get("charm_chance", 0.15)
                    b["charm_boss_chance"] = stats.get("charm_boss_chance", 0.05)
                if stats.get("hexagon"): b["hexagon"] = True
                if stats.get("secret_beam"):
                    b["secret_beam"] = True
                    b["angle"] = a
                    b["homing"] = True
                    b["speed"] = speed
                if is_star: b["homing"] = True; b["angle"] = a; b["special"] = star_special
                if is_true_star: b["homing"] = True; b["angle"] = a; b["true_star"] = True
                new_bullets.append(b)
        with self.lock: self.bullets.extend(new_bullets)

    def _update_lasers(self, now):
        for p in self.players.values():
            if p["dead"]: continue
            weapon = p.get("weapon")
            if weapon not in ("laser", "first_prism", "last_prism"): continue
            if p.get("laser_until", 0) <= now or p.get("frozen_until", 0) > now: continue
            if weapon == "first_prism":
                tick = 0.05
            elif weapon == "last_prism":
                tick = 0.05
            else:
                tick = LASER_TICK
            _lstats = WEAPON_STATS.get(weapon, WEAPON_STATS["laser"])
            dmg_per_hit = weapon_dmg_with_level(_lstats, p.get("level", 0))
            last = p.get("laser_next_tick", 0)
            if last <= 0:
                p["laser_next_tick"] = now; last = now
            ticks = 0
            while last + tick <= now:
                last += tick; ticks += 1
                if ticks > 5000: break
            if ticks <= 0: continue
            if p.get("passive") == "coin_volley":
                p["coins"] += ticks
            p["laser_next_tick"] = last
            dmg = dmg_per_hit * ticks
            ang = p.get("laser_angle", p.get("angle", 0.0))
            self._apply_laser_beam(p, ang, dmg, now, weapon)

    def _apply_laser_beam(self, p, angle, dmg, now, weapon="laser"):
        _md = MOD_API.call("modify_damage", self, p, dmg, "laser", None)
        if _md:
            for _v in _md:
                if isinstance(_v, (int, float)) and _v > 0:
                    dmg = _v; break
        ox, oy = p["x"], p["y"]
        dx, dy = math.cos(angle), math.sin(angle)
        half_w = LASER_WIDTH
        beam_range = max(MAP_W, MAP_H) * 2 if weapon == "last_prism" else LASER_RANGE
        # === PvP: лазер попадает в игроков (только в MODE_PVP) ===
        if self.mode == MODE_PVP:
            for _pid, _pl in self.players.items():
                if _pid == p["id"]: continue
                if _pl.get("dead") or _pl.get("wanish") or _pl.get("choosing_weapon"): continue
                _rx = _pl["x"] - ox; _ry = _pl["y"] - oy
                _t = _rx * dx + _ry * dy
                if _t < -PLAYER_R or _t > beam_range + PLAYER_R: continue
                _perp = abs(_rx * -dy + _ry * dx)
                if _perp > half_w + PLAYER_R: continue
                self._pvp_hit_player(p["id"], _pl, dmg, now)
        for z in list(self.zombies):
            if z.get("charmed"): continue
            zr = z.get("r", ZOMBIE_R)
            rx = z["x"] - ox; ry = z["y"] - oy
            t = rx * dx + ry * dy
            # допускаем t от -zr (зомби наложен на игрока) до beam_range+zr
            if t < -zr or t > beam_range + zr: continue
            perp = abs(rx * -dy + ry * dx)
            if perp > half_w + zr: continue
            died = self._zombie_take_damage(z, dmg, now)
            MOD_API.call("on_laser_hit", self, p, z, dmg)
            dmg_int = int(dmg) if dmg >= 1 else 1
            if weapon in ("first_prism", "last_prism"):
                popup_col = (255, 255, 255)
            else:
                popup_col = (255, 60, 60)
            self._popup(z["x"], z["y"] - zr - 10, dmg_int, popup_col)
            if died:
                reward = int(zombie_reward(self.wave) * self.reward_mult)
                xr = z.get("xp_reward", reward); xc = self._coins_reward(z) if z.get("coins_reward") else reward
                p["xp"] += xr; p["coins"] += xc
                p["level"] = level_from_xp(p["xp"])
                self._send_stats(p["id"], {"type": "kill", "boss": z.get("boss", False)})
                self._maybe_forbidden_drop(z, p["id"])
                self._check_not_funny_on_kill(z)
                self._maybe_drop_special(z, p["id"], weapon)
                if z.get("kind") == "kamikaze" and not z.get("_exploded"):
                    z["_exploded"] = True
                    self._kamikaze_explode(z["x"], z["y"], now)
                if z.get("kind") == "infected": self._spawn_infected_puddle(z["x"], z["y"], now)
                self._kill_zombie(z)

    def _wave_count(self, wave):
        if self.mode == MODE_BOSS_RUSH: return 0
        if wave == self.max_wave and self.stage == 2: return 0
        base = min(5 + int((wave - 1) * 795 / 99), MAX_ZOMBIES_PER_WAVE)
        base = int(base * self.count_mult)
        if is_boss_wave(wave): base = max(1, base // 20)
        return base

    def _pick_zombie_type(self, wave):
        total = sum(t["chance"] for t in ZOMBIE_TYPES.values())
        r = random.random() * total; acc = 0.0
        for tname, t in ZOMBIE_TYPES.items():
            acc += t["chance"]
            if r <= acc: return tname
        return "normal"

    def _golden_active(self):
        return any(p.get("passive") == "first_number" for p in self.players.values())

    def _spawn_zombie(self):
        kind = self._pick_zombie_type(self.wave)
        _fz = MOD_API.first_truthy("filter_zombie_spawn", self, kind, self.wave)
        if _fz is False:
            return
        t = ZOMBIE_TYPES[kind]
        hp = int(ZOMBIE_HP * t["hp_mult"] * self.hp_mult)
        spd = ZOMBIE_SPEED * t["speed_mult"] * self.speed_mult
        dmg = int(ZOMBIE_DMG * t["dmg_mult"] * self.dmg_mult)
        r = int(ZOMBIE_R * t["r_mult"])
        for _ in range(40):
            edge = random.choice(["n", "s", "w", "e"])
            if edge == "n": x, y = random.uniform(50, MAP_W - 50), 50 + r
            elif edge == "s": x, y = random.uniform(50, MAP_W - 50), MAP_H - 50 - r
            elif edge == "w": x, y = 50 + r, random.uniform(50, MAP_H - 50)
            else: x, y = MAP_W - 50 - r, random.uniform(50, MAP_H - 50)
            if all(pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon") or math.hypot(pl["x"] - x, pl["y"] - y) >= 400 + r
                   for pl in self.players.values()):
                reward = int(zombie_reward(self.wave) * self.reward_mult)
                zid = self.next_zombie_id
                is_first = (self.wave_first_zombie_id is None)
                if is_first: self.wave_first_zombie_id = zid
                golden = is_first and self._golden_active()
                if golden:
                    self._broadcast({"type": "golden_zombie", "zid": zid})
                self.zombies.append({
                    "id": zid, "x": x, "y": y, "kind": kind,
                    "hp": hp, "max_hp": hp, "r": r,
                    "speed": spd, "dmg": dmg, "hit_cd": ZOMBIE_HIT_CD,
                    "xp_reward": reward, "coins_reward": reward,
                    "boss": False, "final": False, "charmed": False, "shadow": False,
                    "golden": golden,
                    "last_hit": 0.0, "fire_until": 0.0, "fire_next_tick": 0.0,
                    "frozen_until": 0.0, "next_sound_at": time.time() + 3.0,
                    "spitter_next": time.time() + 1.0,
                })
                self.next_zombie_id += 1
                MOD_API.call("on_zombie_spawn", self, self.zombies[-1])
                return

    def _spawn_boss(self, final=False):
        r = FINAL_BOSS_R if final else BOSS_R
        hp = int((FINAL_BOSS_HP if final else BOSS_HP) * self.hp_mult)
        dmg = int((FINAL_BOSS_DMG if final else BOSS_DMG) * self.dmg_mult)
        for _ in range(40):
            edge = random.choice(["n", "s", "w", "e"])
            if edge == "n": x, y = random.uniform(50, MAP_W - 50), 50 + r
            elif edge == "s": x, y = random.uniform(50, MAP_W - 50), MAP_H - 50 - r
            elif edge == "w": x, y = 50 + r, random.uniform(50, MAP_H - 50)
            else: x, y = MAP_W - 50 - r, random.uniform(50, MAP_H - 50)
            if all(pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon") or math.hypot(pl["x"] - x, pl["y"] - y) >= 800 + r
                   for pl in self.players.values()):
                zid = self.next_zombie_id
                is_first = (self.wave_first_zombie_id is None)
                if is_first: self.wave_first_zombie_id = zid
                golden = is_first and self._golden_active()
                if golden:
                    self._broadcast({"type": "golden_zombie", "zid": zid})
                self.zombies.append({
                    "id": zid, "x": x, "y": y, "kind": "boss",
                    "hp": hp, "max_hp": hp, "boss": True, "final": final,
                    "r": r, "charmed": False, "shadow": False,
                    "golden": golden,
                    "speed": PLAYER_SPEED * (FINAL_BOSS_SPEED_MULT if final else BOSS_SPEED_MULT),
                    "dmg": dmg, "hit_cd": FINAL_BOSS_HIT_CD if final else BOSS_HIT_CD,
                    "xp_reward": FINAL_BOSS_XP_REWARD if final else BOSS_XP_REWARD,
                    "coins_reward": FINAL_BOSS_COINS_REWARD if final else BOSS_COINS_REWARD,
                    "last_hit": 0.0, "fire_until": 0.0, "fire_next_tick": 0.0,
                    "frozen_until": 0.0, "next_sound_at": time.time() + 3.0,
                    "homing_next": time.time() + FINAL_BOSS_HOMING_CD,
                })
                self.next_zombie_id += 1
                MOD_API.call("on_zombie_spawn", self, self.zombies[-1])
                return

    def _spawn_stage50_boss(self):
        r = BOSS_R; hp = int(STAGE50_BOSS_HP * self.hp_mult); dmg = int(BOSS_DMG * self.dmg_mult)
        for _ in range(40):
            edge = random.choice(["n", "s", "w", "e"])
            if edge == "n": x, y = random.uniform(50, MAP_W - 50), 50 + r
            elif edge == "s": x, y = random.uniform(50, MAP_W - 50), MAP_H - 50 - r
            elif edge == "w": x, y = 50 + r, random.uniform(50, MAP_H - 50)
            else: x, y = MAP_W - 50 - r, random.uniform(50, MAP_H - 50)
            if all(pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon") or math.hypot(pl["x"] - x, pl["y"] - y) >= 800 + r
                   for pl in self.players.values()):
                zid = self.next_zombie_id
                is_first = (self.wave_first_zombie_id is None)
                if is_first: self.wave_first_zombie_id = zid
                golden = is_first and self._golden_active()
                if golden:
                    self._broadcast({"type": "golden_zombie", "zid": zid})
                self.zombies.append({
                    "id": zid, "x": x, "y": y, "kind": "boss",
                    "hp": hp, "max_hp": hp, "boss": True, "final": False,
                    "stage50": True, "r": r, "charmed": False, "shadow": False,
                    "golden": golden,
                    "speed": PLAYER_SPEED * BOSS_SPEED_MULT,
                    "dmg": dmg, "hit_cd": BOSS_HIT_CD,
                    "xp_reward": BOSS_XP_REWARD, "coins_reward": BOSS_COINS_REWARD,
                    "last_hit": 0.0, "fire_until": 0.0, "fire_next_tick": 0.0,
                    "frozen_until": 0.0, "next_sound_at": time.time() + 3.0,
                    "dash_next_at": time.time() + STAGE50_BOSS_DASH_CD,
                    "dash_state": "idle", "dash_state_until": 0.0,
                    "dash_vx": 0.0, "dash_vy": 0.0, "dash_hit_players": set(),
                })
                self.next_zombie_id += 1
                MOD_API.call("on_zombie_spawn", self, self.zombies[-1])
                return

    def _spawn_crate_at(self, x, y):
        total_r = sum(r[1] for r in CRATE_RARITIES)
        total_b = sum(b[1] for b in CRATE_BUFF_CHANCES)
        r = random.random() * total_r; acc = 0.0; chosen = CRATE_RARITIES[0]
        for rar in CRATE_RARITIES:
            acc += rar[1]
            if r <= acc: chosen = rar; break
        name, _, bmin, bmax, cmin, cmax, xmin, xmax, color = chosen
        buffs = []
        for _ in range(random.randint(bmin, bmax)):
            rb = random.random() * total_b; acc2 = 0.0
            for bkey, bch in CRATE_BUFF_CHANCES:
                acc2 += bch
                if rb <= acc2: buffs.append(bkey); break
        self.crates.append({"id": self.next_crate_id, "x": x, "y": y,
                             "rarity": name, "color": list(color), "buffs": buffs,
                             "coins": random.randint(cmin, cmax), "xp": random.randint(xmin, xmax)})
        self.next_crate_id += 1

    def _spawn_crates_after_wave(self):
        _n_crates = random.randint(CRATES_PER_WAVE_MIN, CRATES_PER_WAVE_MAX)
        for _ in range(_n_crates):
            for _ in range(30):
                ang = random.uniform(0, math.tau)
                rad = random.uniform(200, CRATE_SPAWN_CENTER_R)
                x = MAP_W / 2 + math.cos(ang) * rad; y = MAP_H / 2 + math.sin(ang) * rad
                if all(math.hypot(o["x"] - x, o["y"] - y) >= 200 for o in self.crates): break
            self._spawn_crate_at(x, y)

    def _start_wave(self, now):
        try:
            if self.wave >= self.max_wave and self.difficulty != DIFF_ENDLESS:
                self.victory = True
                self._broadcast({"type": "victory"})
                MOD_API.call("on_victory", self)
                for pid in list(self.players.keys()): self._send_stats(pid, {"type": "win"})
                if (ACH_ONE_MAN_ARMY not in self.achievements_earned_this_session
                    and not self.session_had_other_clients):
                    self._grant_achievement(ACH_ONE_MAN_ARMY)
                if self.max_wave == 100 and ACH_HORRORS_OF_PAST not in self.achievements_earned_this_session:
                    self._grant_achievement(ACH_HORRORS_OF_PAST)
                self.wave_state = "break"; self.wave_break_until = now + 99999
                self.wave_button_active = False
                return
            self.wave += 1
            self.wave_total = self._wave_count(self.wave)
            self.wave_killed = 0; self.wave_spawn_left = self.wave_total
            self.wave_next_spawn_at = now; self.wave_state = "spawning"
            self.wave_first_zombie_id = None
            self.wave_button_active = False
            if self.mode == MODE_CRYSTAL and self.crystal is None:
                self.crystal = {"x": MAP_W / 2, "y": MAP_H / 2, "vx": 0.0, "vy": 0.0,
                                "hp": CRYSTAL_HP, "max_hp": CRYSTAL_HP}
            if self.mode == MODE_BOSS_RUSH: self._spawn_boss(final=False)
            elif self.wave == 50: self._spawn_stage50_boss()
            elif is_boss_wave(self.wave):
                self._spawn_boss(final=(self.stage == 2 and self.wave == 100))
            self._broadcast({"type": "wave", "wave": self.wave,
                             "total": self.wave_total, "state": self.wave_state})
            MOD_API.call("on_wave_start", self, self.wave)
        except Exception as e:
            print("[start_wave] ERROR:", e); traceback.print_exc()
            self.wave_state = "spawning"; self.wave_spawn_left = max(1, self.wave_spawn_left)

    def _update_crystal(self, now, dt):
        if self.mode != MODE_CRYSTAL or self.crystal is None: return
        c = self.crystal
        # толкание игроками
        for pl in self.players.values():
            if pl["dead"]: continue
            d = math.hypot(pl["x"] - c["x"], pl["y"] - c["y"])
            if d < CRYSTAL_R + PLAYER_R:
                dx = c["x"] - pl["x"]; dy = c["y"] - pl["y"]
                if d < 1e-6: dx, dy, d = 1.0, 0.0, 1.0
                nx, ny = dx / d, dy / d
                c["vx"] += nx * CRYSTAL_PUSH_ACCEL * dt
                c["vy"] += ny * CRYSTAL_PUSH_ACCEL * dt
        # фрикция
        c["vx"] -= c["vx"] * CRYSTAL_FRICTION * dt
        c["vy"] -= c["vy"] * CRYSTAL_FRICTION * dt
        sp = math.hypot(c["vx"], c["vy"])
        if sp > CRYSTAL_MAX_SPEED:
            c["vx"] = c["vx"] / sp * CRYSTAL_MAX_SPEED
            c["vy"] = c["vy"] / sp * CRYSTAL_MAX_SPEED
        c["x"] = max(CRYSTAL_R, min(MAP_W - CRYSTAL_R, c["x"] + c["vx"] * dt))
        c["y"] = max(CRYSTAL_R, min(MAP_H - CRYSTAL_R, c["y"] + c["vy"] * dt))
        # толкаем кристалл из построек (кроме двери)
        _half = BARRICADE_GRID / 2
        for _b in self.buildings:
            if _b.get("kind") == BUILD_DOOR: continue
            _left = _b["x"] - _half; _right = _b["x"] + _half
            _top = _b["y"] - _half; _bot = _b["y"] + _half
            _nx = max(_left, min(c["x"], _right))
            _ny = max(_top, min(c["y"], _bot))
            _dx = c["x"] - _nx; _dy = c["y"] - _ny
            _d2 = _dx*_dx + _dy*_dy
            if _d2 < CRYSTAL_R * CRYSTAL_R:
                _d = math.sqrt(_d2) if _d2 > 1e-12 else 0.0
                if _d < 1e-6:
                    _cx = _b["x"]; _cy = _b["y"]
                    _dxs = c["x"] - _cx; _dys = c["y"] - _cy
                    if abs(_dxs) > abs(_dys):
                        c["x"] = _cx + (_half + CRYSTAL_R) * (1 if _dxs > 0 else -1)
                    else:
                        c["y"] = _cy + (_half + CRYSTAL_R) * (1 if _dys > 0 else -1)
                    continue
                _nx2 = _dx / _d; _ny2 = _dy / _d; _push = CRYSTAL_R - _d
                c["x"] += _nx2 * _push; c["y"] += _ny2 * _push
        # зомби кусают кристалл
        if now >= getattr(self, "crystal_next_hit", 0):
            for z in self.zombies:
                if z.get("charmed"): continue
                zr = z.get("r", ZOMBIE_R)
                if math.hypot(z["x"] - c["x"], z["y"] - c["y"]) < zr + CRYSTAL_R:
                    cdmg = CRYSTAL_DMG
                    # === РАЗЪЯРЕННЫЙ: +урон по кристаллу ===
                    if z.get("kind") == "enraged":
                        missing_hp = max(0, z.get("max_hp", ZOMBIE_HP) - z["hp"])
                        cdmg += int(missing_hp)
                    c["hp"] -= cdmg
                    self.crystal_next_hit = now + CRYSTAL_HIT_CD
                    self._popup(c["x"], c["y"] - CRYSTAL_R - 10, CRYSTAL_DMG, (255, 80, 80))
                    break
        # проигрыш
        if c["hp"] <= 0:
            self.crystal = None
            self.game_over = True
            self._broadcast({"type": "game_over"})
            MOD_API.call("on_game_over", self)


    def _update_waves(self, now):
        if self.wave_state == "break":
            if self.wave_button_active and not self.victory:
                for pl in self.players.values():
                    if pl["dead"] or pl.get("choosing_weapon"): continue
                    if math.hypot(pl["x"] - self.wave_button_x, pl["y"] - self.wave_button_y) < WAVE_BUTTON_R + PLAYER_R:
                        self._start_wave(now)
                        break
            return
        if self.wave_state == "spawning":
            can_spawn = len(self.zombies) < MAX_ZOMBIES_ON_MAP
            if self.wave_spawn_left > 0 and now >= self.wave_next_spawn_at and can_spawn:
                self._spawn_zombie()
                self.wave_spawn_left -= 1
                self.wave_next_spawn_at = now + WAVE_SPAWN_INTERVAL
            elif self.wave_spawn_left == 0: self.wave_state = "fighting"
            return
        if self.wave_state == "fighting":
            if not any(not z.get("charmed") for z in self.zombies) and self.wave_spawn_left == 0:
                self.wave_state = "break"; self.wave_break_until = now + 99999
                self.wave_button_active = True
                self.wave_button_x = MAP_W / 2
                self.wave_button_y = MAP_H / 2
                self._broadcast({"type": "wave", "wave": self.wave,
                                 "total": self.wave_total, "state": "break"})
                for pl in self.players.values():
                    if not pl["dead"]: pl["hp"] = min(MAX_HP, pl["hp"] + 40)
                self._spawn_crates_after_wave()
                MOD_API.call("on_wave_end", self, self.wave)
            elif self.wave_spawn_left > 0 and len(self.zombies) < MAX_ZOMBIES_ON_MAP and now >= self.wave_next_spawn_at:
                self._spawn_zombie(); self.wave_spawn_left -= 1
                self.wave_next_spawn_at = now + WAVE_SPAWN_INTERVAL

    def _update_stage50_boss(self, z, now):
        state = z.get("dash_state", "idle")
        if state == "idle":
            if now >= z.get("dash_next_at", 0):
                target = None; best = None
                for pl in self.players.values():
                    if pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon"): continue
                    d = math.hypot(pl["x"] - z["x"], pl["y"] - z["y"])
                    if best is None or d < best: best = d; target = pl
                if target is None: z["dash_next_at"] = now + 2.0; return
                dx = target["x"] - z["x"]; dy = target["y"] - z["y"]
                d = math.hypot(dx, dy) or 1.0
                z["dash_vx"] = dx / d * (STAGE50_BOSS_DASH_DIST / STAGE50_BOSS_DASH_DURATION)
                z["dash_vy"] = dy / d * (STAGE50_BOSS_DASH_DIST / STAGE50_BOSS_DASH_DURATION)
                z["dash_state"] = "telegraph"; z["dash_state_until"] = now + STAGE50_BOSS_TELEGRAPH
                z["dash_hit_players"] = set()
        elif state == "telegraph":
            if now >= z.get("dash_state_until", 0):
                z["dash_state"] = "dash"; z["dash_state_until"] = now + STAGE50_BOSS_DASH_DURATION
                z["dash_hit_players"] = set()
        elif state == "dash":
            if now >= z.get("dash_state_until", 0):
                z["dash_state"] = "idle"; z["dash_next_at"] = now + STAGE50_BOSS_DASH_CD; return
            z["x"] += z.get("dash_vx", 0) * (1.0 / TICK_RATE)
            z["y"] += z.get("dash_vy", 0) * (1.0 / TICK_RATE)
            zr = z.get("r", ZOMBIE_R)
            hit_set = z.get("dash_hit_players") or set()
            for pl in self.players.values():
                if pl["dead"] or pl.get("wanish") or pl["id"] in hit_set: continue
                if math.hypot(pl["x"] - z["x"], pl["y"] - z["y"]) < PLAYER_R + zr:
                    dmg = STAGE50_BOSS_DASH_DMG
                    if pl.get("weapon") == "shield": dmg = int(dmg * (1 - SHIELD_DMG_REDUCTION))
                    pl["hp"] = max(0, pl["hp"] - dmg)
                    self._popup(pl["x"], pl["y"] - PLAYER_R - 10, dmg, (255, 100, 40))
                    hit_set.add(pl["id"])
                    if pl["hp"] <= 0 and not pl["dead"]:
                        pl["dead"] = True; pl["respawn_at"] = now + RESPAWN_DELAY
                        pl["xp"] = 0; pl["level"] = 0
                        self._send_stats(pl["id"], {"type": "death"})
            z["dash_hit_players"] = hit_set

    def _update_zombies(self, now, dt):
        if dt <= 0: return
        for z in self.zombies:
            if z.get("frozen_until", 0) > now: continue
            if z.get("stage50"): self._update_stage50_boss(z, now)
            zr = z.get("r", ZOMBIE_R)
            zspeed = z.get("speed", ZOMBIE_SPEED)
            zdmg = z.get("dmg", ZOMBIE_DMG)
            zcd = z.get("hit_cd", ZOMBIE_HIT_CD)
            charmed = z.get("charmed", False)
            if charmed:
                target = None; best_d = None
                for o in self.zombies:
                    if o is z or o.get("charmed"): continue
                    d = math.hypot(o["x"] - z["x"], o["y"] - z["y"])
                    if best_d is None or d < best_d: best_d = d; target = o
                if target is None: continue
                dx = target["x"] - z["x"]; dy = target["y"] - z["y"]
                d = math.hypot(dx, dy)
                if d < 1e-6: continue
                touch = target.get("r", ZOMBIE_R) + zr
                if d < touch:
                    if now - z.get("last_hit", 0) >= zcd:
                        z["last_hit"] = now
                        died = self._zombie_take_damage(target, zdmg, now)
                        if died:
                            if target.get("kind") == "kamikaze": self._kamikaze_explode(target["x"], target["y"], now)
                            if target.get("kind") == "infected": self._spawn_infected_puddle(target["x"], target["y"], now)
                            self.zombies.remove(target)
                else:
                    step = min(zspeed * dt, d - touch)
                    if step > 0: z["x"] += dx / d * step; z["y"] += dy / d * step
                continue
            target = None; best_d = None; target_is_player = False
            # в режиме кристалла зомби идут к кристаллу, но кусают игрока, если он на пути
            if self.mode == MODE_CRYSTAL and self.crystal is not None:
                c = self.crystal
                d_to_c = math.hypot(c["x"] - z["x"], c["y"] - z["y"])
                _on_path = None; _best_p = None
                for _pid, _pl in self.players.items():
                    if _pl["dead"] or _pl.get("wanish") or _pl.get("choosing_weapon"): continue
                    _d = math.hypot(_pl["x"] - z["x"], _pl["y"] - z["y"])
                    if _d > 120: continue
                    _rx = _pl["x"] - z["x"]; _ry = _pl["y"] - z["y"]
                    _t = (_rx * (c["x"] - z["x"]) + _ry * (c["y"] - z["y"])) / max(1e-6, d_to_c)
                    if _t < 0 or _t > d_to_c: continue
                    _proj_x = z["x"] + (c["x"] - z["x"]) * (_t / max(1e-6, d_to_c))
                    _proj_y = z["y"] + (c["y"] - z["y"]) * (_t / max(1e-6, d_to_c))
                    _perp = math.hypot(_pl["x"] - _proj_x, _pl["y"] - _proj_y)
                    if _perp <= 80 and (_best_p is None or _d < _best_p): _best_p = _d; _on_path = _pl
                if _on_path is not None:
                    target = _on_path; best_d = _best_p; target_is_player = True
                else:
                    class _C: pass
                    _c_obj = _C(); _c_obj.__dict__.update({"x": c["x"], "y": c["y"], "r": CRYSTAL_R, "kind": "_crystal", "hp": c["hp"], "id": -1, "charmed": False})
                    target = _c_obj.__dict__; best_d = d_to_c; target_is_player = False
                _crystal_handled = True
            else:
                _crystal_handled = False
            if not _crystal_handled:
                for pid, pl in self.players.items():
                    if pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon"): continue
                    d = math.hypot(pl["x"] - z["x"], pl["y"] - z["y"])
                    if best_d is None or d < best_d: best_d = d; target = pl; target_is_player = True
            for o in self.zombies:
                if o is z or not o.get("charmed"): continue
                d = math.hypot(o["x"] - z["x"], o["y"] - z["y"])
                if best_d is None or d < best_d: best_d = d; target = o; target_is_player = False
            if target is None: continue
            dx = target["x"] - z["x"]; dy = target["y"] - z["y"]; d = math.hypot(dx, dy)
            if d < 1e-6: continue
            if z.get("stage50") and z.get("dash_state") == "dash": continue
            if z.get("kind") == "spitter" and target_is_player and d < SPITTER_RANGE:
                if now >= z.get("spitter_next", 0):
                    z["spitter_next"] = now + SPITTER_CD
                    ang = math.atan2(dy, dx)
                    self.spitter_bullets.append({
                        "x": z["x"] + math.cos(ang) * (zr + 6),
                        "y": z["y"] + math.sin(ang) * (zr + 6),
                        "vx": math.cos(ang) * SPITTER_SPEED, "vy": math.sin(ang) * SPITTER_SPEED,
                        "dmg": SPITTER_DMG, "life": 2.0, "r": 12,
                    })
                if d > 300:
                    step = min(zspeed * dt, d - PLAYER_R - zr)
                    if step > 0: z["x"] += dx / d * step; z["y"] += dy / d * step
                z["x"] = max(zr, min(MAP_W - zr, z["x"]))
                z["y"] = max(zr, min(MAP_H - zr, z["y"]))
                continue
            if target_is_player:
                touch = PLAYER_R + zr
                if d < touch:
                    if now - z.get("last_hit", 0) >= zcd:
                        z["last_hit"] = now; dmg = zdmg
                        if target.get("weapon") == "shield": dmg = int(dmg * (1 - SHIELD_DMG_REDUCTION))
                        target["hp"] = max(0, target["hp"] - dmg)
                        self._popup(target["x"], target["y"] - PLAYER_R - 10, dmg, (255, 80, 80))
                        if target["hp"] <= 0 and not target["dead"]:
                            target["dead"] = True; target["respawn_at"] = now + RESPAWN_DELAY
                            target["xp"] = 0; target["level"] = 0
                            self._send_stats(target["id"], {"type": "death"})
                else:
                    step = min(zspeed * dt, d - touch)
                    if step > 0: z["x"] += dx / d * step; z["y"] += dy / d * step
            else:
                touch = target.get("r", ZOMBIE_R) + zr
                if d < touch:
                    if now - z.get("last_hit", 0) >= zcd:
                        z["last_hit"] = now
                        if self.mode == MODE_CRYSTAL and self.crystal is not None:
                            self.crystal["hp"] -= zdmg
                            died = self.crystal["hp"] <= 0
                        else:
                            died = self._zombie_take_damage(target, zdmg, now)
                        if died:
                            if target.get("kind") == "kamikaze": self._kamikaze_explode(target["x"], target["y"], now)
                            if target.get("kind") == "infected": self._spawn_infected_puddle(target["x"], target["y"], now)
                            if target in self.zombies: self.zombies.remove(target)
                else:
                    step = min(zspeed * dt, d - touch)
                    if step > 0: z["x"] += dx / d * step; z["y"] += dy / d * step
            z["x"] = max(zr, min(MAP_W - zr, z["x"]))
            z["y"] = max(zr, min(MAP_H - zr, z["y"]))

    def _resolve_zombie_collisions(self):
        n = len(self.zombies)
        for i in range(n):
            a = self.zombies[i]; ar = a.get("r", ZOMBIE_R)
            for j in range(i + 1, n):
                b = self.zombies[j]; br = b.get("r", ZOMBIE_R)
                if a.get("stage50") and a.get("dash_state") == "dash": continue
                if b.get("stage50") and b.get("dash_state") == "dash": continue
                min_d = ar + br
                dx = b["x"] - a["x"]; dy = b["y"] - a["y"]; d = math.hypot(dx, dy)
                if d < 1e-6: dx, dy, d = 1.0, 0.0, 1.0
                if d < min_d:
                    ov = (min_d - d) / 2; nx, ny = dx / d, dy / d
                    a["x"] -= nx * ov; a["y"] -= ny * ov
                    b["x"] += nx * ov; b["y"] += ny * ov

    def _explode(self, x, y, radius, dmg, owner_id, now):
        self._popup(x, y, "BOOM", (255, 160, 40))
        shooter = self.players.get(owner_id)
        reward = int(zombie_reward(self.wave) * self.reward_mult)
        # === PvP: взрыв попадает в игроков (только в MODE_PVP) ===
        if self.mode == MODE_PVP:
            for _pid, _pl in self.players.items():
                if _pid == owner_id: continue
                if _pl.get("dead") or _pl.get("wanish") or _pl.get("choosing_weapon"): continue
                if math.hypot(_pl["x"] - x, _pl["y"] - y) < radius + PLAYER_R:
                    self._pvp_hit_player(owner_id, _pl, dmg, now)
        for z in list(self.zombies):
            if z.get("charmed"): continue
            zr = z.get("r", ZOMBIE_R)
            if math.hypot(z["x"] - x, z["y"] - y) < radius + zr:
                died = self._zombie_take_damage(z, dmg, now)
                if died:
                    if shooter:
                        xr = z.get("xp_reward", reward); xc = self._coins_reward(z) if z.get("coins_reward") else reward
                        shooter["xp"] += xr; shooter["coins"] += xc
                        shooter["level"] = level_from_xp(shooter["xp"])
                    self._send_stats(owner_id, {"type": "kill", "boss": z.get("boss", False)})
                    self._maybe_forbidden_drop(z, owner_id)
                    self._check_not_funny_on_kill(z)
                    if z.get("kind") == "kamikaze" and not z.get("_exploded"):
                        z["_exploded"] = True
                        self._kamikaze_explode(z["x"], z["y"], now)
                    if z.get("kind") == "infected": self._spawn_infected_puddle(z["x"], z["y"], now)
                    self._kill_zombie(z)

    def _check_team_wipe(self):
        if self.game_over or not self.players: return
        alive_players = [p for p in self.players.values() if not p["dead"] and not p.get("choosing_weapon")]
        if not alive_players: return
        if not any(not p["dead"] and not p.get("wanish") and not p.get("choosing_weapon") for p in self.players.values()):
            self.game_over = True; self._broadcast({"type": "game_over"})

    def _update_turrets(self, now, dt):
        for b in self.buildings:
            # === Ремонтная турель: лечит ближайшую повреждённую barricade ===
            if b["kind"] == BUILD_REPAIR_TURRET:
                if b["hp"] <= 0: continue
                _owner = self.players.get(b.get("owner"))
                _rep_cd = REPAIR_TURRET_CD
                if _owner is not None and _owner.get("passive") == "фиксик":
                    _rep_cd *= 0.8
                if now - b.get("next_repair", 0) < _rep_cd: continue
                target = None; best_d = None
                for other in self.buildings:
                    if other is b: continue
                    if other["kind"] != BUILD_BARRICADE: continue
                    if other["hp"] >= other["max_hp"]: continue
                    d = math.hypot(other["x"] - b["x"], other["y"] - b["y"])
                    if d <= REPAIR_TURRET_RANGE and (best_d is None or d < best_d):
                        best_d = d; target = other
                if target is not None:
                    target["hp"] = target["max_hp"]
                    b["next_repair"] = now
                    b["angle"] = math.atan2(target["y"] - b["y"], target["x"] - b["x"])
                    self._popup(target["x"], target["y"] - BARRICADE_GRID / 2 - 10,
                                "REM", (120, 240, 120))
                else:
                    b["next_repair"] = now
                continue
            if b["kind"] not in (BUILD_TURRET, BUILD_FIRE_TURRET, BUILD_ELECTRIC_TURRET): continue
            if b["hp"] <= 0: continue
            target = None; best_d = None
            for z in self.zombies:
                if z.get("charmed"): continue
                d = math.hypot(z["x"] - b["x"], z["y"] - b["y"])
                if d <= TURRET_RANGE and (best_d is None or d < best_d): best_d = d; target = z
            if target is None: continue
            dx = target["x"] - b["x"]; dy = target["y"] - b["y"]
            b["angle"] = math.atan2(dy, dx)
            cd = (TURRET_SHOOT_CD if b["kind"] == BUILD_TURRET
                  else (ELECTRIC_TURRET_CD if b["kind"] == BUILD_ELECTRIC_TURRET
                        else FIRE_TURRET_SHOOT_CD))
            # === ПАССИВКА "СКОРОСТРЕЛ": +30% скорострельности владельцу ===
            _owner = self.players.get(b.get("owner"))
            if _owner is not None and _owner.get("passive") == "скорострел":
                cd *= 0.7
            if now - b.get("next_shot", 0) < cd: continue
            b["next_shot"] = now; a = b["angle"]
            if b["kind"] == BUILD_TURRET:
                self.turret_bullets.append({
                    "x": b["x"] + math.cos(a) * 25, "y": b["y"] + math.sin(a) * 25,
                    "vx": math.cos(a) * TURRET_BULLET_SPEED, "vy": math.sin(a) * TURRET_BULLET_SPEED,
                    "dmg": TURRET_DMG, "life": 1.2, "owner": b["owner"],
                })
            elif b["kind"] == BUILD_ELECTRIC_TURRET:
                self.electric_turret_bullets.append({
                    "x": b["x"] + math.cos(a) * 25, "y": b["y"] + math.sin(a) * 25,
                    "vx": math.cos(a) * ELECTRIC_TURRET_BULLET_SPEED,
                    "vy": math.sin(a) * ELECTRIC_TURRET_BULLET_SPEED,
                    "dmg": ELECTRIC_TURRET_DMG, "life": 1.5, "owner": b["owner"], "r": 8,
                })
            else:
                self.turret_bullets.append({
                    "x": b["x"] + math.cos(a) * 25, "y": b["y"] + math.sin(a) * 25,
                    "vx": math.cos(a) * FIRE_TURRET_BULLET_SPEED, "vy": math.sin(a) * FIRE_TURRET_BULLET_SPEED,
                    "dmg": FIRE_TURRET_DMG, "life": 2.0, "owner": b["owner"],
                    "pierce_left": FIRE_TURRET_PIERCE, "fire": True, "r": 12, "hit_ids": set(),
                })
        alive = []
        for tb in self.turret_bullets:
            tb["x"] += tb["vx"] * dt; tb["y"] += tb["vy"] * dt
            tb["life"] -= dt
            if tb["life"] <= 0: continue
            if not (0 <= tb["x"] <= MAP_W and 0 <= tb["y"] <= MAP_H): continue
            hit = False
            for z in list(self.zombies):
                if z.get("charmed"): continue
                zr = z.get("r", ZOMBIE_R); tb_r = tb.get("r", 6)
                if math.hypot(z["x"] - tb["x"], z["y"] - tb["y"]) >= zr + tb_r: continue
                if "hit_ids" in tb and z["id"] in tb["hit_ids"]: continue
                if "hit_ids" in tb: tb["hit_ids"].add(z["id"])
                died = self._zombie_take_damage(z, tb["dmg"], now)
                self._popup(z["x"], z["y"] - zr - 10, tb["dmg"],
                            (255, 120, 40) if tb.get("fire") else (255, 255, 255))
                if tb.get("fire"):
                    z["fire_until"] = max(z.get("fire_until", 0), now) + FIRE_DURATION
                    z["fire_next_tick"] = now; z["last_burner"] = tb.get("owner")
                if died:
                    shooter = self.players.get(tb.get("owner"))
                    rw = int(zombie_reward(self.wave) * self.reward_mult)
                    xr = z.get("xp_reward", rw); xc = self._coins_reward(z) if z.get("coins_reward") else rw
                    if shooter:
                        shooter["xp"] += xr; shooter["coins"] += xc
                        shooter["level"] = level_from_xp(shooter["xp"])
                    self._send_stats(tb.get("owner"), {"type": "kill", "boss": z.get("boss", False)})
                    self._maybe_forbidden_drop(z, tb.get("owner"))
                    self._check_not_funny_on_kill(z)
                    if z.get("kind") == "kamikaze" and not z.get("_exploded"):
                        z["_exploded"] = True
                        self._kamikaze_explode(z["x"], z["y"], now)
                    if z.get("kind") == "infected": self._spawn_infected_puddle(z["x"], z["y"], now)
                    self._kill_zombie(z)
                p = tb.get("pierce_left", 0)
                if p > 0: tb["pierce_left"] = p - 1
                else: hit = True; break
            if hit: continue
            alive.append(tb)
        self.turret_bullets = alive

        # === электрические снаряды ===
        el_alive = []
        for eb in self.electric_turret_bullets:
            eb["x"] += eb["vx"] * dt; eb["y"] += eb["vy"] * dt
            eb["life"] -= dt
            if eb["life"] <= 0: continue
            if not (0 <= eb["x"] <= MAP_W and 0 <= eb["y"] <= MAP_H): continue
            hit = False
            for z in list(self.zombies):
                if z.get("charmed"): continue
                zr = z.get("r", ZOMBIE_R)
                if math.hypot(z["x"] - eb["x"], z["y"] - eb["y"]) >= zr + eb.get("r", 8): continue
                died = self._zombie_take_damage(z, eb["dmg"], now)
                self._popup(z["x"], z["y"] - zr - 10, eb["dmg"], (180, 220, 255))
                self._electric_chain(z, eb.get("owner"))
                hit = True
                break
            if hit: continue
            el_alive.append(eb)
        self.electric_turret_bullets = el_alive


    def _update_final_boss_bullets(self, now, dt):
        """Самонаводящиеся пули финального босса.
        Раз в FINAL_BOSS_HOMING_CD сек, живут FINAL_BOSS_HOMING_LIFE сек,
        наносят 50% от текущего HP при попадании."""
        # 1) пуск
        for z in self.zombies:
            if not z.get("final", False): continue
            if z.get("charmed") or z.get("hp", 0) <= 0: continue
            if now >= z.get("homing_next", 0):
                z["homing_next"] = now + FINAL_BOSS_HOMING_CD
                # цель — ближайший живой игрок
                tgt = None; best = None
                for pl in self.players.values():
                    if pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon"): continue
                    d = math.hypot(pl["x"] - z["x"], pl["y"] - z["y"])
                    if best is None or d < best: best = d; tgt = pl
                if tgt is None: continue
                ang = math.atan2(tgt["y"] - z["y"], tgt["x"] - z["x"])
                self.final_boss_bullets.append({
                    "x": z["x"] + math.cos(ang) * (z.get("r", ZOMBIE_R) + 10),
                    "y": z["y"] + math.sin(ang) * (z.get("r", ZOMBIE_R) + 10),
                    "vx": math.cos(ang) * FINAL_BOSS_HOMING_SPEED,
                    "vy": math.sin(ang) * FINAL_BOSS_HOMING_SPEED,
                    "angle": ang,
                    "life": FINAL_BOSS_HOMING_LIFE,
                    "owner": None,
                    "target_id": tgt["id"],
                    "r": FINAL_BOSS_HOMING_R,
                })
        # 2) полёт
        alive = []
        for b in self.final_boss_bullets:
            b["life"] -= dt
            if b["life"] <= 0: continue
            # самонаведение на target_id (если жив)
            tgt = self.players.get(b.get("target_id"))
            if tgt is not None and not tgt["dead"] and not tgt.get("wanish"):
                want = math.atan2(tgt["y"] - b["y"], tgt["x"] - b["x"])
                cur = b["angle"]
                diff = math.atan2(math.sin(want - cur), math.cos(want - cur))
                mt = FINAL_BOSS_HOMING_TURN * dt
                diff = max(-mt, min(mt, diff))
                b["angle"] = cur + diff
                b["vx"] = math.cos(b["angle"]) * FINAL_BOSS_HOMING_SPEED
                b["vy"] = math.sin(b["angle"]) * FINAL_BOSS_HOMING_SPEED
            b["x"] += b["vx"] * dt
            b["y"] += b["vy"] * dt
            if not (0 <= b["x"] <= MAP_W and 0 <= b["y"] <= MAP_H): continue
            hit = False
            for pl in self.players.values():
                if pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon"): continue
                if math.hypot(pl["x"] - b["x"], pl["y"] - b["y"]) < PLAYER_R + b["r"]:
                    if pl.get("weapon") == "shield":
                        pass  # щит не спасает от %-урона
                    dmg = int(pl["hp"] * FINAL_BOSS_HOMING_DMG_FRAC)
                    if dmg < 1: dmg = 1
                    pl["hp"] = max(0, pl["hp"] - dmg)
                    self._popup(pl["x"], pl["y"] - PLAYER_R - 10, dmg, (255, 60, 200))
                    if pl["hp"] <= 0 and not pl["dead"]:
                        pl["dead"] = True; pl["respawn_at"] = now + RESPAWN_DELAY
                        pl["xp"] = 0; pl["level"] = 0
                        self._send_stats(pl["id"], {"type": "death"})
                    hit = True; break
            if hit: continue
            alive.append(b)
        self.final_boss_bullets = alive

    def _update_spitter_bullets(self, dt, now):
        alive = []
        half = BARRICADE_GRID / 2
        for b in self.spitter_bullets:
            b["x"] += b["vx"] * dt; b["y"] += b["vy"] * dt; b["life"] -= dt
            if b["life"] <= 0: continue
            if not (0 <= b["x"] <= MAP_W and 0 <= b["y"] <= MAP_H): continue
            # 1) Столкновение с постройками (raycast по отрезку)
            old_x = b["x"] - b["vx"] * dt
            old_y = b["y"] - b["vy"] * dt
            half = BARRICADE_GRID / 2
            hit_building = False
            for bd in list(self.buildings):
                left = bd["x"] - half; right = bd["x"] + half
                top = bd["y"] - half; bottom = bd["y"] + half
                # расширим прямоугольник на радиус снаряда
                rx = left - b["r"]; ry = top - b["r"]
                rw = (right - left) + 2 * b["r"]; rh = (bottom - top) + 2 * b["r"]
                if _seg_rect_hit(old_x, old_y, b["x"], b["y"], rx, ry, rw, rh):
                    self._damage_building(bd, SPITTER_BUILDING_DMG, now)
                    hit_building = True
                    break
            if hit_building: continue
            # 2) Столкновение с игроками
            hit = False
            for pl in self.players.values():
                if pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon"): continue
                if math.hypot(pl["x"] - b["x"], pl["y"] - b["y"]) < PLAYER_R + b["r"]:
                    dmg = b["dmg"]
                    if pl.get("weapon") == "shield": dmg = int(dmg * (1 - SHIELD_DMG_REDUCTION))
                    pl["hp"] = max(0, pl["hp"] - dmg)
                    self._popup(pl["x"], pl["y"] - PLAYER_R - 10, dmg, (200, 200, 60))
                    if pl["hp"] <= 0 and not pl["dead"]:
                        pl["dead"] = True; pl["respawn_at"] = now + RESPAWN_DELAY
                        pl["xp"] = 0; pl["level"] = 0
                        self._send_stats(pl["id"], {"type": "death"})
                    hit = True; break
            if hit: continue
            alive.append(b)
        self.spitter_bullets = alive
    def _update_puddles(self, now):
        alive = []
        for pd in self.puddles:
            if now >= pd["until"]: continue
            if now >= pd.get("next_tick", 0):
                pd["next_tick"] = now + 1.0
                for pl in self.players.values():
                    if pl["dead"] or pl.get("wanish") or pl.get("choosing_weapon"): continue
                    if math.hypot(pl["x"] - pd["x"], pl["y"] - pd["y"]) < pd["r"] + PLAYER_R:
                        dmg = int(INFECTED_PUDDLE_DPS)
                        pl["hp"] = max(0, pl["hp"] - dmg)
                        self._popup(pl["x"], pl["y"] - PLAYER_R - 10, dmg, (120, 200, 120))
                        if pl["hp"] <= 0 and not pl["dead"]:
                            pl["dead"] = True; pl["respawn_at"] = now + RESPAWN_DELAY
                            pl["xp"] = 0; pl["level"] = 0
                            self._send_stats(pl["id"], {"type": "death"})
            alive.append(pd)
        self.puddles = alive

    def _safe(self, name, fn, *a, **kw):
        try: fn(*a, **kw)
        except Exception as e:
            print(f"[safe] {name}: {e}"); traceback.print_exc()

    def _tick_loop(self):
        last = time.time(); last_broadcast = last
        while self.running:
            try:
                now = time.time(); dt = now - last; last = now
                if dt < 0.001: dt = 0.001
                max_dt = 3.0 / TICK_RATE
                if dt > max_dt: dt = max_dt
                time.sleep(1 / TICK_RATE)
                MOD_API.call("on_tick", self, now, dt)
                if not self.game_over:
                    self._safe("waves", self._update_waves, now)
                    self._safe("crystal", self._update_crystal, now, dt)
                    self._safe("zombies", self._update_zombies, now, dt)
                    self._safe("zombie_buildings", self._resolve_zombie_buildings, now)
                    self._safe("zombie_collisions", self._resolve_zombie_collisions)
                    self._safe("lasers", self._update_lasers, now)
                    self._safe("turrets", self._update_turrets, now, dt)
                    self._safe("spitter_bullets", self._update_spitter_bullets, dt, now)
                    self._safe("final_boss_bullets", self._update_final_boss_bullets, now, dt)
                    self._safe("puddles", self._update_puddles, now)
                self._safe("sounds", self._emit_zombie_sounds, now)
                self._safe("pickups", self._handle_pickups)
                self._safe("bullets", self._update_bullets, dt, now)
                self._safe("meteors", self._update_meteors, now)
                self._safe("multi_hit", self._process_multi_hit_queue, now)
                self._safe("burn", self._update_burning, now)
                self._safe("popups", self._update_popups, dt)
                self._safe("respawn", self._update_respawn, now)
                self._safe("wipe", self._check_team_wipe)
                if now - last_broadcast >= 1 / SEND_RATE:
                    last_broadcast = now
                    self._safe("broadcast", self._broadcast_state, now)
                if self.solo:
                    self.solo_save_timer += dt
                    if self.solo_save_timer >= 1.0:
                        self.solo_save_timer = 0.0
                        try:
                            write_solo_save(self._serialize_solo())
                        except Exception as e:
                            print("[solo_save] ошибка автосейва:", e)
            except Exception as e:
                print("[tick] outer error:", e); traceback.print_exc(); time.sleep(0.05)

    def _emit_zombie_sounds(self, now):
        for z in self.zombies:
            if now >= z.get("next_sound_at", 0):
                z["next_sound_at"] = now + 3.0
                self._broadcast({"type": "zombie_sound", "x": z["x"], "y": z["y"],
                                 "boss": z.get("boss", False), "final": z.get("final", False),
                                 "charmed": z.get("charmed", False)})

    def _handle_pickups(self):
        for pid, pl in list(self.players.items()):
            if pl["dead"] or pl.get("choosing_weapon"): continue
            for cr in list(self.crates):
                if math.hypot(pl["x"] - cr["x"], pl["y"] - cr["y"]) < CRATE_TOUCH_R:
                    if cr.get("weapon"):
                        wkey = cr["weapon"]
                        if wkey not in pl.get("owned_weapons", []):
                            pl["owned_weapons"].append(wkey)
                            self._assign_to_first_free_slot(pl, wkey)
                        self._send(pid, {"type": "weapon_unlocked", "key": wkey})
                        self.crates.remove(cr)
                        break
                    for bkey in cr["buffs"]:
                        pl["inventory"][bkey] = pl["inventory"].get(bkey, 0) + 1
                    pl["coins"] += cr["coins"]; pl["xp"] += cr["xp"]
                    pl["level"] = level_from_xp(pl["xp"])
                    self._send(pid, {"type": "crate_opened", "rarity": cr["rarity"],
                                      "color": cr["color"], "buffs": cr["buffs"],
                                      "coins": cr["coins"], "xp": cr["xp"]})
                    MOD_API.call("on_crate_opened", self, pl, cr)
                    self._add_euphoria(pl, 5)
                    self.crates.remove(cr); break
            for fi in list(self.forbidden_items):
                if math.hypot(pl["x"] - fi["x"], pl["y"] - fi["y"]) < FORBIDDEN_TOUCH_R:
                    pl["forbidden_count"] = pl.get("forbidden_count", 0) + 1
                    self._send(pid, {"type": "forbidden_get"})
                    self.forbidden_items.remove(fi)
            for sh in list(self.prism_shards):
                if math.hypot(pl["x"] - sh["x"], pl["y"] - sh["y"]) < PRISM_SHARD_TOUCH_R:
                    pl["prism_shards"] = pl.get("prism_shards", 0) + 1
                    if pl["prism_shards"] >= PRISM_SHARDS_NEEDED and not pl.get("last_prism_unlocked"):
                        pl["last_prism_unlocked"] = True
                        self._send(pid, {"type": "last_prism_unlocked"})
                    self._add_euphoria(pl, 10)
                    self._send(pid, {"type": "prism_shard_get",
                                      "count": pl["prism_shards"]})
                    self.prism_shards.remove(sh)
            for sd in list(self.stardust_items):
                if math.hypot(pl["x"] - sd["x"], pl["y"] - sd["y"]) < STARDUST_TOUCH_R:
                    pl["stardust"] = pl.get("stardust", 0) + 1
                    if pl["stardust"] >= STARDUST_NEEDED and not pl.get("true_star_unlocked"):
                        pl["true_star_unlocked"] = True
                        self._send(pid, {"type": "true_star_unlocked"})
                    self._add_euphoria(pl, 10)
                    self._send(pid, {"type": "stardust_get", "count": pl["stardust"]})
                    self.stardust_items.remove(sd)

    def _update_bullets(self, dt, now):
        reward = int(zombie_reward(self.wave) * self.reward_mult)
        alive = []
        for b in self.bullets:
            if b.get("homing"):
                target = None; best_d = None
                _homing_r = 1500 if b.get("secret_beam") else STAR_HOMING_RADIUS
                for z in self.zombies:
                    if z.get("charmed"): continue
                    d = math.hypot(z["x"] - b["x"], z["y"] - b["y"])
                    if d <= _homing_r and (best_d is None or d < best_d): best_d = d; target = z
                if target is not None:
                    dx = target["x"] - b["x"]; dy = target["y"] - b["y"]
                    ta = math.atan2(dy, dx); cur = b.get("angle", ta)
                    diff = math.atan2(math.sin(ta - cur), math.cos(ta - cur))
                    _turn = 8.0 if b.get("secret_beam") else STAR_TURN_RATE
                    mt = _turn * dt; diff = max(-mt, min(mt, diff))
                    na = cur + diff
                    b["angle"] = na; b["vx"] = math.cos(na) * b.get("speed", STAR_SPEED); b["vy"] = math.sin(na) * b.get("speed", STAR_SPEED)
            seg = math.hypot(b["vx"] * dt, b["vy"] * dt)
            b["traveled"] = b.get("traveled", 0.0) + seg
            # falloff дробовика убран; sniper оставлен как есть
            wkey = b.get("weapon", "")
            if wkey == "sniper":
                b["dmg"] = int(max(20, 45 + b["traveled"] * 0.5))
            old_x = b["x"]; old_y = b["y"]
            b["x"] += b["vx"] * dt; b["y"] += b["vy"] * dt; b["life"] -= dt
            if b["life"] <= 0: continue
            if not (0 <= b["x"] <= MAP_W and 0 <= b["y"] <= MAP_H): continue
            hit = False
            # === PvP: попадание в игрока (только в MODE_PVP) ===
            if self.mode == MODE_PVP and not b.get("charmed"):
                for _pid, _pl in self.players.items():
                    if _pid == b.get("owner"): continue
                    if _pl.get("dead") or _pl.get("wanish") or _pl.get("choosing_weapon"): continue
                    if not _seg_circle_hit(old_x, old_y, b["x"], b["y"], _pl["x"], _pl["y"], PLAYER_R): continue
                    self._pvp_hit_player(b.get("owner"), _pl, b["dmg"], now)
                    hit = True; break
                if hit: continue
            for z in list(self.zombies):
                if z.get("charmed"): continue
                zr = z.get("r", ZOMBIE_R)
                if not _seg_circle_hit(old_x, old_y, b["x"], b["y"], z["x"], z["y"], zr): continue
                if b.get("special"): self._star_explode(b["x"], b["y"], b["owner"], now); hit = True; break
                if b.get("explosive"):
                    self._explode(b["x"], b["y"], b["explosive"], b["dmg"], b["owner"], now); hit = True; break
                if b.get("meteor"):
                    if not any(m["target_id"] == z["id"] for m in self.meteors):
                        self.meteors.append({"x": z["x"], "y": z["y"], "hit_at": now + METEOR_DELAY, "target_id": z["id"]})
                    hit = True; break
                _ak = b.get("ammo_kind")
                if _ak:
                    _handler = MOD_API.ammo_hits.get(_ak)
                    if _handler:
                        try:
                            _handler(self, b, z)
                        except Exception as _e:
                            print("[mods] ammo hit error:", _e)
                    hit = True
                    break
                died = self._zombie_take_damage(z, b["dmg"], now)
                MOD_API.call("on_bullet_hit", self, b, z)
                self._popup(z["x"], z["y"] - zr - 10, b["dmg"], (255, 255, 255))
                if b.get("firedoom"):
                    z["fire_until"] = max(z.get("fire_until", 0), now) + FIRE_DURATION
                    z["fire_next_tick"] = now; z["last_burner"] = b["owner"]
                if b.get("freeze"):
                    z["frozen_until"] = max(z.get("frozen_until", 0), now) + b["freeze"]
                if b.get("charm"):
                    is_boss = z.get("boss", False) or z.get("final", False)
                    ch = b.get("charm_boss_chance", 0.05) if is_boss else b.get("charm_chance", 0.15)
                    if random.random() < ch: self._charm_zombie(z, now)
                if b.get("hexagon"): self._spawn_hexagon_shadows(z, now)
                if died:
                    shooter = self.players.get(b["owner"])
                    xr = z.get("xp_reward", reward); xc = self._coins_reward(z) if z.get("coins_reward") else reward
                    if shooter:
                        shooter["xp"] += xr; shooter["coins"] += xc
                        shooter["level"] = level_from_xp(shooter["xp"])
                    self._send_stats(b["owner"], {"type": "kill", "boss": z.get("boss", False)})
                    self._maybe_forbidden_drop(z, b["owner"])
                    self._check_not_funny_on_kill(z)
                    self._maybe_drop_special(z, b["owner"], b.get("weapon", ""))
                    # Эйфория: +1 за обычного, +10 за босса
                    _e = 10 if z.get("boss", False) else 1
                    self._add_euphoria(shooter, _e, now)
                    # Дроп бафа: 10% шанс, только при убийстве пистолетом (weapon == "base")
                    if b.get("weapon", "") == "base":
                        self._maybe_drop_buff_from_zombie(z, b["owner"], now)
                    if z.get("kind") == "kamikaze" and not z.get("_exploded"):
                        z["_exploded"] = True
                        self._kamikaze_explode(z["x"], z["y"], now)
                    if z.get("kind") == "infected": self._spawn_infected_puddle(z["x"], z["y"], now)
                    self._kill_zombie(z)
                pierce = b.get("pierce_left", 0)
                if pierce > 0: b["pierce_left"] = pierce - 1
                else: hit = True
                break
            if hit: continue
            alive.append(b)
        self.bullets = alive

    def _update_meteors(self, now):
        for m in list(self.meteors):
            target = None
            for z in self.zombies:
                if z["id"] == m["target_id"]: target = z; break
            if target is None: self.meteors.remove(m); continue
            m["x"], m["y"] = target["x"], target["y"]
            if now >= m["hit_at"]:
                for z in list(self.zombies):
                    if z.get("charmed"): continue
                    zr = z.get("r", ZOMBIE_R)
                    if math.hypot(z["x"] - m["x"], z["y"] - m["y"]) < 120 + zr:
                        died = self._zombie_take_damage(z, METEOR_DMG, now)
                        self._popup(z["x"], z["y"] - zr - 10, METEOR_DMG, (255, 80, 40))
                        if died:
                            if z.get("kind") == "kamikaze" and not z.get("_exploded"):
                                z["_exploded"] = True
                                self._kamikaze_explode(z["x"], z["y"], now)
                            if z.get("kind") == "infected": self._spawn_infected_puddle(z["x"], z["y"], now)
                            self._kill_zombie(z)
                self.meteors.remove(m)
    def _update_burning(self, now):
        for z in list(self.zombies):
            if z.get("charmed"): continue
            if z.get("fire_until", 0) > now and now >= z.get("fire_next_tick", 0):
                z["fire_next_tick"] = now + 1.0
                zr = z.get("r", ZOMBIE_R)
                self._popup(z["x"], z["y"] - zr - 10, FIRE_DPS, (255, 160, 30))
                died = self._zombie_take_damage(z, FIRE_DPS, now)
                if died:
                    self._on_zombie_killed(z, z.get("last_burner"), None, "burning")

    def _update_popups(self, dt):
        alive = []
        for p in self.damage_popups:
            p["t"] += dt
            if p["t"] < p["life"]: alive.append(p)
        self.damage_popups = alive

    def _update_respawn(self, now):
        for pl in self.players.values():
            if pl["dead"] and now >= pl["respawn_at"] and not self.game_over:
                pl["x"], pl["y"] = self._spawn()
                pl["hp"] = MAX_HP; pl["dead"] = False
                MOD_API.call("on_player_respawn", self, pl)

    def _broadcast_state(self, now):
        visible_players = []
        with self.lock:
            for pid, pl in self.players.items():
                visible_players.append(pl)
        self._broadcast({
            "type": "state", "server_time": now,
            "players": visible_players,
            "bullets": self.bullets, "zombies": self.zombies,
            "spitter_bullets": self.spitter_bullets,
            "final_boss_bullets": self.final_boss_bullets,
            "turret_bullets": self.turret_bullets,
            "electric_turret_bullets": self.electric_turret_bullets,
            "puddles": self.puddles,
            "buildings": self.buildings, "building_cells": list(self.building_cells),
            "crates": self.crates, "meteors": self.meteors,
            "popups": self.damage_popups, "forbidden_items": self.forbidden_items,
            "wave": self.wave, "wave_state": self.wave_state,
            "wave_total": self.wave_total, "wave_killed": self.wave_killed,
            "wave_break_until": self.wave_break_until,
            "victory": self.victory, "game_over": self.game_over,
            "max_wave": self.max_wave,
            "wave_button_active": self.wave_button_active,
            "wave_button_x": self.wave_button_x,
            "wave_button_y": self.wave_button_y,
        })

    def _announce_loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            try: s.sendto(f"SHOOTER|{self.port}|{self.name}|{self.stage}".encode(),
                          ("255.255.255.255", DISCOVERY_PORT))
            except Exception: pass
            time.sleep(1.0)

    def stop(self):
        self.running = False
        if self.srv:
            try: self.srv.close()
            except Exception: pass
        with self.lock:
            for c in self.clients.values():
                try: c["sock"].close()
                except Exception: pass
            self.clients.clear()


class Client:
    def request_mod(self, name):
        self.send({"type": "mod_request", "name": name})
    def send_mods_ack(self):
        self._mods_ack_sent = True
        self.pending_mods = []
        self.send({"type": "mods_ack"})

    def _save_mod_file(self, m):
        """Атомарная запись мода: пишем в tmp, проверяем sha256, и только
        при совпадении переносим в addon/<id>/. Никогда не оставляем
        недописанный/неподписанный файл в addon/."""
        name = m.get("name", "?")
        mid_raw = m.get("id") or ""
        # id должен быть безопасным для имени папки
        if not isinstance(mid_raw, str) or not re.match(r"^[A-Za-z0-9_\-]{1,64}$", mid_raw):
            getattr(self, "mod_errors", []).append((str(name), "bad id"))
            return
        mod_id = mid_raw
        script = m.get("script", "")
        sha_exp = m.get("sha256", "")
        if not isinstance(script, str) or not isinstance(sha_exp, str):
            getattr(self, "mod_errors", []).append((name, "bad fields"))
            return
        # проверяем sha256 ДО записи в addon/
        import hashlib as _hl
        sha_act = _hl.sha256(script.encode("utf-8")).hexdigest()
        if sha_exp and sha_act != sha_exp:
            getattr(self, "mod_errors", []).append((name, "sha256 mismatch (pre-write)"))
            return
        try:
            root = os.path.join(ADDON_DIR, mod_id)
            os.makedirs(os.path.join(root, "script"), exist_ok=True)
            manifest = {"name": name, "description": m.get("description", ""),
                        "script": "script/main.py"}
            script_path = os.path.join(root, "script", "main.py")
            manifest_path = os.path.join(root, "manifest.json")
            # пишем во временные файлы в той же папке
            tmp_script = script_path + ".tmp"
            tmp_manifest = manifest_path + ".tmp"
            with open(tmp_script, "w", encoding="utf-8") as f:
                f.write(script)
            with open(tmp_manifest, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            # финальная проверка sha по уже записанному tmp
            with open(tmp_script, "rb") as f:
                sha2 = _hl.sha256(f.read()).hexdigest()
            if sha_exp and sha2 != sha_exp:
                for p in (tmp_script, tmp_manifest):
                    try: os.remove(p)
                    except Exception: pass
                getattr(self, "mod_errors", []).append((name, "sha256 mismatch (post-write)"))
                return
            os.replace(tmp_script, script_path)
            os.replace(tmp_manifest, manifest_path)
            self._mods_downloaded.add(mod_id)
            print(f"[mod] скачан: {name} -> {root}")
        except Exception as e:
            getattr(self, "mod_errors", []).append((name, f"save: {e}"))
            # убираем возможные хвосты
            try:
                for p in (os.path.join(ADDON_DIR, mod_id, "script", "main.py.tmp"),
                          os.path.join(ADDON_DIR, mod_id, "manifest.json.tmp")):
                    if os.path.isfile(p): os.remove(p)
            except Exception:
                pass

    def __init__(self, host, port, on_welcome, console_enabled=True, on_cheat=None, my_stage=0,
                 my_wins=0, my_unlocks=None, my_achievements=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(None)
        self.sock.connect((host, port))
        try:
            self.sock.sendall(encode({
                "type": "hello", "stage": int(my_stage),
                "wins": int(my_wins),
                "unlocks": list(my_unlocks or []),
                "achievements": list(my_achievements or []),
            }))
        except Exception: pass
        self.buf = bytearray(); self.lock = threading.Lock()
        self.msgs = []; self.my_id = None; self.is_admin = False
        self.connected = True; self.on_welcome = on_welcome; self.on_cheat = on_cheat
        self.kills_pending = 0; self.deaths_pending = 0; self.wins_pending = 0
        self.apple_eat_events = []; self.zombie_sound_events = []
        self.crate_popups = []; self.forbidden_pickups = 0
        self.achievements_pending = []
        self.server_cheats = False; self.server_wins = 0; self.no_stage = False
        self.no_stats = False
        self.cheat_used_pending = False
        self.prism_shard_gets = 0; self.stardust_gets = 0
        self.true_star_unlocked = False; self.last_prism_unlocked = False
        self.prism_shards_local = 0; self.stardust_local = 0
        # === МОДЫ ===
        self.server_mods = []
        self.pending_mods = []
        self.mod_errors = []
        self._mods_downloaded = set()
        self._mods_required_evt = threading.Event()
        threading.Thread(target=self._recv, daemon=True).start()
        if console_enabled: threading.Thread(target=self._console_loop, daemon=True).start()

    def _recv(self):
        try:
            while self.connected:
                data = self.sock.recv(16384)
                if not data: break
                self.buf.extend(data)
                try: msgs = decode_from_buffer(self.buf)
                except Exception: self.buf.clear(); continue
                for m in msgs:
                    t = m.get("type")
                    if t == "welcome":
                        self.my_id = m["id"]; self.is_admin = bool(m.get("is_admin", False))
                        self.server_cheats = bool(m.get("cheats", False))
                        self.server_wins = int(m.get("wins", 0))
                        self.no_stats = bool(m.get("no_stats", False))
                        self.on_welcome(m)
                    elif t == "no_stage":
                        self.no_stage = True; self.connected = False
                        with self.lock: self.msgs.append(m); return
                    elif t == "kill": self.kills_pending += 1
                    elif t == "death": self.deaths_pending += 1
                    elif t == "win": self.wins_pending += 1
                    elif t == "forbidden_get": self.forbidden_pickups += 1
                    elif t == "achievement": self.achievements_pending.append(m.get("key"))
                    elif t == "unlock":
                        with self.lock: self.msgs.append(m)
                    elif t == "weapon_unlocked":
                        with self.lock: self.msgs.append(m)
                    elif t == "cheat_used": self.cheat_used_pending = True
                    elif t == "prism_shard_get":
                        self.prism_shard_gets += 1
                        self.prism_shards_local = m.get("count", self.prism_shards_local + 1)
                    elif t == "stardust_get":
                        self.stardust_gets += 1
                        self.stardust_local = m.get("count", self.stardust_local + 1)
                    elif t == "true_star_unlocked": self.true_star_unlocked = True
                    elif t == "last_prism_unlocked": self.last_prism_unlocked = True
                    elif t == "apple_eat": self.apple_eat_events.append((m.get("x", 0), m.get("y", 0)))
                    elif t == "mod_file":
                        self._save_mod_file(m)
                    elif t == "mod_error":
                        getattr(self, "mod_errors", []).append(
                            (m.get("id", "?"), m.get("reason", "?")))
                        _bad_id = m.get("id")
                        if _bad_id and hasattr(self, "_mods_pending_ids"):
                            try: self._mods_pending_ids.discard(_bad_id)
                            except Exception: pass
                    elif t == "zombie_sound":
                        self.zombie_sound_events.append((m.get("x", 0), m.get("y", 0),
                                                          m.get("boss", False), m.get("final", False)))
                    elif t == "crate_opened":
                        self.crate_popups.append({"rarity": m.get("rarity", "rare"),
                                                   "color": m.get("color", [60, 200, 60]),
                                                   "buffs": m.get("buffs", []),
                                                   "coins": m.get("coins", 0), "xp": m.get("xp", 0)})
                    else:
                        try:
                            MOD_API.on_custom_message(self, m)
                        except Exception:
                            pass
                    with self.lock: self.msgs.append(m)
        except Exception: pass
        self.connected = False

    def _console_loop(self):
        while self.connected:
            try: line = input()
            except (EOFError, KeyboardInterrupt): return
            except Exception: continue
            if not line: continue
            self.send({"type": "console", "line": line})

    def send(self, msg):
        try: self.sock.sendall(encode(msg))
        except Exception: self.connected = False

    def poll(self):
        with self.lock:
            out = self.msgs[:]; self.msgs.clear()
        return out

    def close(self):
        self.connected = False
        try: self.sock.close()
        except Exception: pass


def discover(timeout=1.0):
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.bind(("", DISCOVERY_PORT)); s.settimeout(0.15)
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(1024)
                parts = data.decode("utf-8", "ignore").split("|")
                if len(parts) >= 3 and parts[0] == "SHOOTER":
                    p = int(parts[1]); n = parts[2]
                    stage = int(parts[3]) if len(parts) > 3 else 0
                    found[(addr[0], p)] = (addr[0], p, n, stage)
            except socket.timeout: continue
    except OSError: pass
    finally: s.close()
    return list(found.values())


class Button:
    def __init__(self, rect, text, color=(60, 60, 90)):
        self.rect = pygame.Rect(rect); self.text = text; self.color = color
        self.toggle = False; self.is_toggle = False; self.active = False

    def draw(self, surf, font, mouse):
        h = self.rect.collidepoint(mouse)
        base = self.color
        if self.is_toggle and self.toggle: base = (220, 80, 40)
        if self.active: base = (220, 180, 60)
        c = tuple(min(255, v + 30) for v in base) if h else base
        pygame.draw.rect(surf, c, self.rect, border_radius=8)
        pygame.draw.rect(surf, (200, 200, 220), self.rect, 2, border_radius=8)
        t = font.render(self.text, True, (240, 240, 240))
        surf.blit(t, t.get_rect(center=self.rect.center))

    def clicked(self, e):
        if e.type == pygame.FINGERDOWN:
            return self.rect.collidepoint((e.x * WIDTH, e.y * HEIGHT))
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            return self.rect.collidepoint(e.pos)
        return False

    def clicked_touch(self, e):
        if e.type == pygame.FINGERDOWN:
            return self.rect.collidepoint((e.x * WIDTH, e.y * HEIGHT))
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            return self.rect.collidepoint(e.pos)
        return False


class Joystick:
    def __init__(self, cx, cy, r):
        self.cx, self.cy, self.r = cx, cy, r
        self.knob = (cx, cy); self.active = False
        self.value = (0.0, 0.0); self.finger_id = None

    def handle(self, e):
        if e.type == pygame.FINGERDOWN:
            fx = e.x * WIDTH; fy = e.y * HEIGHT
            if math.hypot(fx - self.cx, fy - self.cy) < self.r * 1.5:
                self.finger_id = e.finger_id; self.active = True
                self._move((fx, fy)); return True
        elif e.type == pygame.FINGERMOTION:
            if self.finger_id == e.finger_id:
                self._move((e.x * WIDTH, e.y * HEIGHT)); return True
        elif e.type == pygame.FINGERUP:
            if self.finger_id == e.finger_id:
                self.finger_id = None; self.active = False
                self.knob = (self.cx, self.cy); self.value = (0.0, 0.0); return True
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and not self.active:
            if math.hypot(e.pos[0] - self.cx, e.pos[1] - self.cy) < self.r * 1.5:
                self.active = True; self._move(e.pos); return True
        elif e.type == pygame.MOUSEMOTION and self.active and self.finger_id is None:
            self._move(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.finger_id is None:
            if self.active:
                self.active = False; self.knob = (self.cx, self.cy)
                self.value = (0.0, 0.0); return True
        return False

    def _move(self, pos):
        dx = pos[0] - self.cx; dy = pos[1] - self.cy
        d = math.hypot(dx, dy)
        if d > self.r: dx, dy = dx / d * self.r, dy / d * self.r
        self.knob = (self.cx + dx, self.cy + dy)
        self.value = (dx / self.r, dy / self.r)

    def draw(self, surf):
        pygame.draw.circle(surf, (255, 255, 255), (self.cx, self.cy), self.r)
        pygame.draw.circle(surf, (120, 120, 160), (self.cx, self.cy), self.r, 3)
        pygame.draw.circle(surf, (90, 90, 200), (int(self.knob[0]), int(self.knob[1])), self.r // 2)


QWERTY_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
QWERTY_SHIFT = ["!@#$%^&*()", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
YAQWERTY_ROWS = ["1234567890", "йцукенгшщзхъ", "фывапролджэ", "ячсмитьбюё"]
YAQWERTY_SHIFT = ["!\"№;%:?*()_", "ЙЦУКЕНГШЩЗХЪ", "ФЫВАПРОЛДЖЭ", "ЯЧСМИТЬБЮЁ"]
SYMBOLS = ["@#$%^&*()_+", "-=[]{};:'\",.", "<>/\\|~`?"]


class ChatKeyboard:
    def __init__(self):
        self.open = False; self.lang = "ru"; self.shift = False
        self.symbols_mode = False; self.text = ""; self.max_len = CHAT_MAX_LEN
        self.keys = []; self.width = WIDTH; self.height = 380
        self.y0 = HEIGHT - self.height - 10
        self.prompt_override = None
        self._rebuild()

    def _rebuild(self):
        self.keys = []
        if self.symbols_mode: rows = SYMBOLS
        elif self.lang == "ru": rows = YAQWERTY_SHIFT if self.shift else YAQWERTY_ROWS
        else: rows = QWERTY_SHIFT if self.shift else QWERTY_ROWS
        top_row = "1234567890"; pad = 6; top_y = self.y0 + 10; key_h = 42
        kw = (self.width - 20 - pad * (len(top_row) - 1)) / len(top_row)
        for i, ch in enumerate(top_row):
            self.keys.append((pygame.Rect(10 + i * (kw + pad), top_y, kw, key_h), ch, "char"))
        rows_y = top_y + key_h + pad
        for ri, row in enumerate(rows):
            n = len(row)
            if n == 0: continue
            kw = (self.width - 40 - pad * (n - 1)) / n
            xs = (self.width - (kw * n + pad * (n - 1))) / 2
            y = rows_y + ri * (key_h + pad)
            for i, ch in enumerate(row):
                self.keys.append((pygame.Rect(xs + i * (kw + pad), y, kw, key_h), ch, "char"))
        bottom_y = rows_y + len(rows) * (key_h + pad) + 4
        bw, bh = 90, 42
        self.keys.append((pygame.Rect(10, bottom_y, bw, bh), "?123" if not self.symbols_mode else "ABC", "mode"))
        self.keys.append((pygame.Rect(10 + bw + pad, bottom_y, bw, bh), "SHIFT" if not self.shift else "shft", "shift"))
        self.keys.append((pygame.Rect(10 + 2 * (bw + pad), bottom_y, bw, bh), "RU" if self.lang == "ru" else "EN", "lang"))
        sx = 10 + 3 * (bw + pad); sw = self.width - sx - 220
        self.keys.append((pygame.Rect(sx, bottom_y, sw, bh), " ", "space"))
        self.keys.append((pygame.Rect(self.width - 210, bottom_y, 100, bh), "⌫", "back"))
        self.keys.append((pygame.Rect(self.width - 100, bottom_y, 90, bh), "✓", "enter"))
        self.keys.append((pygame.Rect(self.width - 100, top_y, 90, key_h), "✕", "close"))

    def open_kb(self): self.open = True; self.text = ""; self.symbols_mode = False; self._rebuild()
    def close_kb(self): self.open = False; self.text = ""

    def handle(self, e):
        if not self.open: return None
        pos = None; pressed = False
        if e.type == pygame.FINGERDOWN:
            pos = (e.x * WIDTH, e.y * HEIGHT); pressed = True
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            pos = e.pos; pressed = True
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_RETURN: return self._enter()
            if e.key == pygame.K_BACKSPACE: self.text = self.text[:-1]; return None
            if e.key == pygame.K_ESCAPE: self.close_kb(); return None
            ch = e.unicode
            if ch and ch.isprintable() and len(self.text) < self.max_len: self.text += ch
            return None
        if not pressed: return None
        if pos[1] < self.y0: self.close_kb(); return None
        for r, ch, kind in self.keys:
            if not r.collidepoint(pos): continue
            if kind == "char":
                if len(self.text) < self.max_len: self.text += ch
                if self.shift and not self.symbols_mode: self.shift = False; self._rebuild()
            elif kind == "space":
                if len(self.text) < self.max_len: self.text += " "
            elif kind == "back": self.text = self.text[:-1]
            elif kind == "enter": return self._enter()
            elif kind == "close": self.close_kb(); return None
            elif kind == "shift": self.shift = not self.shift; self._rebuild()
            elif kind == "lang": self.lang = "en" if self.lang == "ru" else "ru"; self.symbols_mode = False; self._rebuild()
            elif kind == "mode": self.symbols_mode = not self.symbols_mode; self.shift = False; self._rebuild()
            return None
        return None

    def _enter(self):
        text = self.text.strip()
        if not text: return None
        self.close_kb(); return text

    def draw(self, surf, font, small):
        if not self.open: return
        overlay = pygame.Surface((WIDTH, self.height), pygame.SRCALPHA)
        overlay.fill((20, 20, 40, 230)); surf.blit(overlay, (0, self.y0))
        pygame.draw.line(surf, (200, 200, 220), (0, self.y0), (WIDTH, self.y0), 3)
        if self.prompt_override:
            prompt = self.text if self.text else self.prompt_override
        else:
            prompt = self.text if self.text else "Введите текст..."
        col = (240, 240, 240) if self.text else (140, 140, 160)
        pt = font.render(prompt, True, col)
        pygame.draw.rect(surf, (10, 10, 25), (10, self.y0 - 44, WIDTH - 20, 36), border_radius=6)
        pygame.draw.rect(surf, (120, 120, 180), (10, self.y0 - 44, WIDTH - 20, 36), 2, border_radius=6)
        surf.blit(pt, (20, self.y0 - 38))
        mouse = pygame.mouse.get_pos()
        for r, ch, kind in self.keys:
            h = r.collidepoint(mouse)
            if kind == "enter": base = (60, 140, 60)
            elif kind == "close": base = (150, 50, 50)
            elif kind == "shift": base = (100, 100, 40) if self.shift else (60, 60, 90)
            elif kind == "lang": base = (40, 100, 140)
            elif kind == "mode": base = (100, 60, 130)
            else: base = (60, 60, 90)
            c = tuple(min(255, v + 30) for v in base) if h else base
            pygame.draw.rect(surf, c, r, border_radius=6)
            pygame.draw.rect(surf, (200, 200, 220), r, 2, border_radius=6)
            label = ch if ch != " " else "ПРОБЕЛ"
            if ch == "shft": label = "SHIFT"
            tt = small.render(label, True, (240, 240, 240))
            surf.blit(tt, tt.get_rect(center=r.center))



class App:
    def __init__(self):
        try: self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        except Exception:
            try: self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.SCALED)
            except Exception: self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Piu piu.io")
        self.real_w, self.real_h = self.screen.get_size()
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        # === PIXELATE ===
        self.pixel_w = max(1, WIDTH // PIXEL_SCALE)
        self.pixel_h = max(1, HEIGHT // PIXEL_SCALE)
        self.pixel_canvas = pygame.Surface((self.pixel_w, self.pixel_h))
        self.pixel_out = pygame.Surface((WIDTH, HEIGHT))
        self.overlay_canvas = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 22)
        self.big = pygame.font.SysFont("arial", 44, bold=True)
        self.huge = pygame.font.SysFont("arial", 64, bold=True)
        self.menu_title = pygame.font.SysFont("arial", 90, bold=True)
        self.small = pygame.font.SysFont("arial", 16)
        self.tiny = pygame.font.SysFont("arial", 14)
        self.audio_ok = _init_mixer()
        self.snd_shoot = _load_sound("music/shoot.ogg") if self.audio_ok else None
        self.music_menu_started = False
        self.music_game_started = False
        self._music_warned = False
        self.snd_swo = _load_sound("music/swo.ogg") if self.audio_ok else None
        self.snd_apple = _load_sound("music/apple.ogg") if self.audio_ok else None
        self.snd_zombie = _load_sound("music/zombie.ogg") if self.audio_ok else None
        self.state = "menu"; self.host = None; self.client = None; self.my_id = None
        self.force_connecting = False
        self.is_admin = False; self.server_time_offset = 0.0
        self.server_full_msg = ""; self.info_msg = ""; self.info_msg_until = 0.0
        self.trophies = load_gamestate(); self.cheated_this_session = False
        # Input mode
        self.input_mode = self.trophies.get("input_mode", "touch")
        self.mouse_held = False
        self.keys_held = set()
        # Первый запуск
        self.btn_choose_pc = Button((WIDTH//2 - 350, HEIGHT//2 - 50, 280, 100), "ПК", (60, 90, 140))
        self.btn_choose_touch = Button((WIDTH//2 + 70, HEIGHT//2 - 50, 280, 100), "Сенсор", (60, 130, 90))
        # Если первый запуск — идём на экран выбора
        if not self.trophies.get("not_first", False):
            self.state = "choose_input"
        self.new_server_mode = MODE_NORMAL
        self.new_server_difficulty = DIFF_NORMAL
        self.new_server_cheats = False
        self.btn_play = Button((WIDTH//2 - 130, HEIGHT//2 - 130, 260, 70), "ИГРАТЬ")
        self.btn_solo = Button((WIDTH//2 - 130, HEIGHT//2 - 40, 260, 70), "СОЛО", (90, 50, 130))
        self.btn_settings = Button((WIDTH//2 - 130, HEIGHT//2 + 50, 260, 60), "НАСТРОЙКИ", (70, 70, 110))
        self.btn_stats = Button((WIDTH//2 - 130, HEIGHT//2 + 130, 260, 60), "СТАТИСТИКА", (60, 100, 60))
        self.btn_plus = Button((WIDTH//2 - 110, HEIGHT - 110, 220, 60), "+ Создать сервер", (40, 120, 60))
        self.btn_back = Button((30, HEIGHT - 80, 120, 50), "Назад")
        self.btn_auto = Button((WIDTH - 180, HEIGHT - 320, 60, 60), "A", (60, 60, 90))
        self.btn_auto.is_toggle = True
        self.shop_open = None
        # Магазин: плавный вертикальный скролл.
        self._shop_scroll_target = 0.0
        self._shop_scroll_cur = 0.0
        self._shop_scroll_max = 0.0
        self.slot_picker = None
        self.weapon_desc_popup = None
        self.btn_shop_weapons = Button((WIDTH - 170, 10, 160, 44), "МАГАЗИН", (100, 80, 140))
        self.btn_shop_buffs = Button((-500, -500, 1, 1), "", (0,0,0))
        self.btn_shop_build = Button((-500, -500, 1, 1), "", (0,0,0))
        self.btn_shop_passives = Button((-500, -500, 1, 1), "", (0,0,0))
        _s = load_settings()
        self.button_mode = _s.get("button_mode", "default")
        self.show_barricade_preview = _s.get("show_barricade_preview", False)
        self.pixelate = _s.get("pixelate", True)
        self.keybinds = dict(DEFAULT_KEYBINDS)
        try:
            _kb = _s.get("keybinds", {})
            if isinstance(_kb, dict):
                for k, v in _kb.items():
                    if k in DEFAULT_KEYBINDS:
                        self.keybinds[k] = v
        except Exception:
            pass
        self.btn_mode_default = Button((WIDTH//2 - 220, HEIGHT//2 - 20, 200, 70), "Обычное", (60, 60, 90))
        self.btn_mode_center = Button((WIDTH//2 + 20, HEIGHT//2 - 20, 200, 70), "По середине", (60, 60, 90))
        self.btn_preview_toggle = Button((WIDTH//2 - 240, HEIGHT//2 + 90, 480, 60),
                                          "Показать обводку баррикады: ВЫКЛ", (60, 60, 90))
        self.btn_input_toggle = Button((WIDTH//2 - 240, HEIGHT//2 + 170, 480, 60),
                                        "Управление: Сенсор", (90, 70, 120))
        self.btn_keybinds = Button((WIDTH//2 - 240, HEIGHT//2 + 240, 480, 55),
                                    "Настройка раскладки", (60, 80, 140))
        self.btn_pixelate = Button((WIDTH//2 - 240, HEIGHT//2 + 310, 480, 55),
                                    "Пиксельность: ВКЛ", (100, 70, 140))
        self.btn_keybinds_back = Button((30, 30, 140, 55), "Назад", (60, 60, 90))
        self.btn_keybinds_reset = Button((WIDTH//2 - 100, HEIGHT - 80, 200, 50), "Сбросить", (140, 60, 60))
        self.kb_active_row = None
        self.kb_scroll = 0.0
        self._kb_drag_start = None
        self._kb_drag_dy = 0
        self.btn_settings_back = Button((30, 30, 140, 55), "Назад", (60, 60, 90))
        self.btn_stats_back = Button((WIDTH//2 - 100, HEIGHT - 100, 200, 55), "Назад", (60, 60, 90))
        self.btn_sv_back = Button((30, HEIGHT - 80, 120, 50), "Назад")
        self.btn_sv_start = Button((WIDTH//2 - 130, HEIGHT - 100, 260, 70), "НАЧАТЬ", (40, 140, 60))
        self.sv_mode_buttons = []; self.sv_diff_buttons = []
        self.btn_sv_cheats = Button((WIDTH//2 - 160, HEIGHT//2 + 100, 320, 60), "Читы: ВЫКЛ", (60, 60, 90))
        self.btn_sv_mods = Button((WIDTH//2 - 160, HEIGHT//2 + 170, 320, 60),
                                  "МОДЫ", (60, 100, 140))
        self.mods_warning = None
        self.mods_warning_btn = Button((WIDTH//2 - 180, HEIGHT//2 + 140, 360, 60),
                                       "Загрузить", (60, 140, 60))
        self.mods_warning_close = Button((WIDTH//2 - 180, HEIGHT//2 + 220, 360, 60),
                                         "Отмена", (120, 60, 60))
        self._mods_pending_ids = set()
        self._mods_download_deadline = 0.0
        self._build_server_settings_buttons()
        self._apply_button_mode(); self._refresh_settings_buttons()
        self.hotbar_slot_size = 60; self.hotbar_gap = 8
        self.hotbar_rects = []; self.hotbar_keys = []; self.hotbar_is_item = []
        self.servers = []; self.last_disc = 0; self.disc_thread = None
        self.map_w, self.map_h = MAP_W, MAP_H
        self.players = {}; self.bullets = []
        self.zombies = []; self.meteors = []; self.popups = []
        self.buildings = []; self.building_cells = []
        self.turret_bullets = []; self.crates = []; self.lasers = []
        self.spitter_bullets = []; self.puddles = []
        self.final_boss_bullets = []
        self.forbidden_items = []; self.forbidden_count_local = 0
        self.wave = 0; self.wave_state = "break"; self.wave_total = 0
        self.wave_killed = 0; self.wave_break_until = 0
        self.victory = False; self.max_wave_current = 100
        self.server_wins = 0
        self.camera = [0.0, 0.0]
        self.move_joy = Joystick(150, HEIGHT - 150, 100)
        self.aim_joy = Joystick(WIDTH - 150, HEIGHT - 150, 100)
        self.last_shot = 0; self.status = ""
        self.local_x = 0.0; self.local_y = 0.0; self.local_init = False
        self.btn_chat_open = Button((WIDTH//2 + 100, 60, 60, 44), "C", (60, 100, 140))
        self.chat_kb = ChatKeyboard()
        self.barricade_mode = False
        self.barricade_hover = (WIDTH // 2, HEIGHT // 2)
        self.crate_popup = None
        self.unlock_popup = None
        self.unlock_popup_close = Button((WIDTH//2 - 100, HEIGHT - 130, 200, 55), "Продолжить", (40, 120, 60))
        self.achievement_popup = None
        self.achievement_popup_close = Button((WIDTH//2 - 100, HEIGHT - 130, 200, 55), "OK", (40, 120, 60))
        self.solo_mode = False
        self._weapon_sprite_cache = {}
        self._zombie_sprite_cache = {}
        self.drop_menu_open = False
        self.prism_shards_local = 0
        self.stardust_local = 0
        self.true_star_unlocked = False
        self.last_prism_unlocked = False
        self.choosing_weapon = False
        self.choose_btn_base = None
        self.choose_btn_rifle = None
        self.choose_btn_shotgun = None
        self.wave_button_active = False
        self.wave_button_x = MAP_W / 2
        self.wave_button_y = MAP_H / 2
        # Меню-фон
        self._menu_zombies = []
        self._menu_time = 0.0
        self._init_menu_zombies()
        self.tutorial = None
        # Курсор — спрятать если ПК
        if self.input_mode == "pc":
            try: pygame.mouse.set_visible(False)
            except Exception: pass

    # ============================================================
    #  МЕНЮ-ФОН
    # ============================================================

    def _init_menu_zombies(self):
        self._menu_zombies = []
        for _ in range(60):
            self._menu_zombies.append(self._make_menu_zombie(random_start=True))

    def _make_menu_zombie(self, random_start=False):
        kind = random.choice(list(ZOMBIE_TYPES.keys()))
        t = ZOMBIE_TYPES[kind]
        r = int(ZOMBIE_R * t["r_mult"] * random.uniform(0.6, 1.0))
        y = random.uniform(-50, HEIGHT + 50)
        if random_start:
            x = random.uniform(-200, WIDTH + 400)
        else:
            x = WIDTH + random.uniform(50, 300)
        speed = 60 + random.uniform(-15, 30)
        return {"x": x, "y": y, "r": r, "kind": kind, "speed": speed,
                "phase": random.uniform(0, math.tau), "body": t["color"]}

    def _update_menu_bg(self, dt):
        self._menu_time += dt
        for z in self._menu_zombies:
            z["x"] -= z["speed"] * dt
            z["y"] += math.sin(self._menu_time * 3 + z["phase"]) * 0.3
            if z["x"] < -200:
                z.update(self._make_menu_zombie())

    def _draw_menu_bg(self):
        self.screen.fill((18, 30, 18))
        for z in self._menu_zombies:
            sx = int(z["x"]); sy = int(z["y"]); r = z["r"]
            dark = tuple(max(0, c - 40) for c in z["body"])
            pygame.draw.circle(self.screen, (12, 20, 12), (sx + 4, sy + 6), r + 2)
            pygame.draw.circle(self.screen, dark, (sx, sy), r)
            eye_off = r // 3; eye_r = max(3, r // 8)
            pygame.draw.circle(self.screen, (180, 40, 40), (sx - eye_off, sy - eye_off // 2), eye_r)
            pygame.draw.circle(self.screen, (180, 40, 40), (sx + eye_off, sy - eye_off // 2), eye_r)
        vig = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        for i in range(0, 200, 8):
            a = int(140 * (1 - i / 200))
            pygame.draw.rect(vig, (0, 0, 0, a), (i, i, WIDTH - 2*i, HEIGHT - 2*i), 8)
        self.screen.blit(vig, (0, 0))

    # ============================================================
    #  АРСЕНАЛ / ОРУЖИЕ
    # ============================================================
    _WEAPON_LEN = {
        "hammer": 52, "wrench": 46,
        "base": 26, "rifle": 50, "shotgun": 48, "smg": 38,
        "sniper": 62, "laser": 54, "plasma": 42,
        "sword": 52, "charm_sword": 52, "cursed_sword": 56,
        "shield": 34, "stone": 50, "meteor": 52,
        "charm_staff": 52, "star": 46, "hexagon": 52,
        "first_prism": 54, "last_prism": 54, "true_star": 46,
        "secret_beam": 40,
        "bow": 40,
    }
    _WEAPON_SIDE = {"sword", "charm_sword", "cursed_sword", "hammer", "wrench",
                     "stone", "meteor", "charm_staff", "hexagon"}

    def _weapon_sprite(self, wkey, angle):
        # === мод может отдать свой спрайт ===
        try:
            _rd = MOD_API.weapon_renderers.get(wkey)
            if _rd and _rd.get("sprite"):
                _surf = _rd["sprite"](angle)
                if _surf is not None:
                    return _surf
        except Exception as _e:
            print("[mods] weapon sprite error:", _e)
        bucket = int(round(angle / (math.pi / 36))) % 72
        key = (wkey, bucket)
        cached = self._weapon_sprite_cache.get(key)
        if cached is not None: return cached
        length = self._WEAPON_LEN.get(wkey, 30)
        side = wkey in self._WEAPON_SIDE
        size = length + 40
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        cx = size // 2; cy = size // 2
        if side: self._draw_weapon_shape_side(surf, cx, cy, wkey, length)
        else: self._draw_weapon_shape_fwd(surf, cx, cy, wkey, length)
        rotated = pygame.transform.rotate(surf, -math.degrees(angle))
        self._weapon_sprite_cache[key] = rotated
        return rotated

    def _draw_weapon_shape_fwd(self, surf, cx, cy, wkey, L):
        if wkey == "base":
            pygame.draw.rect(surf, (60, 60, 70), (cx, cy - 4, L, 8), border_radius=2)
            pygame.draw.rect(surf, (90, 90, 100), (cx + 2, cy + 2, 8, 8), border_radius=2)
        elif wkey == "rifle":
            pygame.draw.rect(surf, (60, 60, 70), (cx, cy - 4, L, 8), border_radius=2)
            pygame.draw.rect(surf, (90, 90, 100), (cx + 10, cy + 4, 10, 14), border_radius=2)
            pygame.draw.rect(surf, (40, 40, 50), (cx - 4, cy - 6, 12, 12), border_radius=3)
        elif wkey == "shotgun":
            pygame.draw.rect(surf, (60, 60, 70), (cx, cy - 6, L, 5), border_radius=2)
            pygame.draw.rect(surf, (60, 60, 70), (cx, cy + 1, L, 5), border_radius=2)
            pygame.draw.rect(surf, (80, 55, 30), (cx - 6, cy - 5, 12, 12), border_radius=2)
        elif wkey == "smg":
            pygame.draw.rect(surf, (50, 50, 60), (cx, cy - 5, L, 10), border_radius=3)
            pygame.draw.rect(surf, (30, 30, 40), (cx + 6, cy + 3, 8, 16), border_radius=2)
        elif wkey == "sniper":
            pygame.draw.rect(surf, (60, 60, 70), (cx, cy - 3, L, 6), border_radius=2)
            pygame.draw.rect(surf, (90, 90, 100), (cx + 14, cy - 10, 14, 5), border_radius=2)
            pygame.draw.rect(surf, (50, 50, 60), (cx - 6, cy - 4, 12, 10), border_radius=2)
        elif wkey in ("laser", "first_prism", "last_prism"):
            col = (70, 70, 80)
            if wkey == "first_prism": col = (220, 220, 240)
            elif wkey == "last_prism": col = (255, 255, 255)
            pygame.draw.rect(surf, col, (cx, cy - 6, L, 12), border_radius=3)
            cap_col = (255, 255, 255) if wkey in ("first_prism", "last_prism") else (220, 40, 40)
            pygame.draw.rect(surf, cap_col, (cx + L - 6, cy - 8, 6, 16), border_radius=2)
        elif wkey == "plasma":
            pygame.draw.rect(surf, (70, 60, 90), (cx, cy - 5, L, 10), border_radius=3)
            pygame.draw.circle(surf, (150, 100, 255), (cx + L, cy), 7)
        elif wkey == "shield":
            pts = [(cx + 6, cy - 14), (cx + 24, cy - 8), (cx + 22, cy + 8),
                   (cx + 6, cy + 14), (cx - 6, cy + 8), (cx - 8, cy - 8)]
            pygame.draw.polygon(surf, (180, 200, 240), pts)
            pygame.draw.polygon(surf, (60, 80, 140), pts, 3)
        elif wkey == "star":
            pygame.draw.rect(surf, (90, 80, 60), (cx, cy - 5, L, 10), border_radius=3)
            pts = []
            for k in range(16):
                ang = k * math.pi / 8; rad = 10 if k % 2 == 0 else 4
                pts.append((cx + L + math.cos(ang) * rad, cy + math.sin(ang) * rad))
            pygame.draw.polygon(surf, (255, 220, 80), pts)
        elif wkey == "secret_beam":
            # книга
            pygame.draw.rect(surf, (60, 20, 80), (cx, cy - 18, L, 36), border_radius=3)
            pygame.draw.rect(surf, (200, 160, 255), (cx, cy - 18, L, 36), 2, border_radius=3)
            pygame.draw.line(surf, (200, 160, 255), (cx + L // 2, cy - 16), (cx + L // 2, cy + 16), 2)
            pygame.draw.circle(surf, (255, 240, 120), (cx + L // 2, cy), 5)
        elif wkey == "true_star":
            pygame.draw.rect(surf, (90, 80, 60), (cx, cy - 6, L, 12), border_radius=3)
            pts = []
            for k in range(16):
                ang = k * math.pi / 8; rad = 14 if k % 2 == 0 else 6
                pts.append((cx + L + math.cos(ang) * rad, cy + math.sin(ang) * rad))
            pygame.draw.polygon(surf, (255, 250, 180), pts)
            pygame.draw.polygon(surf, (255, 255, 255), pts, 2)

    def _draw_weapon_shape_side(self, surf, cx, cy, wkey, L):
        if wkey in ("sword", "charm_sword", "cursed_sword"):
            col = {"sword": (220, 220, 230), "charm_sword": (255, 150, 220),
                   "cursed_sword": (200, 140, 240)}[wkey]
            pygame.draw.rect(surf, (90, 60, 30), (cx - 3, cy - 4, 6, 14), border_radius=2)
            pts = [(cx - 4, cy - 6), (cx + 4, cy - 6), (cx + 3, cy - L), (cx, cy - L - 6), (cx - 3, cy - L)]
            pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, (40, 40, 50), pts, 2)
        elif wkey in ("stone", "meteor", "charm_staff"):
            pygame.draw.rect(surf, (110, 70, 40), (cx - 2, cy - L, 4, L), border_radius=2)
            if wkey == "stone":
                pygame.draw.circle(surf, (140, 140, 150), (cx, cy - L - 4), 8)
                pygame.draw.circle(surf, (220, 220, 230), (cx - 2, cy - L - 6), 3)
            elif wkey == "meteor":
                pygame.draw.circle(surf, (200, 120, 255), (cx, cy - L - 4), 8)
                pygame.draw.circle(surf, (255, 240, 160), (cx - 2, cy - L - 6), 3)
            else:
                pygame.draw.circle(surf, (255, 150, 220), (cx, cy - L - 4), 8)
                pygame.draw.circle(surf, (255, 240, 250), (cx - 2, cy - L - 6), 3)
        elif wkey == "hammer":
            # рукоять
            pygame.draw.rect(surf, (110, 70, 40), (cx - 3, cy - L, 6, L), border_radius=2)
            # голова молота
            pygame.draw.rect(surf, (170, 170, 180), (cx - 14, cy - L - 16, 28, 16), border_radius=3)
            pygame.draw.rect(surf, (60, 60, 70), (cx - 14, cy - L - 16, 28, 16), 2, border_radius=3)
        elif wkey == "wrench":
            # рукоять
            pygame.draw.rect(surf, (150, 150, 160), (cx - 3, cy - L, 6, L), border_radius=2)
            # рожковый ключ — два «зуба»
            pygame.draw.circle(surf, (180, 180, 190), (cx, cy - L - 6), 10, 3)
            pygame.draw.rect(surf, (200, 200, 210), (cx - 12, cy - L - 12, 6, 14), border_radius=2)
            pygame.draw.rect(surf, (200, 200, 210), (cx + 6, cy - L - 12, 6, 14), border_radius=2)

        elif wkey == "hexagon":
            pygame.draw.rect(surf, (60, 60, 60), (cx - 3, cy - L, 6, L), border_radius=2)
            pts = []
            for k in range(6):
                ang = k * math.pi / 3 - math.pi / 6
                pts.append((cx + math.cos(ang) * 10, cy - L - 4 + math.sin(ang) * 10))
            pygame.draw.polygon(surf, (20, 20, 20), pts)
            pygame.draw.polygon(surf, (200, 200, 200), pts, 2)
        elif wkey == "bow":
            # Лук: дуга + тетива
            pts = []
            for k in range(-4, 5):
                ang = k * math.pi / 8 + math.pi / 2
                pts.append((cx + math.cos(ang) * 22, cy + math.sin(ang) * 22))
            pygame.draw.lines(surf, (139, 69, 19), False, pts, 4)
            pygame.draw.line(surf, (200, 200, 200), (int(pts[0][0]), int(pts[0][1])), (int(pts[-1][0]), int(pts[-1][1])), 1)

    def _draw_weapon_in_hand(self, sx, sy, wkey, angle):
        if not wkey or wkey == "fist": return
        sprite = self._weapon_sprite(wkey, angle)
        hx = sx + math.cos(angle) * (PLAYER_R - 6); hy = sy + math.sin(angle) * (PLAYER_R - 6)
        self.screen.blit(sprite, sprite.get_rect(center=(hx, hy)))

    def _draw_weapon_icon(self, wkey, r):
        cx, cy = r.centerx, r.centery
        # === мод может нарисовать сам ===
        try:
            _rd = MOD_API.weapon_renderers.get(wkey)
            if _rd and _rd.get("icon"):
                _rd["icon"](self.screen, r)
                return
        except Exception as _e:
            print("[mods] weapon icon error:", _e)
        if wkey == "fist":
            pygame.draw.circle(self.screen, (220, 180, 140),
                               (int(cx), int(cy)), 14)
            for k in range(4):
                ang = math.pi * 0.15 + k * 0.18
                pygame.draw.line(self.screen, (150, 110, 80),
                                 (cx + 6, cy - 8 + k * 5),
                                 (cx + 6 + 10 * math.cos(ang),
                                  cy - 8 + k * 5 + 10 * math.sin(ang)), 3)
            return
        if wkey == "base":
            pygame.draw.line(self.screen, (220, 220, 220), (cx - 12, cy + 8), (cx + 10, cy - 8), 5)
            pygame.draw.circle(self.screen, (200, 200, 220), (cx - 12, cy + 8), 5)
        elif wkey == "rifle":
            pygame.draw.line(self.screen, (200, 220, 255), (cx - 16, cy), (cx + 14, cy), 6)
            pygame.draw.rect(self.screen, (120, 140, 200), (cx - 8, cy + 3, 8, 12), border_radius=2)
        elif wkey == "shotgun":
            pygame.draw.line(self.screen, (240, 200, 100), (cx - 16, cy - 3), (cx + 14, cy - 3), 5)
            pygame.draw.line(self.screen, (200, 160, 60), (cx - 16, cy + 4), (cx + 12, cy + 4), 5)
        elif wkey == "smg":
            pygame.draw.rect(self.screen, (150, 220, 150), (cx - 16, cy - 5, 24, 10), border_radius=3)
            pygame.draw.rect(self.screen, (80, 80, 100), (cx + 6, cy - 8, 6, 16), border_radius=3)
        elif wkey == "sniper":
            pygame.draw.line(self.screen, (180, 220, 255), (cx - 18, cy), (cx + 16, cy), 5)
            pygame.draw.circle(self.screen, (255, 255, 255), (cx + 6, cy - 6), 4)
        elif wkey in ("laser", "first_prism", "last_prism"):
            col = (255, 80, 80)
            if wkey == "first_prism": col = (220, 220, 240)
            elif wkey == "last_prism": col = (255, 255, 255)
            pygame.draw.line(self.screen, col, (cx - 16, cy), (cx + 16, cy), 6)
            pygame.draw.circle(self.screen, (255, 255, 255), (cx + 16, cy), 5)
        elif wkey == "plasma":
            pygame.draw.circle(self.screen, (150, 100, 255), (int(cx), int(cy)), 16)
            pygame.draw.circle(self.screen, (255, 220, 255), (int(cx), int(cy)), 6)
        elif wkey == "sword":
            pygame.draw.line(self.screen, (110, 70, 40), (cx - 16, cy + 14), (cx - 4, cy + 2), 5)
            pygame.draw.line(self.screen, (220, 220, 230), (cx - 4, cy + 2), (cx + 16, cy - 14), 6)
        elif wkey == "charm_sword":
            pygame.draw.line(self.screen, (110, 70, 40), (cx - 16, cy + 14), (cx - 4, cy + 2), 5)
            pygame.draw.line(self.screen, (255, 150, 220), (cx - 4, cy + 2), (cx + 16, cy - 14), 6)
        elif wkey == "cursed_sword":
            pygame.draw.circle(self.screen, (140, 60, 200), (int(cx), int(cy)), max(8, r.width // 2 - 4), 2)
            pygame.draw.line(self.screen, (60, 20, 80), (cx - 16, cy + 14), (cx - 4, cy + 2), 5)
            pygame.draw.line(self.screen, (200, 140, 240), (cx - 4, cy + 2), (cx + 16, cy - 14), 6)
        elif wkey == "stone":
            pygame.draw.line(self.screen, (170, 170, 180), (cx - 10, cy + 14), (cx + 8, cy - 10), 5)
            pygame.draw.circle(self.screen, (140, 140, 150), (cx + 10, cy - 12), 7)
        elif wkey == "meteor":
            pygame.draw.line(self.screen, (180, 100, 255), (cx - 10, cy + 14), (cx + 8, cy - 10), 5)
            pygame.draw.circle(self.screen, (200, 120, 255), (cx + 10, cy - 12), 7)
        elif wkey == "charm_staff":
            pygame.draw.line(self.screen, (160, 90, 160), (cx - 10, cy + 14), (cx + 8, cy - 10), 5)
            pygame.draw.circle(self.screen, (255, 150, 220), (cx + 10, cy - 12), 8)
        elif wkey == "shield":
            pts = [(cx, cy - 18), (cx + 16, cy - 8), (cx + 14, cy + 10),
                   (cx, cy + 18), (cx - 14, cy + 10), (cx - 16, cy - 8)]
            pygame.draw.polygon(self.screen, (180, 200, 240), pts)
            pygame.draw.polygon(self.screen, (60, 80, 140), pts, 3)
        elif wkey == "star":
            pts = []
            for k in range(16):
                ang = k * math.pi / 8; rad = 16 if k % 2 == 0 else 6
                pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
            pygame.draw.polygon(self.screen, (255, 220, 80), pts)
        elif wkey == "true_star":
            pts = []
            for k in range(16):
                ang = k * math.pi / 8; rad = 18 if k % 2 == 0 else 7
                pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
            pygame.draw.polygon(self.screen, (255, 250, 180), pts)
            pygame.draw.polygon(self.screen, (255, 255, 255), pts, 2)
        elif wkey == "hammer":
            # рукоять
            pygame.draw.line(self.screen, (110, 70, 40),
                             (cx - 12, cy + 14), (cx + 6, cy - 10), 6)
            # голова
            pygame.draw.rect(self.screen, (170, 170, 180),
                             (cx + 2, cy - 18, 20, 12), border_radius=3)
            pygame.draw.rect(self.screen, (60, 60, 70),
                             (cx + 2, cy - 18, 20, 12), 2, border_radius=3)
        elif wkey == "wrench":
            # рукоять
            pygame.draw.line(self.screen, (150, 150, 160),
                             (cx - 12, cy + 14), (cx + 6, cy - 10), 6)
            # рожковый ключ
            pygame.draw.circle(self.screen, (180, 180, 190), (cx + 8, cy - 12), 8, 3)
            pygame.draw.rect(self.screen, (200, 200, 210),
                             (cx - 2, cy - 20, 6, 10), border_radius=2)
            pygame.draw.rect(self.screen, (200, 200, 210),
                             (cx + 12, cy - 20, 6, 10), border_radius=2)

        elif wkey == "secret_beam":
            # книга
            pygame.draw.rect(self.screen, (60, 20, 80), (cx - 12, cy - 16, 24, 32), border_radius=3)
            pygame.draw.rect(self.screen, (200, 160, 255), (cx - 12, cy - 16, 24, 32), 2, border_radius=3)
            pygame.draw.line(self.screen, (200, 160, 255), (cx, cy - 14), (cx, cy + 14), 2)
            pygame.draw.circle(self.screen, (255, 240, 120), (int(cx), int(cy)), 4)
        elif wkey == "hexagon":
            pts = []
            for k in range(6):
                ang = k * math.pi / 3 - math.pi / 6
                pts.append((cx + math.cos(ang) * 16, cy + math.sin(ang) * 16))
            pygame.draw.polygon(self.screen, (30, 30, 30), pts)
            pygame.draw.polygon(self.screen, (200, 200, 200), pts, 3)
            for k in range(3):
                ang = k * 2 * math.pi / 3
                pygame.draw.circle(self.screen, (160, 160, 160),
                                    (int(cx + math.cos(ang) * 7), int(cy + math.sin(ang) * 7)), 3)
        elif wkey == "bow":
            # Иконка лука
            pts = []
            for k in range(-3, 4):
                ang = k * math.pi / 6 + math.pi / 2
                pts.append((cx + math.cos(ang) * 18, cy + math.sin(ang) * 18))
            pygame.draw.lines(self.screen, (139, 69, 19), False, pts, 4)
            pygame.draw.line(self.screen, (200, 200, 200), (int(pts[0][0]), int(pts[0][1])), (int(pts[-1][0]), int(pts[-1][1])), 1)

    def _draw_buff_icon(self, key, r):
        cx, cy = r.centerx, r.centery
        if key == "apple":
            pygame.draw.circle(self.screen, (220, 40, 40), (int(cx), int(cy + 2)), 14)
            pygame.draw.circle(self.screen, (180, 20, 20), (int(cx), int(cy + 2)), 14, 2)
            pygame.draw.circle(self.screen, (255, 150, 150), (int(cx - 5), int(cy - 3)), 4)
            pygame.draw.line(self.screen, (90, 60, 30), (cx, cy - 12), (cx + 2, cy - 18), 3)
            pygame.draw.ellipse(self.screen, (60, 180, 60), (cx + 2, cy - 20, 10, 6))
        elif key == "lightning":
            pygame.draw.circle(self.screen, (255, 240, 130), (int(cx), int(cy)), 15)
            pygame.draw.polygon(self.screen, (255, 200, 0), [
                (cx + 3, cy - 12), (cx - 5, cy + 2), (cx, cy + 2),
                (cx - 3, cy + 12), (cx + 6, cy - 2), (cx + 1, cy - 2)])
        elif key == "minigun":
            pygame.draw.circle(self.screen, (200, 220, 255), (int(cx), int(cy)), 15)
            pygame.draw.rect(self.screen, (60, 60, 80), (cx - 10, cy - 3, 20, 6), border_radius=3)
            pygame.draw.rect(self.screen, (60, 60, 80), (cx + 5, cy - 6, 5, 12), border_radius=3)
        elif key == "firedoom":
            pygame.draw.circle(self.screen, (255, 180, 80), (int(cx), int(cy)), 15)
            pygame.draw.circle(self.screen, (255, 100, 20), (int(cx), int(cy)), 8)
            pygame.draw.circle(self.screen, (255, 240, 120), (int(cx), int(cy)), 3)
        elif key == "crazy":
            pygame.draw.circle(self.screen, (180, 60, 220), (int(cx), int(cy)), 15)
            pygame.draw.circle(self.screen, (100, 20, 130), (int(cx), int(cy)), 15, 2)
            for k in range(3):
                ang = k * (2 * math.pi / 3)
                pygame.draw.line(self.screen, (255, 240, 120), (cx, cy),
                                  (cx + math.cos(ang) * 10, cy + math.sin(ang) * 10), 3)
            pygame.draw.circle(self.screen, (255, 240, 120), (int(cx), int(cy)), 4)

    def _draw_build_icon(self, key, r):
        cx, cy = r.centerx, r.centery
        if key == BUILD_BARRICADE:
            pygame.draw.rect(self.screen, (130, 95, 55), (cx - 20, cy - 8, 40, 16), border_radius=2)
            pygame.draw.rect(self.screen, (40, 30, 20), (cx - 20, cy - 8, 40, 16), 2, border_radius=2)
            for dx in range(-15, 20, 10):
                pygame.draw.line(self.screen, (80, 55, 30), (cx + dx, cy - 8), (cx + dx, cy + 8), 2)
        elif key == BUILD_TURRET:
            pygame.draw.rect(self.screen, (140, 140, 150), (cx - 14, cy - 8, 28, 16), border_radius=3)
            pygame.draw.line(self.screen, (60, 60, 70), (cx, cy - 8), (cx + 14, cy - 16), 4)
            pygame.draw.circle(self.screen, (180, 200, 240), (cx + 14, cy - 16), 5)
        elif key == BUILD_FIRE_TURRET:
            pygame.draw.rect(self.screen, (150, 80, 40), (cx - 14, cy - 8, 28, 16), border_radius=3)
            pygame.draw.line(self.screen, (60, 60, 70), (cx, cy - 8), (cx + 14, cy - 16), 4)
            pygame.draw.circle(self.screen, (255, 140, 30), (cx + 14, cy - 16), 6)
        elif key == BUILD_REPAIR_TURRET:
            pygame.draw.rect(self.screen, (60, 140, 80), (cx - 14, cy - 8, 28, 16), border_radius=3)
            pygame.draw.line(self.screen, (60, 60, 70), (cx, cy - 8), (cx + 14, cy - 16), 4)
            pygame.draw.circle(self.screen, (120, 240, 120), (cx + 14, cy - 16), 6)
            pygame.draw.line(self.screen, (255, 255, 255), (cx + 10, cy - 16), (cx + 18, cy - 16), 2)
            pygame.draw.line(self.screen, (255, 255, 255), (cx + 14, cy - 20), (cx + 14, cy - 12), 2)
        elif key == BUILD_ELECTRIC_TURRET:
            pygame.draw.rect(self.screen, (60, 100, 180), (cx - 14, cy - 8, 28, 16), border_radius=3)
            pygame.draw.line(self.screen, (60, 60, 70), (cx, cy - 8), (cx + 14, cy - 16), 4)
            pygame.draw.circle(self.screen, (150, 220, 255), (cx + 14, cy - 16), 6)
            pygame.draw.line(self.screen, (255, 255, 100), (cx + 10, cy - 20), (cx + 14, cy - 16), 2)
            pygame.draw.line(self.screen, (255, 255, 100), (cx + 14, cy - 16), (cx + 18, cy - 12), 2)
        elif key == BUILD_HAMMER:
            # Молоток: рукоять + голова
            pygame.draw.line(self.screen, (110, 70, 40),
                             (cx - 12, cy + 14), (cx + 6, cy - 10), 6)
            pygame.draw.rect(self.screen, (160, 160, 170),
                             (cx + 2, cy - 18, 20, 12), border_radius=3)
            pygame.draw.rect(self.screen, (60, 60, 70),
                             (cx + 2, cy - 18, 20, 12), 2, border_radius=3)
        elif key == BUILD_DOOR:
            # Дверь: рама + светлая середина + ручка
            pygame.draw.rect(self.screen, (120, 80, 50),
                             (cx - 16, cy - 18, 32, 36), border_radius=3)
            pygame.draw.rect(self.screen, (60, 40, 20),
                             (cx - 16, cy - 18, 32, 36), 3, border_radius=3)
            pygame.draw.rect(self.screen, (200, 170, 120),
                             (cx - 10, cy - 12, 20, 24), border_radius=2)
            pygame.draw.circle(self.screen, (255, 220, 100),
                               (cx + 8, cy + 2), 3)

    def _build_server_settings_buttons(self):
        modes = [(MODE_NORMAL, "Обычный"), (MODE_BOSS_RUSH, "Босс-раш"), (MODE_PVP, "ПвП"), (MODE_CRYSTAL, "Защита кристалла")]
        bw, bh, gap = 200, 60, 20
        total = len(modes) * bw + (len(modes) - 1) * gap
        x0 = WIDTH // 2 - total // 2; y0 = HEIGHT // 2 - 130
        self.sv_mode_buttons = []
        for i, (mkey, mlabel) in enumerate(modes):
            self.sv_mode_buttons.append((mkey, Button(pygame.Rect(x0 + i*(bw+gap), y0, bw, bh), mlabel, (60,60,90))))
        diffs = [(DIFF_EASY, "Лёгкий"), (DIFF_NORMAL, "Обычный"), (DIFF_HARD, "Сложный"), (DIFF_ENDLESS, "Бесконечный")]
        y0 = HEIGHT // 2 - 20
        self.sv_diff_buttons = []
        for i, (dkey, dlabel) in enumerate(diffs):
            self.sv_diff_buttons.append((dkey, Button(pygame.Rect(x0 + i*(bw+gap), y0, bw, bh), dlabel, (60,60,90))))

    def _is_unlocked(self, key): return key in self.trophies.get("unlocks", [])
    def _has_achievement(self, key): return key in self.trophies.get("achievements", [])

    def _refresh_server_settings_buttons(self):
        for mkey, btn in self.sv_mode_buttons:
            if mkey == MODE_NORMAL: btn.active = (mkey == self.new_server_mode); btn.text = "Обычный"
            elif mkey == MODE_BOSS_RUSH:
                u = self._is_unlocked(UNLOCK_BOSSRUSH)
                btn.text = "Босс-раш" if u else "🔒 Босс-раш"
                btn.color = (60, 60, 90) if u else (50, 40, 40)
                btn.active = (mkey == self.new_server_mode)
            elif mkey == MODE_PVP:
                u = self._is_unlocked(UNLOCK_PVP)
                btn.text = "ПвП" if u else "🔒 ПвП"
                btn.color = (60, 60, 90) if u else (50, 40, 40)
                btn.active = (mkey == self.new_server_mode)
            elif mkey == MODE_CRYSTAL:
                u = self._is_unlocked(UNLOCK_CRYSTAL)
                btn.text = "Кристалл" if u else "🔒 Кристалл"
                btn.color = (60, 60, 90) if u else (50, 40, 40)
                btn.active = (mkey == self.new_server_mode)
        for dkey, btn in self.sv_diff_buttons:
            if dkey == DIFF_HARD and not self._is_unlocked(UNLOCK_HARD):
                btn.text = "🔒 Сложный"; btn.color = (50, 40, 40)
            elif dkey == DIFF_ENDLESS and not self._is_unlocked(UNLOCK_ENDLESS):
                btn.text = "🔒 Бесконечный"; btn.color = (50, 40, 40)
            else:
                _names = {DIFF_EASY: "Лёгкий", DIFF_NORMAL: "Обычный", DIFF_HARD: "Сложный", DIFF_ENDLESS: "Бесконечный"}
                btn.text = _names[dkey]; btn.color = (60, 60, 90)
            btn.active = (dkey == self.new_server_difficulty)
        self.btn_sv_cheats.text = "Читы: ВКЛ" if self.new_server_cheats else "Читы: ВЫКЛ"
        self.btn_sv_cheats.active = self.new_server_cheats
        try:
            _s = load_settings()
            _en = len(_s.get("enabled_mods", []))
            self.btn_sv_mods.text = f"МОДЫ ({_en})" if _en else "МОДЫ"
        except Exception:
            self.btn_sv_mods.text = "МОДЫ"

    def _apply_button_mode(self):
        w, h = 160, 44
        if self.button_mode == "center":
            y = HEIGHT // 2 - h // 2
            self.btn_shop_weapons.rect = pygame.Rect(WIDTH - w - 10, y, w, h)
            self.btn_auto.rect = pygame.Rect(WIDTH - 180, y + 60, 60, 60)
        else:
            self.btn_shop_weapons.rect = pygame.Rect(WIDTH - w - 10, 10, w, h)
            self.btn_auto.rect = pygame.Rect(WIDTH - 180, HEIGHT - 320, 60, 60)

    def _refresh_settings_buttons(self):
        self.btn_mode_default.active = (self.button_mode == "default")
        self.btn_mode_center.active = (self.button_mode == "center")
        self.btn_preview_toggle.text = ("Показать обводку баррикады: ВКЛ" if self.show_barricade_preview
                                          else "Показать обводку баррикады: ВЫКЛ")
        self.btn_preview_toggle.active = self.show_barricade_preview
        self.btn_input_toggle.text = ("Управление: ПК" if self.input_mode == "pc" else "Управление: Сенсор")
        self.btn_input_toggle.active = (self.input_mode == "pc")
        self.btn_pixelate.text = ("Пиксельность: ВКЛ" if self.pixelate else "Пиксельность: ВЫКЛ")
        self.btn_pixelate.active = self.pixelate

    def _save_keybinds(self):
        try:
            _s = load_settings()
            _s["keybinds"] = dict(self.keybinds)
            save_settings(_s)
        except Exception: pass

    def _kb_click_at(self, pos):
        """Определяет, по какой строке раскладки кликнули."""
        list_x = WIDTH // 2 - 400
        list_w = 800
        row_h = 60
        y0 = 200 - int(self.kb_scroll)
        for i, key in enumerate(KEYBIND_ORDER):
            y = y0 + i * row_h
            r = pygame.Rect(list_x, y, list_w, row_h - 6)
            if r.collidepoint(pos):
                self.kb_active_row = i
                return

    def goto_servers(self):
        self.state = "servers"; self.servers = []; self.last_disc = 0
        self.status = "Поиск серверов в локальной сети..."

    def goto_server_settings(self, solo=False):
        self.state = "server_settings"; self.solo_mode = solo
        self.new_server_mode = MODE_NORMAL; self.new_server_difficulty = DIFF_NORMAL
        self.new_server_cheats = False; self._refresh_server_settings_buttons()

    def _my_stage(self): return int(self.trophies.get("stage", 0))
    def _my_wins(self): return int(self.trophies.get("wins", 0))

    def start_server(self):
        if self.host is not None: return
        try:
            self.host = Host(port=DEFAULT_PORT, name="Zombie Server", mode=self.new_server_mode,
                             difficulty=self.new_server_difficulty, cheats=self.new_server_cheats,
                             stage=self._my_stage(), host_achievements=self.trophies.get("achievements", []),
                             host_wins=self._my_wins())
        except OSError as e:
            self.status = f"Не удалось: {e}"; return
        self.client = None
        self.my_id = self.host.local_cid
        self.is_admin = True
        self.state = "game"
        self._reset_game_state()
        self.host.start_console()
        print(f"=== Код сервера: {self.host.server_code} ===")
        self.status = f"Код: {self.host.server_code}"
        self.host._app_ref = self

    def start_solo(self):
        if self.host is not None: return
        _snap = load_solo_save()
        try:
            self.host = Host(port=DEFAULT_PORT, name="__solo__", mode=self.new_server_mode,
                             difficulty=self.new_server_difficulty, cheats=self.new_server_cheats,
                             stage=self._my_stage(), host_achievements=self.trophies.get("achievements", []),
                             host_wins=self._my_wins(), solo=True,
                             save_snapshot=_snap)
        except OSError as e:
            self.status = f"Не удалось: {e}"; return
        self.client = None
        self.my_id = self.host.local_cid
        self.is_admin = True
        self.state = "game"
        self._reset_game_state()
        self.host.start_console()
        self.status = "Соло"
        self.host._app_ref = self

    def _reset_game_state(self):
        self.players = {}; self.bullets = []
        self.zombies = []; self.meteors = []; self.popups = []
        self.buildings = []; self.building_cells = []
        self.turret_bullets = []; self.crates = []; self.lasers = []
        self.spitter_bullets = []; self.puddles = []
        self.forbidden_items = []; self.forbidden_count_local = 0
        self.camera = [0.0, 0.0]; self.local_init = False
        self.server_full_msg = ""; self.chat_kb.close_kb()
        self.victory = False; self.cheated_this_session = False
        self.no_stats_this_session = False
        self.barricade_mode = False; self.shop_open = None
        self.slot_picker = None; self.crate_popup = None
        self.unlock_popup = None; self.achievement_popup = None
        self.drop_menu_open = False
        self.prism_shards_local = 0
        self.stardust_local = 0
        self.true_star_unlocked = False
        self.last_prism_unlocked = False
        self.choosing_weapon = True
        self.wave_button_active = False

    def _connect(self, host, port, console_enabled=True):
        try:
            self.client = Client(
                host, port, on_welcome=self._on_welcome, console_enabled=console_enabled,
                on_cheat=self._on_cheat_detected, my_stage=self._my_stage(),
                my_wins=self._my_wins(),
                my_unlocks=self.trophies.get("unlocks", []),
                my_achievements=self.trophies.get("achievements", []),
            )
            self.state = "game"
            self.host = None
            self._reset_game_state()
        except Exception as e:
            self.status = f"Ошибка подключения: {e}"

    def _on_welcome(self, msg):
        self.my_id = msg["id"]; self.is_admin = bool(msg.get("is_admin", False))
        _welcome_mods = list(msg.get("mods", []))
        if _welcome_mods and self.mods_warning is None and not getattr(self, "_mods_ack_sent", False):
            self.mods_warning = {"mods": _welcome_mods, "status": ""}
        m = msg.get("map")
        if m: self.map_w, self.map_h = m
        if msg.get("cheats", False): self.cheated_this_session = True
        self.max_wave_current = int(msg.get("max_wave", 100))
        self.server_wins = int(msg.get("wins", 0))
        self.no_stats_this_session = bool(msg.get("no_stats", False))

    def _on_cheat_detected(self):
        if not self.cheated_this_session:
            self.cheated_this_session = True
            self.info_msg = "Команды и читы отключают статистику в этой сессии"
            self.info_msg_until = time.time() + 5.0

    def leave(self):
        try: pygame.mixer.music.stop()
        except Exception: pass
        self.music_menu_started = False
        self.music_game_started = False
        if self.client: self.client.close(); self.client = None
        if self.host: self.host.stop(); self.host = None
        self.my_id = None; self.is_admin = False; self.local_init = False
        self.btn_auto.toggle = False; self.shop_open = None
        self.chat_kb.close_kb(); self.victory = False
        self.barricade_mode = False; self.slot_picker = None
        self.crate_popup = None; self.lasers = []; self.forbidden_items = []
        self.unlock_popup = None; self.achievement_popup = None
        self.solo_mode = False; self.drop_menu_open = False
        self.prism_shards_local = 0
        self.stardust_local = 0
        self.true_star_unlocked = False
        self.last_prism_unlocked = False
        self.choosing_weapon = False
        self.state = "menu"

    def _force_lobby(self, reason):
        self.info_msg = reason; self.info_msg_until = time.time() + 5.0; self.leave()

    def _mark_stage_complete(self):
        if self.cheated_this_session or getattr(self, 'no_stats_this_session', False):
            return
        cur = int(self.trophies.get("stage", 0))
        unlocks = set(self.trophies.get("unlocks", []))
        new_items = []
        if cur == 0: self.trophies["stage"] = 1; new_items.append(("Этап 50 волн", True))
        elif cur == 1:
            self.trophies["stage"] = 2; new_items.append(("Этап 100 волн", True))
            for k in (UNLOCK_BOSSRUSH, UNLOCK_PVP, UNLOCK_HARD, UNLOCK_STAGE100):
                if k not in unlocks: unlocks.add(k); new_items.append((UNLOCK_NAMES[k], True))
        self.trophies["unlocks"] = list(unlocks)
        if new_items: self.unlock_popup = {"items": new_items}

    def _grant_achievement_local(self, key):
        if self.cheated_this_session: return
        ach = set(self.trophies.get("achievements", []))
        if key in ach: return
        ach.add(key); self.trophies["achievements"] = list(ach)
        if key == ACH_HORRORS_OF_PAST:
            unlocks = set(self.trophies.get("unlocks", []))
            unlocks.add(UNLOCK_FORBIDDEN); self.trophies["unlocks"] = list(unlocks)
        save_gamestate(self.trophies); self.achievement_popup = key

    # ============================================================
    #  ОБРАБОТКА СОБЫТИЙ
    # ============================================================
    def events(self):
        for e in pygame.event.get():
            # Мышь — только в режиме ПК
            if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                if self.input_mode != "pc":
                    continue
            # Тач — только в режиме Сенсор
            if e.type in (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION):
                if self.input_mode != "touch":
                    continue
            # === модовский перехват событий (после фильтра по input_mode) ===
            try:
                _ev = MOD_API.call("on_event", self, e)
                if _ev and any(_ev):
                    continue
            except Exception as _e:
                print("[mods] on_event error:", _e)
            if e.type == pygame.QUIT:
                self.leave(); pygame.quit(); raise SystemExit
            # ПК: мышь зажата
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.mouse_held = True
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                self.mouse_held = False
                # === ЛУК: выстрел при отпускании мыши ===
                me = self.players.get(self.my_id)
                if me and me.get("weapon") == "bow" and me.get("charge_start", 0) > 0:
                    self._fire_charged_shot(me, time.time())
            # ПК: клавиши WASD
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_w: self.keys_held.add("w")
                elif e.key == pygame.K_a: self.keys_held.add("a")
                elif e.key == pygame.K_s: self.keys_held.add("s")
                elif e.key == pygame.K_d: self.keys_held.add("d")
            elif e.type == pygame.KEYUP:
                if e.key == pygame.K_w: self.keys_held.discard("w")
                elif e.key == pygame.K_a: self.keys_held.discard("a")
                elif e.key == pygame.K_s: self.keys_held.discard("s")
                elif e.key == pygame.K_d: self.keys_held.discard("d")
            # === Экран настройки раскладки ===
            if self.state == "keybinds":
                # Клик по кнопкам
                if self.btn_keybinds_back.clicked(e) or self.btn_keybinds_back.clicked_touch(e):
                    self.kb_active_row = None
                    self.state = "settings"
                    self._save_keybinds()
                    continue
                if self.btn_keybinds_reset.clicked(e) or self.btn_keybinds_reset.clicked_touch(e):
                    self.keybinds = dict(DEFAULT_KEYBINDS)
                    self.kb_active_row = None
                    self._save_keybinds()
                    continue
                # Нажатие клавиши — назначить/отменить
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        self.kb_active_row = None
                        continue
                    if self.kb_active_row is not None:
                        key_name = pygame.key.name(e.key)
                        self.keybinds[KEYBIND_ORDER[self.kb_active_row]] = key_name
                        self.kb_active_row = None
                        self._save_keybinds()
                        continue
                # Плавный скролл под пальцем
                if e.type == pygame.FINGERDOWN:
                    self._kb_drag_start = (e.x * WIDTH, e.y * HEIGHT)
                    self._kb_drag_last_y = e.y * HEIGHT
                    self._kb_drag_dy = 0
                elif e.type == pygame.FINGERMOTION and self._kb_drag_start:
                    cur_y = e.y * HEIGHT
                    self.kb_scroll -= (cur_y - self._kb_drag_last_y)
                    self._kb_drag_last_y = cur_y
                elif e.type == pygame.FINGERUP and self._kb_drag_start:
                    self._kb_drag_start = None
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self._kb_drag_start = e.pos
                    self._kb_drag_last_y = e.pos[1]
                    self._kb_drag_dy = 0
                    self._kb_click_at(e.pos)
                elif e.type == pygame.MOUSEMOTION and self._kb_drag_start and e.buttons[0]:
                    cur_y = e.pos[1]
                    self.kb_scroll -= (cur_y - self._kb_drag_last_y)
                    self._kb_drag_last_y = cur_y
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                    self._kb_drag_start = None
                # Ограничение скролла
                max_scroll = max(0, len(KEYBIND_ORDER) * 60 - (HEIGHT - 300))
                self.kb_scroll = max(0, min(max_scroll, self.kb_scroll))
                continue
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                if self.chat_kb.open: self.chat_kb.close_kb(); continue
                if self.state == "choose_input": continue
                if self.state == "settings": self.state = "menu"
                elif self.state == "stats": self.state = "menu"
                elif self.state == "servers": self.state = "menu"
                elif self.state == "mods": self.state = "server_settings"
                elif self.state == "server_settings": self.state = "servers"
                elif self.state == "game":
                    if self.choosing_weapon: self.leave()
                    elif self.achievement_popup: self.achievement_popup = None
                    elif self.unlock_popup: self.unlock_popup = None
                    elif self.drop_menu_open: self.drop_menu_open = False
                    elif self.slot_picker is not None: self.slot_picker = None
                    elif self.crate_popup: self.crate_popup = None
                    elif self.barricade_mode: self.barricade_mode = False
                    elif self.shop_open: self.shop_open = None
                    else: self.leave()
            if self.state == "choose_input":
                if self.btn_choose_pc.clicked(e) or self.btn_choose_pc.clicked_touch(e):
                    self.input_mode = "pc"
                    self.trophies["input_mode"] = "pc"
                    self.trophies["not_first"] = True
                    save_gamestate(self.trophies)
                    try: pygame.mouse.set_visible(False)
                    except Exception: pass
                    self._refresh_settings_buttons()
                    self.state = "menu"
                if self.btn_choose_touch.clicked(e) or self.btn_choose_touch.clicked_touch(e):
                    self.input_mode = "touch"
                    self.trophies["input_mode"] = "touch"
                    self.trophies["not_first"] = True
                    save_gamestate(self.trophies)
                    try: pygame.mouse.set_visible(True)
                    except Exception: pass
                    self._refresh_settings_buttons()
                    self.state = "menu"
            elif self.state == "menu":
                if self.btn_play.clicked(e) or self.btn_play.clicked_touch(e): self.goto_servers()
                if self.btn_solo.clicked(e) or self.btn_solo.clicked_touch(e): self.goto_server_settings(solo=True)
                if self.btn_settings.clicked(e) or self.btn_settings.clicked_touch(e): self.state = "settings"
                if self.btn_stats.clicked(e) or self.btn_stats.clicked_touch(e): self.state = "stats"
            elif self.state == "stats":
                if self.btn_stats_back.clicked(e) or self.btn_stats_back.clicked_touch(e): self.state = "menu"
            elif self.state == "settings":
                if self.btn_mode_default.clicked(e) or self.btn_mode_default.clicked_touch(e):
                    self.button_mode = "default"; self._apply_button_mode(); self._refresh_settings_buttons()
                    _s = load_settings(); _s["button_mode"] = self.button_mode; save_settings(_s)
                elif self.btn_mode_center.clicked(e) or self.btn_mode_center.clicked_touch(e):
                    self.button_mode = "center"; self._apply_button_mode(); self._refresh_settings_buttons()
                    _s = load_settings(); _s["button_mode"] = self.button_mode; save_settings(_s)
                if self.btn_preview_toggle.clicked(e) or self.btn_preview_toggle.clicked_touch(e):
                    self.show_barricade_preview = not self.show_barricade_preview
                    self._refresh_settings_buttons()
                    _s = load_settings(); _s["show_barricade_preview"] = self.show_barricade_preview; save_settings(_s)
                if self.btn_input_toggle.clicked(e) or self.btn_input_toggle.clicked_touch(e):
                    self.input_mode = "pc" if self.input_mode == "touch" else "touch"
                    self.trophies["input_mode"] = self.input_mode
                    save_gamestate(self.trophies)
                    try: pygame.mouse.set_visible(self.input_mode != "pc")
                    except Exception: pass
                    self._refresh_settings_buttons()
                if self.btn_pixelate.clicked(e) or self.btn_pixelate.clicked_touch(e):
                    self.pixelate = not self.pixelate
                    self._refresh_settings_buttons()
                    _s = load_settings(); _s["pixelate"] = self.pixelate; save_settings(_s)
                if self.btn_keybinds.clicked(e) or self.btn_keybinds.clicked_touch(e):
                    self.state = "keybinds"
                    self.kb_active_row = None
                    self.kb_scroll = 0.0
                    continue
                if self.btn_settings_back.clicked(e) or self.btn_settings_back.clicked_touch(e): self.state = "menu"
            elif self.state == "servers":
                if self.btn_plus.clicked(e) or self.btn_plus.clicked_touch(e): self.goto_server_settings(solo=False)
                if self.btn_back.clicked(e) or self.btn_back.clicked_touch(e): self.state = "menu"
                _fb = getattr(self, "_btn_force_connect", None)
                if _fb is not None and (
                    (e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and _fb.collidepoint(e.pos))
                    or (e.type == pygame.FINGERDOWN and _fb.collidepoint((e.x * WIDTH, e.y * HEIGHT)))
                ):
                    self._force_connect()
                    continue
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    for i, s in enumerate(self.servers):
                        r = pygame.Rect(80, 120 + i * 60, WIDTH - 160, 50)
                        if r.collidepoint(e.pos): self._connect(s[0], s[1]); break
                elif e.type == pygame.FINGERDOWN:
                    fx, fy = e.x * WIDTH, e.y * HEIGHT
                    for i, s in enumerate(self.servers):
                        r = pygame.Rect(80, 120 + i * 60, WIDTH - 160, 50)
                        if r.collidepoint((fx, fy)): self._connect(s[0], s[1]); break
            elif self.state == "mods":
                self._handle_mods_click(e)
            elif self.state == "server_settings":
                if self.btn_sv_back.clicked(e) or self.btn_sv_back.clicked_touch(e):
                    self.state = "menu" if self.solo_mode else "servers"
                if self.btn_sv_start.clicked(e) or self.btn_sv_start.clicked_touch(e):
                    if self.solo_mode: self.start_solo()
                    else: self.start_server()
                for mkey, btn in self.sv_mode_buttons:
                    if btn.clicked(e) or btn.clicked_touch(e):
                        if mkey == MODE_NORMAL:
                            self.new_server_mode = mkey; self._refresh_server_settings_buttons()
                        elif mkey == MODE_BOSS_RUSH and self._is_unlocked(UNLOCK_BOSSRUSH):
                            self.new_server_mode = mkey; self._refresh_server_settings_buttons()
                        elif mkey == MODE_PVP and self._is_unlocked(UNLOCK_PVP):
                            self.new_server_mode = mkey; self._refresh_server_settings_buttons()
                        elif mkey == MODE_CRYSTAL and self._is_unlocked(UNLOCK_CRYSTAL):
                            self.new_server_mode = mkey; self._refresh_server_settings_buttons()
                for dkey, btn in self.sv_diff_buttons:
                    if btn.clicked(e) or btn.clicked_touch(e):
                        if dkey == DIFF_HARD and not self._is_unlocked(UNLOCK_HARD): continue
                        if dkey == DIFF_ENDLESS and not self._is_unlocked(UNLOCK_ENDLESS): continue
                        self.new_server_difficulty = dkey; self._refresh_server_settings_buttons()
                if self.btn_sv_cheats.clicked(e) or self.btn_sv_cheats.clicked_touch(e):
                    self.new_server_cheats = not self.new_server_cheats; self._refresh_server_settings_buttons()
                if self.btn_sv_mods.clicked(e) or self.btn_sv_mods.clicked_touch(e):
                    self.state = "mods"
                    self._mods_checkboxes = []
            elif self.state == "game":
                if self.mods_warning is not None:
                    if self.mods_warning_btn.clicked(e) or self.mods_warning_btn.clicked_touch(e):
                        self._start_mods_download()
                    elif self.mods_warning_close.clicked(e) or self.mods_warning_close.clicked_touch(e):
                        self.mods_warning = None
                        self._force_lobby("Загрузка модов отменена")
                    continue
                if self.mods_warning is not None:
                    if self.mods_warning_btn.clicked(e) or self.mods_warning_btn.clicked_touch(e):
                        self._start_mods_download()
                    elif self.mods_warning_close.clicked(e) or self.mods_warning_close.clicked_touch(e):
                        self.mods_warning = None
                        self._force_lobby("Загрузка модов отменена")
                    continue
                if self.choosing_weapon:
                    self._handle_choose_weapon_event(e)
                    continue
                if self.achievement_popup is not None:
                    if self.achievement_popup_close.clicked(e) or self.achievement_popup_close.clicked_touch(e):
                        self.achievement_popup = None
                    continue
                if self.unlock_popup is not None:
                    if self.unlock_popup_close.clicked(e) or self.unlock_popup_close.clicked_touch(e):
                        self.unlock_popup = None
                    continue
                if self.weapon_desc_popup is not None:
                    pos = None
                    if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                        pos = e.pos
                    elif e.type == pygame.FINGERDOWN:
                        pos = (e.x * WIDTH, e.y * HEIGHT)
                    if pos is not None:
                        # клик по фону (вне панели) или по крестику — закрыть
                        panel = pygame.Rect(WIDTH // 2 - 400, HEIGHT // 2 - 220, 800, 440)
                        close_btn = pygame.Rect(panel.right - 60, panel.top + 16, 44, 44)
                        if not panel.collidepoint(pos) or close_btn.collidepoint(pos):
                            self.weapon_desc_popup = None
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                        self.weapon_desc_popup = None
                    continue
                if self.chat_kb.open:
                    txt = self.chat_kb.handle(e)
                    if txt is not None and (self.client or self.host):
                        self._send_to_server({"type": "console", "line": txt})
                    continue
                # === Клавиши ПК-режима (только при input_mode == "pc") ===
                if self.input_mode == "pc" and e.type == pygame.KEYDOWN:
                    if self._handle_pc_key(e): continue
                self._handle_game_event(e)

    def _handle_pc_key(self, e):
        """Обрабатывает нажатие клавиши в ПК-режиме. Возвращает True, если клавиша поглощена."""
        name = pygame.key.name(e.key)
        # Магазин
        if self.keybinds.get("shop") == name:
            if self.shop_open:
                self.shop_open = None
            else:
                self.shop_open = "weapons"; self.shop_tab = "weapons"
                self.shop_page_weapons = 0
            return True
        # Строй. слот
        if self.keybinds.get("build") == name:
            me = self.players.get(self.my_id)
            if me and me.get("build_slot"):
                self.barricade_mode = not self.barricade_mode
            return True
        # Слоты оружия 1-5
        for i in range(5):
            if self.keybinds.get(f"slot{i+1}") == name:
                self._on_hotbar_slot(i)
                return True
        # Яблоко
        if self.keybinds.get("apple") == name:
            self._send_to_server({"type": "use_item", "key": "apple"})
            return True
        # Ускорение
        if self.keybinds.get("lightning") == name:
            self._send_to_server({"type": "use_item", "key": "lightning"})
            return True
        # Миниган
        if self.keybinds.get("minigun") == name:
            self._send_to_server({"type": "use_item", "key": "minigun"})
            return True
        # Огненное дуло
        if self.keybinds.get("firedoom") == name:
            self._send_to_server({"type": "use_item", "key": "firedoom"})
            return True
        # Сумасшествие
        if self.keybinds.get("crazy") == name:
            self._send_to_server({"type": "use_item", "key": "crazy"})
            return True
        # Выбросить
        if self.keybinds.get("drop") == name:
            self.drop_menu_open = True
            return True
        return False

    def _send_to_server(self, msg):
        if self.host is not None:
            self.host.local_send(msg)
        elif self.client is not None:
            self.client.send(msg)

    def _handle_choose_weapon_event(self, e):
        pos = None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.input_mode != "pc": return
            pos = e.pos
        elif e.type == pygame.FINGERDOWN:
            if self.input_mode != "touch": return
            pos = (e.x * WIDTH, e.y * HEIGHT)
        if pos is None: return
        for key, rect in (("base", self.choose_btn_base), ("rifle", self.choose_btn_rifle),
                          ("shotgun", self.choose_btn_shotgun)):
            if rect and rect.collidepoint(pos):
                self._send_to_server({"type": "choose_start_weapon", "key": key})
                self.choosing_weapon = False
                return
        # (после send_to_server)



    def _handle_game_event(self, e):
        # Определяем pos
        pos = None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.input_mode != "pc": return
            pos = e.pos
        elif e.type == pygame.FINGERDOWN:
            if self.input_mode != "touch": return
            pos = (e.x * WIDTH, e.y * HEIGHT)
        # Для не-тап событий (motion/keyboard) — не обрабатываем здесь
        if self.drop_menu_open:
            if pos is not None:
                panel = pygame.Rect(WIDTH//2 - 500, HEIGHT//2 - 250, 1000, 500)
                close_rect = pygame.Rect(WIDTH//2 - 100, panel.bottom - 70, 200, 50)
                if close_rect.collidepoint(pos):
                    self.drop_menu_open = False; return
                if not panel.collidepoint(pos):
                    self.drop_menu_open = False; return
                me = self.players.get(self.my_id)
                if not me: return
                weapons = [w for w in me.get("owned_weapons", []) if w != "base"]
                for i, wkey in enumerate(weapons):
                    col = i % 5; row = i // 5
                    r = pygame.Rect(panel.x + 30 + col * 90, panel.y + 60 + row * 90, 80, 80)
                    if r.collidepoint(pos):
                        self._send_to_server({"type": "drop_weapon", "key": wkey}); return
                buffs = list(SHOP_BUFFS.keys())
                for i, bkey in enumerate(buffs):
                    r = pygame.Rect(panel.x + 540, panel.y + 60 + i * 70, 440, 60)
                    if r.collidepoint(pos):
                        self._send_to_server({"type": "drop_buff", "key": bkey}); return
            return
        if self.slot_picker is not None:
            if pos is not None:
                wkey = self.slot_picker
                close_rect = pygame.Rect(WIDTH // 2 - 100, HEIGHT // 2 + 140, 200, 50)
                if close_rect.collidepoint(pos):
                    self.slot_picker = None; return
                for i in range(MAX_WEAPON_SLOTS):
                    r = pygame.Rect(WIDTH // 2 - 250 + i * 100, HEIGHT // 2 - 50, 90, 100)
                    if r.collidepoint(pos):
                        self._send_to_server({"type": "assign_slot", "key": wkey, "slot": i})
                        self.slot_picker = None; return
            return
        if self.crate_popup is not None:
            if pos is not None: self.crate_popup = None
            return
        if self.shop_open: self._handle_shop_click(e); return
        if self.btn_chat_open.clicked(e) or self.btn_chat_open.clicked_touch(e):
            self.chat_kb.open_kb(); return
        if self.btn_auto.clicked(e) or self.btn_auto.clicked_touch(e):
            self.btn_auto.toggle = not self.btn_auto.toggle; return
        if self.btn_shop_weapons.clicked(e) or self.btn_shop_weapons.clicked_touch(e):
            self.shop_open = "weapons"
            if not hasattr(self, "shop_tab"): self.shop_tab = "weapons"
            self.shop_page_weapons = 0
            return
        if pos is not None:
            for i, r in enumerate(self.hotbar_rects):
                if r.collidepoint(pos): self._on_hotbar_slot(i); return
        # Джойстики — только в тач-режиме
        if self.input_mode == "touch":
            moved = self.move_joy.handle(e) or self.aim_joy.handle(e)
            if moved: return
        if self.barricade_mode:
            me = self.players.get(self.my_id)
            if me and not me.get("dead"):
                if pos is not None:
                    self._try_place_build(pos); return

        # молот/ключ — тап по карте применяет к своей постройке
        me_ = self.players.get(self.my_id)
        if me_ is not None and pos is not None:
            _w = me_.get("weapon", "base")
            _ws = WEAPON_STATS.get(_w, {})
            if _ws.get("hammer") or _ws.get("wrench"):
                _cx, _cy = self.camera
                _gx = int((pos[0] + _cx) // BARRICADE_GRID)
                _gy = int((pos[1] + _cy) // BARRICADE_GRID)
                if self.local_init:
                    _mgx = int(self.local_x // BARRICADE_GRID)
                    _mgy = int(self.local_y // BARRICADE_GRID)
                    if abs(_gx - _mgx) > BARRICADE_RANGE or abs(_gy - _mgy) > BARRICADE_RANGE:
                        self.info_msg = "Слишком далеко"
                        self.info_msg_until = time.time() + 1.2
                        return
                self._send_to_server({"type": "tool_use", "gx": _gx, "gy": _gy})
                return

    def _try_place_build(self, screen_pos):
        me = self.players.get(self.my_id)
        if not me: return
        key = me.get("build_slot")
        if not key or me.get("build_inventory", {}).get(key, 0) <= 0:
            self.barricade_mode = False; return
        self.barricade_hover = screen_pos
        cx, cy = self.camera
        gx = int((screen_pos[0] + cx) // BARRICADE_GRID); gy = int((screen_pos[1] + cy) // BARRICADE_GRID)
        if self.local_init:
            mgx = int(self.local_x // BARRICADE_GRID); mgy = int(self.local_y // BARRICADE_GRID)
            if abs(gx - mgx) > BARRICADE_RANGE or abs(gy - mgy) > BARRICADE_RANGE:
                self.info_msg = "Слишком далеко"; self.info_msg_until = time.time() + 1.2; return
        self._send_to_server({"type": "place_build", "gx": gx, "gy": gy})

    def _on_hotbar_slot(self, idx):
        me = self.players.get(self.my_id)
        if not me: return
        if idx < 0 or idx >= len(self.hotbar_keys): return
        key = self.hotbar_keys[idx]
        is_item = self.hotbar_is_item[idx]
        if key == "__drop__":
            self.drop_menu_open = True
            return
        if key == "__build__":
            if me.get("build_slot"): self.barricade_mode = not self.barricade_mode
            return
        if is_item:
            if key == "forbidden": self._send_to_server({"type": "use_forbidden"})
            elif key in SHOP_BUFFS:
                self._send_to_server({"type": "use_item", "key": key})
        else:
            slots = me.get("weapon_slots", [])
            if key in slots:
                # если уже выбрано — открыть пикер слотов (переназначить)
                if me.get("weapon") == key:
                    self.slot_picker = key
                else:
                    self._send_to_server({"type": "select_weapon", "key": key})

    SHOP_CELL_W = 700
    SHOP_CELL_H = 90
    SHOP_GAP    = 12
    SHOP_TOP_Y  = 200

    def _shop_cells(self, items):
        """Возвращает список (key, info, rect) — все items одним столбцом."""
        cw = min(WIDTH - 200, self.SHOP_CELL_W)
        x0 = WIDTH // 2 - cw // 2
        y0 = self.SHOP_TOP_Y - int(self._shop_scroll_cur)
        cells = []
        for idx, (key, info) in enumerate(items):
            y = y0 + idx * (self.SHOP_CELL_H + self.SHOP_GAP)
            r = pygame.Rect(x0, y, cw, self.SHOP_CELL_H)
            cells.append((key, info, r))
        return cells

    def _arsenal_visible(self):
        """Возвращает список (key, info) для отображения в магазине оружия.
        Скрывает last_prism и true_star, если они ещё не открыты.
        Сортирует по цене: от самых дешёвых к самым дорогим."""
        items = []
        for key, info in ARSENAL.items():
            if key == "last_prism" and not self.last_prism_unlocked: continue
            if key == "true_star" and not self.true_star_unlocked: continue
            items.append((key, info))
        items.sort(key=lambda kv: (kv[1].get("price", 0), kv[1].get("label", "")))
        return items

    def _shop_arsenal_cells(self, page=0):
        items = self._arsenal_visible()
        return self._shop_cells(items), len(items)

    def _shop_buff_cells(self, page=0):
        items = list(SHOP_BUFFS.items())
        return self._shop_cells(items), len(items)

    def _shop_build_cells(self, page=0):
        items = [(k, {"label": v}) for k, v in BUILD_LABELS.items()]
        return self._shop_cells(items), len(items)

    def _shop_passive_cells(self, page=0):
        items = list(PASSIVES.items())
        return self._shop_cells(items), len(items)

    def _handle_shop_click(self, e):
        """Скролл магазина: drag = скролл, тап = клик.
        Работает и в touch, и в pc input_mode."""
        # -------- Тач --------
        if e.type == pygame.FINGERDOWN:
            self._shop_drag_start_y = e.y * HEIGHT
            self._shop_drag_last_y = self._shop_drag_start_y
            self._shop_drag_moved = False
            return
        elif e.type == pygame.FINGERMOTION:
            if not hasattr(self, "_shop_drag_last_y"): return
            cur_y = e.y * HEIGHT
            dy = cur_y - self._shop_drag_last_y
            self._shop_drag_last_y = cur_y
            if abs(cur_y - self._shop_drag_start_y) > 6:
                self._shop_drag_moved = True
            self._shop_scroll_target -= dy * 1.4
            return
        elif e.type == pygame.FINGERUP:
            if not hasattr(self, "_shop_drag_last_y"): return
            if not getattr(self, "_shop_drag_moved", False):
                pos = (e.x * WIDTH, e.y * HEIGHT)
                self._shop_click_at(pos)
            del self._shop_drag_last_y
            if hasattr(self, "_shop_drag_start_y"): del self._shop_drag_start_y
            return
        # -------- Мышь --------
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self._shop_drag_start_y = e.pos[1]
            self._shop_drag_last_y = e.pos[1]
            self._shop_drag_moved = False
            return
        elif e.type == pygame.MOUSEMOTION and hasattr(self, "_shop_drag_last_y") and e.buttons[0]:
            cur_y = e.pos[1]
            dy = cur_y - self._shop_drag_last_y
            self._shop_drag_last_y = cur_y
            if abs(cur_y - self._shop_drag_start_y) > 6:
                self._shop_drag_moved = True
            self._shop_scroll_target -= dy * 1.4
            return
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if not hasattr(self, "_shop_drag_last_y"): return
            if not getattr(self, "_shop_drag_moved", False):
                self._shop_click_at(e.pos)
            del self._shop_drag_last_y
            if hasattr(self, "_shop_drag_start_y"): del self._shop_drag_start_y
            return

    def _shop_click_at(self, pos):
        close_rect = pygame.Rect(WIDTH // 2 - 60, HEIGHT - 70, 120, 50)
        if close_rect.collidepoint(pos):
            self.shop_open = None
            return
        # Вкладки
        if not hasattr(self, "shop_tab") or self.shop_tab is None:
            self.shop_tab = "weapons"
        tabs = [("weapons",), ("buffs",), ("build",), ("passives",)]
        tw = 200; th = 44; tgap = 12
        total = len(tabs) * tw + (len(tabs) - 1) * tgap
        tx0 = WIDTH // 2 - total // 2; ty = 130
        for i, (key,) in enumerate(tabs):
            r = pygame.Rect(tx0 + i * (tw + tgap), ty, tw, th)
            if r.collidepoint(pos):
                if self.shop_tab != key:
                    self.shop_tab = key
                    self._shop_scroll_target = 0.0
                    self._shop_scroll_cur = 0.0
                return
        # Контент по вкладке — используем новые ячейки (со сдвигом)
        if self.shop_tab == "weapons":
            cells, total = self._shop_arsenal_cells()
            me = self.players.get(self.my_id)
            for key, info, r in cells:
                sb = pygame.Rect(r.right - 110, r.bottom - 34, 96, 26)
                qb = pygame.Rect(r.right - 40, r.top + 8, 30, 30)
                owned = bool(me) and key in me.get("owned_weapons", [])
                if qb.collidepoint(pos):
                    self.weapon_desc_popup = key
                    return
                if owned and sb.collidepoint(pos):
                    self.slot_picker = key
                    return
                if r.collidepoint(pos):
                    self._send_to_server({"type": "buy_weapon", "key": key})
                    return
        elif self.shop_tab == "buffs":
            cells, total = self._shop_buff_cells()
            for key, info, r in cells:
                if r.collidepoint(pos):
                    self._send_to_server({"type": "buy_buff", "key": key})
                    return
        elif self.shop_tab == "build":
            cells, total = self._shop_build_cells()
            me = self.players.get(self.my_id)
            for key, info, r in cells:
                slot_btn = pygame.Rect(r.right - 110, r.bottom - 34, 96, 26)
                if slot_btn.collidepoint(pos):
                    self._send_to_server({"type": "select_build", "key": key})
                    return
                if r.collidepoint(pos):
                    self._send_to_server({"type": "buy_build", "key": key})
                    return
        elif self.shop_tab == "passives":
            cells, total = self._shop_passive_cells()
            me = self.players.get(self.my_id)
            for key, info, r in cells:
                sb = pygame.Rect(r.right - 110, r.bottom - 34, 96, 26)
                owned = bool(me) and key in me.get("passive_owned", [])
                if owned and sb.collidepoint(pos):
                    self._send_to_server({"type": "select_passive", "key": key})
                    return
                if r.collidepoint(pos):
                    self._send_to_server({"type": "buy_passive", "key": key})
                    return

    def _apply_state_from_host(self):
        h = self.host
        with h.lock:
            self.players = {p["id"]: p for p in h.players.values()}
            self.bullets = list(h.bullets)
            self.zombies = list(h.zombies)
            self.spitter_bullets = list(h.spitter_bullets)
            self.final_boss_bullets = list(h.final_boss_bullets)
            self.puddles = list(h.puddles)
            self.buildings = list(h.buildings)
            self.building_cells = list(h.building_cells)
            self.turret_bullets = list(h.turret_bullets)
            self.electric_turret_bullets = list(h.electric_turret_bullets)
            self.crates = list(h.crates)
            self.meteors = list(h.meteors)
            self.popups = list(h.damage_popups)
            self.forbidden_items = list(h.forbidden_items)
            self.wave = h.wave
            self.wave_state = h.wave_state
            self.wave_total = h.wave_total
            self.wave_killed = h.wave_killed
            self.wave_break_until = h.wave_break_until
            self.victory = h.victory
            self.max_wave_current = h.max_wave
            self.wave_button_active = h.wave_button_active
            self.wave_button_x = h.wave_button_x
            self.wave_button_y = h.wave_button_y
            self.server_time_offset = 0.0
        me = self.players.get(self.my_id)
        if me and me.get("choosing_weapon"):
            self.choosing_weapon = True
            self.local_init = False
        elif me:
            self.choosing_weapon = False
            if not me.get("dead"):
                if not self.local_init:
                    self.local_x, self.local_y = me["x"], me["y"]; self.local_init = True
                else:
                    dx = me["x"] - self.local_x; dy = me["y"] - self.local_y
                    if abs(dx) > 120 or abs(dy) > 120: self.local_x, self.local_y = me["x"], me["y"]
                    else:
                        self.local_x += dx * 0.08; self.local_y += dy * 0.08
            elif me.get("dead"):
                self.local_init = False

    def _handle_event_msg(self, msg):
        t = msg.get("type")
        if t == "server_full": self.server_full_msg = "Сервер полон"; self._force_lobby("Сервер полон"); return True
        if t == "no_stage": self._force_lobby("Недостаточный прогресс"); return True
        if t == "game_over": self._force_lobby("Все игроки погибли"); return True
        if t == "state":
            if msg.get("game_over"): self._force_lobby("Все игроки погибли"); return True
            self.server_time_offset = msg.get("server_time", time.time()) - time.time()
            self.players = {p["id"]: p for p in msg["players"]}
            self.bullets = msg["bullets"]; self.zombies = msg.get("zombies", [])
            self.spitter_bullets = msg.get("spitter_bullets", [])
            self.final_boss_bullets = msg.get("final_boss_bullets", [])
            self.puddles = msg.get("puddles", [])
            self.buildings = msg.get("buildings", [])
            self.building_cells = msg.get("building_cells", [])
            self.turret_bullets = msg.get("turret_bullets", [])
            self.electric_turret_bullets = msg.get("electric_turret_bullets", [])
            self.crates = msg.get("crates", []); self.meteors = msg.get("meteors", [])
            self.popups = msg.get("popups", [])
            self.wave = msg.get("wave", 0); self.wave_state = msg.get("wave_state", "break")
            self.wave_total = msg.get("wave_total", 0); self.wave_killed = msg.get("wave_killed", 0)
            self.wave_break_until = msg.get("wave_break_until", 0)
            self.victory = msg.get("victory", False)
            self.max_wave_current = msg.get("max_wave", self.max_wave_current)
            self.wave_button_active = msg.get("wave_button_active", False)
            self.wave_button_x = msg.get("wave_button_x", self.map_w / 2)
            self.wave_button_y = msg.get("wave_button_y", self.map_h / 2)
            me = self.players.get(self.my_id)
            if me and me.get("choosing_weapon"):
                self.choosing_weapon = True
                self.local_init = False
            elif me:
                self.choosing_weapon = False
                if not me.get("dead"):
                    if not self.local_init:
                        self.local_x, self.local_y = me["x"], me["y"]; self.local_init = True
                    else:
                        dx = me["x"] - self.local_x; dy = me["y"] - self.local_y
                        if abs(dx) > 120 or abs(dy) > 120: self.local_x, self.local_y = me["x"], me["y"]
                        else:
                            self.local_x += dx * 0.08; self.local_y += dy * 0.08
                elif me.get("dead"):
                    self.local_init = False
        elif t == "join": self.players[msg["player"]["id"]] = msg["player"]
        elif t == "leave": self.players.pop(msg["id"], None)
        elif t == "victory":
            if not self.cheated_this_session:
                self._mark_stage_complete(); save_gamestate(self.trophies)
        return False

    def _drain_events(self):
        if self.host is not None:
            return self.host.drain_local_events()
        if self.client is not None:
            return self.client.poll()
        return []

    def update(self, dt):
        self._decay_shop_slide(dt)
        self._update_mods_download()
        self._update_music()
        if self.state == "game":
            self._interpolate_network(dt)
        if self.state == "menu" or self.state == "choose_input":
            self._update_menu_bg(dt)
        if self.state == "servers":
            now = time.time()
            if now - self.last_disc > 1.5:
                self.last_disc = now
                if not (self.disc_thread and self.disc_thread.is_alive()):
                    self.disc_thread = threading.Thread(target=self._disc, daemon=True); self.disc_thread.start()
        if self.state == "game" and (self.host is not None or self.client is not None):
            if self.host is not None:
                self._apply_state_from_host()
            if self.client is not None and not self.client.connected:
                self.status = "Соединение потеряно"; self._force_lobby("Соединение потеряно"); return
            if self.client is not None and self.client.no_stage:
                self._force_lobby("Недостаточный прогресс"); return
            if self.client is not None:
                if self.client.cheat_used_pending:
                    self.client.cheat_used_pending = False
                    self._on_cheat_detected()
                if self.client.forbidden_pickups > 0:
                    self.forbidden_count_local += self.client.forbidden_pickups
                    self.client.forbidden_pickups = 0
                if self.client.prism_shard_gets > 0:
                    self.prism_shards_local = self.client.prism_shards_local
                    self.client.prism_shard_gets = 0
                if self.client.stardust_gets > 0:
                    self.stardust_local = self.client.stardust_local
                    self.client.stardust_gets = 0
                if self.client.true_star_unlocked:
                    self.client.true_star_unlocked = False
                    self.true_star_unlocked = True
                    self.info_msg = "★ Открыта Истинная звёздная пушка! ★"
                    self.info_msg_until = time.time() + 5.0
                if self.client.last_prism_unlocked:
                    self.client.last_prism_unlocked = False
                    self.last_prism_unlocked = True
                    self.info_msg = "★ Открыта Последняя призма! ★"
                    self.info_msg_until = time.time() + 5.0
                while self.client.achievements_pending:
                    self._grant_achievement_local(self.client.achievements_pending.pop(0))
                if self.client.apple_eat_events:
                    closest_d = None
                    for ex, ey in self.client.apple_eat_events:
                        if not self.local_init: closest_d = 0; break
                        d = math.hypot(ex - self.local_x, ey - self.local_y)
                        if closest_d is None or d < closest_d: closest_d = d
                    if closest_d is not None and closest_d < 1000:
                        vol = max(0.1, 0.7 * (1 - closest_d / 1000)); _play_sound(self.snd_apple, vol)
                    self.client.apple_eat_events.clear()
                if self.client.zombie_sound_events:
                    best_vol = 0.0
                    for ev in self.client.zombie_sound_events:
                        zx, zy = ev[0], ev[1]
                        is_boss = ev[2] if len(ev) > 2 else False
                        is_final = ev[3] if len(ev) > 3 else False
                        if not self.local_init: vol = 0.4
                        else:
                            d = math.hypot(zx - self.local_x, zy - self.local_y)
                            if d > 1400: continue
                            vol = max(0.05, 0.7 * (1 - d / 1400))
                        if is_final: vol = min(1.0, vol * 1.5)
                        elif is_boss: vol = min(1.0, vol * 1.2)
                        if vol > best_vol: best_vol = vol
                    if best_vol > 0: _play_sound(self.snd_zombie, best_vol)
                    self.client.zombie_sound_events.clear()
                if self.client.crate_popups and self.crate_popup is None:
                    self.crate_popup = self.client.crate_popups.pop(0); self.client.crate_popups.clear()
            for msg in self._drain_events():
                t = msg.get("type")
                if t == "state":
                    if self.host is None:
                        if self._handle_event_msg(msg): return
                    continue
                if t == "server_full": self.server_full_msg = "Сервер полон"; self._force_lobby("Сервер полон"); return
                if t == "no_stage": self._force_lobby("Недостаточный прогресс"); return
                if t == "game_over": self._force_lobby("Все игроки погибли"); return
                if t == "kill":
                    if not self.cheated_this_session and not self.no_stats_this_session:
                        self.trophies["kills"] = self.trophies.get("kills", 0) + 1
                elif t == "death":
                    if not self.cheated_this_session and not self.no_stats_this_session:
                        self.trophies["deaths"] = self.trophies.get("deaths", 0) + 1
                elif t == "win":
                    if not self.cheated_this_session and not self.no_stats_this_session:
                        self.trophies["wins"] = self.trophies.get("wins", 0) + 1
                        save_gamestate(self.trophies)
                elif t == "achievement":
                    if not self.no_stats_this_session:
                        self._grant_achievement_local(msg.get("key"))
                elif t == "unlock":
                    key = msg.get("key")
                    if key:
                        ul = set(self.trophies.get("unlocks", []))
                        if key not in ul:
                            ul.add(key)
                            self.trophies["unlocks"] = list(ul)
                            save_gamestate(self.trophies)
                elif t == "weapon_unlocked":
                    self.info_msg = f"Получено оружие из бокса!"
                    self.info_msg_until = time.time() + 3.0
                elif t == "cheat_used":
                    self._on_cheat_detected()
                elif t == "forbidden_get":
                    self.forbidden_count_local += 1
                elif t == "prism_shard_get":
                    self.prism_shards_local = msg.get("count", self.prism_shards_local + 1)
                elif t == "stardust_get":
                    self.stardust_local = msg.get("count", self.stardust_local + 1)
                elif t == "true_star_unlocked":
                    self.true_star_unlocked = True
                    self.info_msg = "★ Открыта Истинная звёздная пушка! ★"
                    self.info_msg_until = time.time() + 5.0
                elif t == "last_prism_unlocked":
                    self.last_prism_unlocked = True
                    self.info_msg = "★ Открыта Последняя призма! ★"
                    self.info_msg_until = time.time() + 5.0
                elif t == "apple_eat":
                    ex = msg.get("x", 0); ey = msg.get("y", 0)
                    if not self.local_init: vol = 0.5
                    else:
                        d = math.hypot(ex - self.local_x, ey - self.local_y)
                        vol = max(0.1, 0.7 * (1 - d / 1000)) if d < 1000 else 0
                    if vol > 0: _play_sound(self.snd_apple, vol)
                elif t == "zombie_sound":
                    zx = msg.get("x", 0); zy = msg.get("y", 0)
                    is_boss = msg.get("boss", False); is_final = msg.get("final", False)
                    if not self.local_init: vol = 0.4
                    else:
                        d = math.hypot(zx - self.local_x, zy - self.local_y)
                        vol = max(0.05, 0.7 * (1 - d / 1400)) if d < 1400 else 0
                    if is_final: vol = min(1.0, vol * 1.5)
                    elif is_boss: vol = min(1.0, vol * 1.2)
                    if vol > 0: _play_sound(self.snd_zombie, vol)
                elif t == "crate_opened":
                    if self.crate_popup is None:
                        self.crate_popup = {"rarity": msg.get("rarity", "rare"),
                                             "color": msg.get("color", [60, 200, 60]),
                                             "buffs": msg.get("buffs", []),
                                             "coins": msg.get("coins", 0), "xp": msg.get("xp", 0)}
                elif t == "victory":
                    if not self.cheated_this_session and not self.no_stats_this_session:
                        self._mark_stage_complete(); save_gamestate(self.trophies)
            if self.host is not None and not self.cheated_this_session:
                save_gamestate(self.trophies)
            if not self.choosing_weapon:
                self._send_input(dt)

    def _decay_shop_slide(self, dt):
        """Плавно двигает _shop_scroll_cur к _shop_scroll_target,
        ограничивает обе величины [0, _shop_scroll_max]."""
        try:
            k = min(1.0, dt * 12.0)
            self._shop_scroll_cur += (self._shop_scroll_target - self._shop_scroll_cur) * k
            mx = max(0.0, getattr(self, "_shop_scroll_max", 0.0))
            if self._shop_scroll_target < 0: self._shop_scroll_target = 0.0
            if self._shop_scroll_target > mx: self._shop_scroll_target = mx
            if self._shop_scroll_cur < 0: self._shop_scroll_cur = 0.0
            if self._shop_scroll_cur > mx: self._shop_scroll_cur = mx
        except Exception:
            pass

    def _disc(self):
        found = discover(timeout=1.0)
        seen = set(); uniq = []
        for s in found:
            if s[2] == "__solo__": continue
            k = (s[0], s[1])
            if k in seen: continue
            seen.add(k); uniq.append(s)
        self.servers = uniq
        if not uniq: self.status = "Серверов не найдено."
        elif self.server_full_msg: self.status = self.server_full_msg

    def _send_input(self, dt):
        if self.my_id is None: return
        me = self.players.get(self.my_id)
        if not me or me.get("dead") or me.get("choosing_weapon"):
            self.local_init = False; return
        if not me.get("weapon"):
            me["weapon"] = "fist"
        if self.chat_kb.open:
            self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": me.get("angle", 0)}); return
        now_server = time.time() + self.server_time_offset
        wkey = me.get("weapon", "base")
        wstats = WEAPON_STATS.get(wkey, WEAPON_STATS["base"])
        base_cd = wstats.get("cooldown", SHOOT_CD)
        rate_mult = 1.0
        if me.get("shoot_until", 0) > now_server: rate_mult *= MINIGUN_SHOOT_MULT
        if me.get("crazy_until", 0) > now_server:
            rate_mult *= CRAZY_MULT_ACH if self._has_achievement(ACH_NOT_FUNNY) else CRAZY_MULT
        cd = max(0.016, base_cd / rate_mult)
        speed_mult = LIGHTNING_SPEED_MULT if me.get("speed_until", 0) > now_server else 1.0
        _ms = MOD_API.call("modify_speed", self, me, speed_mult)
        if _ms:
            for _v in _ms:
                if isinstance(_v, (int, float)) and _v > 0:
                    speed_mult = _v; break
        if not self.local_init: self.local_x, self.local_y = me["x"], me["y"]; self.local_init = True
        # Движение
        if self.input_mode == "pc":
            mx = 0.0; my = 0.0
            if "a" in self.keys_held: mx -= 1
            if "d" in self.keys_held: mx += 1
            if "w" in self.keys_held: my -= 1
            if "s" in self.keys_held: my += 1
            if mx != 0 or my != 0:
                n = math.hypot(mx, my)
                if n > 0: mx /= n; my /= n
        else:
            mx, my = self.move_joy.value
        new_x = self.local_x + mx * PLAYER_SPEED * speed_mult * dt
        new_y = self.local_y + my * PLAYER_SPEED * speed_mult * dt
        new_x = max(PLAYER_R, min(self.map_w - PLAYER_R, new_x))
        new_y = max(PLAYER_R, min(self.map_h - PLAYER_R, new_y))
        half = BARRICADE_GRID / 2
        for b in self.buildings:
            if b.get("kind") == BUILD_DOOR: continue  # игроки ходят сквозь дверь
            left = b["x"] - half; right = b["x"] + half
            top = b["y"] - half; bottom = b["y"] + half
            nx = max(left, min(new_x, right)); ny = max(top, min(new_y, bottom))
            dx = new_x - nx; dy = new_y - ny; d2 = dx*dx + dy*dy
            if d2 < PLAYER_R * PLAYER_R:
                d = math.sqrt(d2) if d2 > 1e-12 else 0.0
                if d < 1e-6:
                    cxx = b["x"]; cyy = b["y"]; dxs = new_x - cxx; dys = new_y - cyy
                    if abs(dxs) > abs(dys): new_x = cxx + (half + PLAYER_R) * (1 if dxs > 0 else -1)
                    else: new_y = cyy + (half + PLAYER_R) * (1 if dys > 0 else -1)
                else:
                    nx2 = dx / d; ny2 = dy / d; push = PLAYER_R - d
                    new_x += nx2 * push; new_y += ny2 * push
        # блок движения сквозь постройки (клиент-сайд предикция)
        if self.buildings:
            if _seg_blocked_by_buildings(self.local_x, self.local_y, new_x, new_y, self.buildings, BUILD_DOOR):
                new_x, new_y = _first_block_along_segment(self.local_x, self.local_y, new_x, new_y, self.buildings, BUILD_DOOR)
        self.local_x = new_x; self.local_y = new_y
        # Угол
        if self.input_mode == "pc":
            # Угол к курсору
            mxp, myp = pygame.mouse.get_pos()
            # Курсор в экранных координатах, нужно относительно центра экрана
            cx, cy = self.camera
            world_mx = mxp + cx; world_my = myp + cy
            angle = math.atan2(world_my - self.local_y, world_mx - self.local_x)
            me["angle"] = angle
            if me.get("frozen_until", 0) > now_server:
                self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": angle}); return
            no_shoot = wstats.get("no_shoot", False)
            # === ЛУК: в ПК-режиме не стреляем автоматически ===
            if wkey == "bow":
                if self.mouse_held and me.get("charge_start", 0) == 0:
                    me["charge_start"] = time.time()
                self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": angle})
                return
            if not no_shoot and self.mouse_held:
                if wkey in ("laser", "first_prism", "last_prism"):
                    if time.time() - self.last_shot > cd:
                        self._send_to_server({"type": "shoot", "angle": angle})
                        self.last_shot = time.time()
                        self._fire_effects()
                else:
                    if time.time() - self.last_shot > cd:
                        self._send_to_server({"type": "shoot", "angle": angle})
                        self.last_shot = time.time()
                        self._fire_effects()
            self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": angle})
            return
        # Тач-режим (старое поведение)
        ax, ay = self.aim_joy.value
        angle = me.get("angle", 0); joy_active = abs(ax) + abs(ay) > 0.2
        if me.get("frozen_until", 0) > now_server:
            self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": angle}); return
        no_shoot = wstats.get("no_shoot", False)
        if not no_shoot:
            # === ЛУК: в тач-режиме не стреляем автоматически ===
            if wkey == "bow":
                if joy_active:
                    angle = math.atan2(ay, ax); me["angle"] = angle
                    if me.get("charge_start", 0) == 0:
                        me["charge_start"] = time.time()
                else:
                    # джойстик отпущен — стреляем
                    if me.get("charge_start", 0) > 0:
                        self._fire_charged_shot(me, time.time())
                self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": angle})
                return
            # === ЛУК: в тач-режиме не стреляем автоматически ===
            if wkey == "bow":
                if joy_active:
                    angle = math.atan2(ay, ax); me["angle"] = angle
                    if me.get("charge_start", 0) == 0:
                        me["charge_start"] = time.time()
                else:
                    # джойстик отпущен — стреляем
                    if me.get("charge_start", 0) > 0:
                        self._fire_charged_shot(me, time.time())
                self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": angle})
                return
            if wkey in ("laser", "first_prism", "last_prism"):
                if joy_active:
                    angle = math.atan2(ay, ax); me["angle"] = angle
                if time.time() - self.last_shot > cd:
                    self._send_to_server({"type": "shoot", "angle": angle})
                    self.last_shot = time.time()
                    self._fire_effects()
            elif joy_active:
                angle = math.atan2(ay, ax); me["angle"] = angle
                if time.time() - self.last_shot > cd:
                    self._send_to_server({"type": "shoot", "angle": angle}); self.last_shot = time.time()
                    self._fire_effects()
            elif self.btn_auto.toggle:
                if time.time() - self.last_shot > cd:
                    self._send_to_server({"type": "shoot", "angle": angle}); self.last_shot = time.time()
                    self._fire_effects()
        self._send_to_server({"type": "input", "x": self.local_x, "y": self.local_y, "angle": angle})

    def _fire_charged_shot(self, p, now):
        """Выстрел из лука с учётом времени зарядки (макс 3 сек)."""
        start = p.get("charge_start", 0)
        p["charge_start"] = 0.0
        if start <= 0: return
        
        duration = min(now - start, 3.0)  # макс 3 сек
        charge_ratio = duration / 3.0      # от 0 до 1
        
        stats = WEAPON_STATS.get("bow", WEAPON_STATS["base"])
        lvl = p.get("level", 0)
        base_dmg = weapon_dmg_with_level(stats, lvl)
        
        # Урон: от 20% (при 0 сек) до 100% (при 3 сек)
        final_dmg = int(base_dmg * (0.2 + 0.8 * charge_ratio))
        # Скорость: от 50% до 100%
        final_speed = int(stats["speed"] * (0.5 + 0.5 * charge_ratio))
        
        angle = p.get("charge_angle", p.get("angle", 0))
        self._send_to_server({
            "type": "shoot",
            "angle": angle,
            "custom_dmg": final_dmg,
            "custom_speed": final_speed
        })
        self._fire_effects()

    
    
    
    
    
    
    
    
    
    def _fire_effects(self):
        me = self.players.get(self.my_id)
        if not me: return
        key = me.get("weapon", "base")
        stats = WEAPON_STATS.get(key, WEAPON_STATS["base"])
        if stats.get("melee"): _play_sound(self.snd_swo, 0.7)
        else: _play_sound(self.snd_shoot, 0.5)

    # ============================================================
    #  ОТРИСОВКА
    # ============================================================
    def draw(self):
        # --------------------------------------------------------------
        # Слой 1: фон, сетка, граница карты — чёткие
        # --------------------------------------------------------------
        self.canvas.fill((200, 240, 200))
        _saved = self.screen; self.screen = self.canvas
        try:
            if self.state == "choose_input": self._draw_choose_input()
            elif self.state == "keybinds": self._draw_keybinds()
            elif self.state == "menu": self._draw_menu()
            elif self.state == "servers": self._draw_servers()
            elif self.state == "settings": self._draw_settings()
            elif self.state == "stats": self._draw_stats()
            elif self.state == "mods": self._draw_mods_settings()
            elif self.state == "server_settings": self._draw_server_settings()
            else:
                if self.choosing_weapon: self._draw_choose_weapon()
                # _draw_game больше не вызывается — мир рисует _draw_game_overlay
        finally:
            self.screen = _saved

        # --------------------------------------------------------------
        # Слой 2: overlay — мир + все игровые объекты + меню-зомби + кнопки.
        # Пикселизируется ВЕСЬ overlay.
        # --------------------------------------------------------------
        self.overlay_canvas.fill((0, 0, 0, 0))
        _saved = self.screen; self.screen = self.overlay_canvas
        try:
            self._draw_overlay_pixel()
        finally:
            self.screen = _saved
        self._pixelate_overlay()
        self.canvas.blit(self.overlay_canvas, (0, 0))

        # --------------------------------------------------------------
        # Слой 3: UI поверх пиксельного — чёткий. Рисуется только в игре
        # (в меню уже всё в overlay).
        # --------------------------------------------------------------
        if self.state == "game":
            _saved = self.screen; self.screen = self.canvas
            try:
                if not self.choosing_weapon:
                    self._draw_ui_clear()
                if self.mods_warning is not None:
                    self._draw_mods_warning()
            finally:
                self.screen = _saved

        # --------------------------------------------------------------
        # Вывод на экран
        # --------------------------------------------------------------
        if (self.real_w, self.real_h) != (WIDTH, HEIGHT):
            scaled = pygame.transform.scale(self.canvas, (self.real_w, self.real_h))
            self.screen.blit(scaled, (0, 0))
        else:
            self.screen.blit(self.canvas, (0, 0))

        # === мод рисует в РЕАЛЬНЫЙ screen, чтобы эффект был виден ===
        try:
            MOD_API.call("on_draw", self, self.screen)
        except Exception as _e:
            print("[mods] on_draw error:", _e)
        if self.input_mode == "pc" and self.state != "choose_input":
            mx, my = pygame.mouse.get_pos()
            try:
                sx = mx * WIDTH // self.real_w if self.real_w else mx
                sy = my * HEIGHT // self.real_h if self.real_h else my
            except Exception:
                sx, sy = mx, my
            pygame.draw.circle(self.screen, (255, 60, 60), (int(sx), int(sy)), 12, 3)
            pygame.draw.line(self.screen, (255, 60, 60), (sx - 16, sy), (sx + 16, sy), 2)
            pygame.draw.line(self.screen, (255, 60, 60), (sx, sy - 16), (sx, sy + 16), 2)
        pygame.display.flip()

    def _draw_ui_clear(self):
        """Чёткий UI поверх пиксельного overlay: миникарта, хотбар, кнопки,
        надписи HP/XP/волна/монеты, магазин, слот-пикер, попап ящика,
        дроп-меню, VICTORY/DEAD, ачивки, чат."""
        s = self.screen
        me = self.players.get(self.my_id)
        cx, cy = self.camera
        now_server = time.time() + self.server_time_offset

        # миникарта
        self._draw_minimap(me, cx, cy)

        # хотбар
        if me: self._draw_hotbar(me)

        # кнопки магазина / авто / чата
        mouse = pygame.mouse.get_pos()
        self.btn_auto.draw(s, self.small, mouse)
        self.btn_shop_weapons.draw(s, self.small, mouse)
        self.btn_chat_open.draw(s, self.small, mouse)

        # надписи
        if me:
            lvl = me.get("level", 0); coins = me.get("coins", 0)
            wkey = me.get("weapon", "base"); ws = WEAPON_STATS.get(wkey, WEAPON_STATS["base"])
            dmg_now = weapon_dmg_with_level(ws, lvl)
            need = xp_to_next_level(lvl); have = me.get("xp", 0) - xp_for_level(lvl)
            s.blit(self.font.render(f"HP: {me.get('hp', 0)}", True, (20,20,30)), (20,20))
            s.blit(self.font.render(f"Lv{lvl}   XP: {me.get('xp', 0)}", True, (20,20,30)), (20,50))
            s.blit(self.small.render(f"До Lv{lvl+1}: {have}/{need}", True, (40,40,60)), (20,80))
            s.blit(self.font.render(f"Монеты: {coins}", True, (200,160,0)), (20,100))
            s.blit(self.small.render(f"Оружие: {wkey}   Урон: {dmg_now}", True, (100,20,20)), (20,128))
            if self.is_admin or me.get("is_admin_for_session", False):
                s.blit(self.small.render("АДМИН", True, (180,40,180)), (20,148))
            if me.get("wanish"):
                s.blit(self.small.render("★ WANISH (невидимый)", True, (140, 100, 220)), (20, 168))
            if self.cheated_this_session:
                s.blit(self.small.render("★ СТАТИСТИКА ОТКЛЮЧЕНА", True, (220,40,40)), (20,188))
            if getattr(self, "no_stats_this_session", False):
                s.blit(self.small.render("★ СТАТИСТИКА ОТКЛЮЧЕНА (сюжет выше)", True, (255,140,60)), (20,208))
            y = 210
            for label, key2, col2 in [("Ускорение","speed_until",(200,140,0)),
                                       ("Миниган","shoot_until",(20,60,180)),
                                       ("Огненное дуло","firedoom_until",(220,80,30)),
                                       ("СУМАСШЕСТВИЕ! (x20)","crazy_until",(255,60,200)),
                                       ("ГОРЮ","fire_until",(255,60,20)),
                                       ("ЗАМОРОЖЕН","frozen_until",(80,180,255))]:
                if me.get(key2, 0) > now_server:
                    left = me[key2] - now_server
                    s.blit(self.small.render(f"{label}: {left:.1f}с", True, col2), (20, y)); y += 20
            passive = me.get("passive")
            if passive:
                pinfo = PASSIVES.get(passive, {})
                s.blit(self.small.render(f"Пассивка: {pinfo.get('label','')}", True, (200, 160, 60)), (20, y)); y += 20
            if self.prism_shards_local > 0:
                s.blit(self.small.render(f"Осколки призмы: {self.prism_shards_local}/{PRISM_SHARDS_NEEDED}",
                                          True, (220, 220, 240)), (20, y)); y += 20
            if self.stardust_local > 0:
                s.blit(self.small.render(f"Звёздная пыль: {self.stardust_local}/{STARDUST_NEEDED}",
                                          True, (255, 240, 160)), (20, y)); y += 20
            if self.host is not None:
                s.blit(self.small.render(f"КОД: {self.host.server_code}", True, (200, 220, 200)),
                       (WIDTH - 200, 60))
        if self.max_wave_current >= 999999:
            _wave_text = f"ВОЛНА {self.wave}   Убито {self.wave_killed}/{self.wave_total}"
        else:
            _wave_text = f"ВОЛНА {self.wave}/{self.max_wave_current}   Убито {self.wave_killed}/{self.wave_total}"
        wt = self.font.render(_wave_text, True, (150,20,20))
        s.blit(wt, wt.get_rect(center=(WIDTH // 2, 26)))
        zc = self.font.render(f"Зомби: {len(self.zombies)}", True, (60,120,60))
        s.blit(zc, zc.get_rect(center=(WIDTH // 2, 58)))
        if self.solo_mode:
            solo = self.small.render("СОЛО", True, (140,60,180))
            s.blit(solo, solo.get_rect(center=(WIDTH // 2, 86)))

        # магазин, слот-пикер, попап ящика, дроп-меню — чётко поверх
        if self.shop_open: self._draw_shop()
        if self.weapon_desc_popup is not None: self._draw_weapon_desc_popup()
        if self.slot_picker is not None: self._draw_slot_picker()
        if self.crate_popup is not None: self._draw_crate_popup(self.crate_popup)
        if self.drop_menu_open: self._draw_drop_menu()

        # info_msg
        if self.info_msg and time.time() < self.info_msg_until:
            im = self.font.render(self.info_msg, True, (255, 220, 120))
            s.blit(im, im.get_rect(center=(WIDTH//2, HEIGHT - 100)))

        # VICTORY / DEAD / достижения / чат
        if self.victory:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,180))
            s.blit(overlay, (0, 0))
            s.blit(self.huge.render("ПОБЕДА!", True, (255,220,60)),
                   self.huge.render("ПОБЕДА!", True, (255,220,60)).get_rect(center=(WIDTH//2, HEIGHT//2 - 40)))
            s.blit(self.big.render(f"Этап {STAGE_NAMES.get(self._my_stage(), '')} пройден!", True, (255,255,255)),
                   self.big.render(f"Этап {STAGE_NAMES.get(self._my_stage(), '')} пройден!", True, (255,255,255)).get_rect(center=(WIDTH//2, HEIGHT//2 + 40)))
        if me and me.get("dead"):
            respawn_left = max(0.0, me.get("respawn_at", 0) - now_server)
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,140))
            s.blit(overlay, (0, 0))
            s.blit(self.huge.render("Вы погибли!", True, (255,60,60)),
                   self.huge.render("Вы погибли!", True, (255,60,60)).get_rect(center=(WIDTH//2, HEIGHT//2 - 60)))
            s.blit(self.big.render(f"Респавн через {int(respawn_left) + 1}", True, (255,255,255)),
                   self.big.render(f"Респавн через {int(respawn_left) + 1}", True, (255,255,255)).get_rect(center=(WIDTH//2, HEIGHT//2 + 40)))
        if self.achievement_popup is not None: self._draw_achievement_popup()
        elif self.unlock_popup is not None: self._draw_unlock_popup()
        if self.mods_warning is None and self.chat_kb.open:
            self.chat_kb.draw(s, self.font, self.small)

    def _draw_keybinds(self):
        self.screen.fill((25, 35, 30))
        self.screen.blit(self.big.render("НАСТРОЙКА РАСКЛАДКИ", True, (220, 240, 220)),
                         self.big.render("НАСТРОЙКА РАСКЛАДКИ", True, (220, 240, 220)).get_rect(center=(WIDTH//2, 60)))
        sub = self.small.render("Тапни строку, затем нажми клавишу. Esc — отмена.", True, (180, 200, 180))
        self.screen.blit(sub, sub.get_rect(center=(WIDTH//2, 110)))
        sub2 = self.small.render("Клавиши работают только в режиме ПК.", True, (180, 200, 180))
        self.screen.blit(sub2, sub2.get_rect(center=(WIDTH//2, 135)))
        # список
        list_x = WIDTH // 2 - 400
        list_w = 800
        row_h = 60
        y0 = 200 - int(self.kb_scroll)
        for i, key in enumerate(KEYBIND_ORDER):
            y = y0 + i * row_h
            if y < 160 or y > HEIGHT - 100: continue
            r = pygame.Rect(list_x, y, list_w, row_h - 6)
            active = (self.kb_active_row == i)
            bg = (200, 160, 40) if active else (45, 60, 50)
            pygame.draw.rect(self.screen, bg, r, border_radius=8)
            pygame.draw.rect(self.screen, (200, 220, 200) if active else (120, 140, 130),
                             r, 3 if active else 2, border_radius=8)
            label = KEYBIND_LABELS.get(key, key)
            self.screen.blit(self.font.render(label, True, (240, 240, 240)), (r.x + 20, r.y + 12))
            kb = self.keybinds.get(key)
            kb_text = kb if kb else "none"
            kb_col = (255, 240, 120) if active else (200, 220, 220)
            kbt = self.font.render(kb_text, True, kb_col)
            self.screen.blit(kbt, kbt.get_rect(midright=(r.right - 20, r.centery)))
        # кнопки
        mouse = pygame.mouse.get_pos()
        self.btn_keybinds_back.draw(self.screen, self.font, mouse)
        self.btn_keybinds_reset.draw(self.screen, self.font, mouse)

    def _draw_choose_input(self):
        self._draw_menu_bg()
        self.screen.blit(self.huge.render("ВЫБЕРИ УПРАВЛЕНИЕ", True, (255, 240, 180)),
                         self.huge.render("ВЫБЕРИ УПРАВЛЕНИЕ", True, (255, 240, 180)).get_rect(center=(WIDTH//2, HEIGHT//2 - 160)))
        sub = self.font.render("Это можно поменять в настройках", True, (200, 220, 200))
        self.screen.blit(sub, sub.get_rect(center=(WIDTH//2, HEIGHT//2 - 100)))
        mouse = pygame.mouse.get_pos()
        self.btn_choose_pc.draw(self.screen, self.huge, mouse)
        self.btn_choose_touch.draw(self.screen, self.huge, mouse)

    def _draw_choose_weapon(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((20, 30, 20))
        self.screen.blit(overlay, (0, 0))
        self.screen.blit(self.huge.render("ВЫБЕРИ ОРУЖИЕ", True, (255, 240, 180)),
                         self.huge.render("ВЫБЕРИ ОРУЖИЕ", True, (255, 240, 180)).get_rect(center=(WIDTH // 2, 120)))
        cols = [("base", "Пистолет", "Стартовое, слабое, но вечное"),
                ("rifle", "Автомат", "Скорострельный, средний урон"),
                ("shotgun", "Дробовик", "Убойный вблизи, 7 дробин")]
        bw = 360; bh = 400; gap = 40
        total = len(cols) * bw + (len(cols) - 1) * gap
        x0 = WIDTH // 2 - total // 2; y0 = HEIGHT // 2 - bh // 2 + 60
        rects = []
        for i, (key, label, desc) in enumerate(cols):
            r = pygame.Rect(x0 + i * (bw + gap), y0, bw, bh)
            rects.append((key, r))
            mouse = pygame.mouse.get_pos()
            hov = r.collidepoint(mouse)
            bg = (70, 100, 70) if hov else (45, 65, 45)
            pygame.draw.rect(self.screen, bg, r, border_radius=14)
            pygame.draw.rect(self.screen, (240, 220, 160), r, 4, border_radius=14)
            self.screen.blit(self.big.render(label, True, (255, 240, 200)),
                             self.big.render(label, True, (255, 240, 200)).get_rect(center=(r.centerx, r.y + 50)))
            icon_r = pygame.Rect(r.centerx - 70, r.y + 110, 140, 140)
            self._draw_weapon_icon(key, icon_r)
            self.screen.blit(self.font.render(desc, True, (230, 230, 230)),
                             self.font.render(desc, True, (230, 230, 230)).get_rect(center=(r.centerx, r.bottom - 60)))
        self.choose_btn_base = rects[0][1]
        self.choose_btn_rifle = rects[1][1]
        self.choose_btn_shotgun = rects[2][1]

    def _draw_update_banner(self, x, y, big=False):
        """Рисует наклонную надпись с названием обновления, как в Minecraft.
        x, y — базовая позиция; big — крупный шрифт для меню."""
        try:
            font = self.big if big else self.small
            text = current_update
            surf = font.render(text, True, (255, 230, 120))
            rotated = pygame.transform.rotate(surf, -20)
            # Тень
            shadow = font.render(text, True, (60, 40, 0))
            shadow_r = pygame.transform.rotate(shadow, -20)
            self.screen.blit(shadow_r, (x + 2, y + 2))
            self.screen.blit(rotated, (x, y))
        except Exception:
            pass

    def _draw_menu(self):
        self._draw_menu_bg()
        title = "Piu piu.io"
        sh = self.menu_title.render(title, True, (10, 40, 10))
        self.screen.blit(sh, sh.get_rect(center=(WIDTH // 2 + 4, HEIGHT // 2 - 210 + 4)))
        tm = self.menu_title.render(title, True, (150, 255, 150))
        self.screen.blit(tm, tm.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 210)))
        # Наклонная надпись обновления справа-снизу от заголовка
        self._draw_update_banner(WIDTH // 2 + 180, HEIGHT // 2 - 150, big=True)
        cur = self._my_stage()
        sub = self.font.render(f"Сюжет: {STAGE_NAMES.get(cur, '10 волн')}   Побед: {self._my_wins()}",
                                True, (180, 230, 180))
        self.screen.blit(sub, sub.get_rect(center=(WIDTH//2, HEIGHT//2 - 140)))
        if self.info_msg and time.time() < self.info_msg_until:
            im = self.font.render(self.info_msg, True, (255, 80, 80))
            self.screen.blit(im, im.get_rect(center=(WIDTH//2, HEIGHT//2 + 260)))
        panel = pygame.Rect(WIDTH//2 - 200, HEIGHT//2 - 170, 400, 400)
        ps = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
        ps.fill((10, 20, 10, 160))
        self.screen.blit(ps, (panel.x, panel.y))
        mouse = pygame.mouse.get_pos()
        self.btn_play.draw(self.screen, self.font, mouse)
        self.btn_solo.draw(self.screen, self.font, mouse)
        self.btn_settings.draw(self.screen, self.font, mouse)
        self.btn_stats.draw(self.screen, self.font, mouse)
        if patch_version:
            _pvsurf2 = self.font.render(patch_version, True, (70, 70, 70))
            self.screen.blit(_pvsurf2, _pvsurf2.get_rect(bottomright=(WIDTH - 140, HEIGHT - 20)))
        if patch_version:
            _pvsurf2 = self.small.render(patch_version, True, (90, 90, 90))
            self.screen.blit(_pvsurf2, _pvsurf2.get_rect(bottomright=(WIDTH - 10, HEIGHT - 10)))

    def _draw_stats(self):
        self.screen.blit(self.big.render("СТАТИСТИКА", True, (30, 70, 30)),
                         self.big.render("СТАТИСТИКА", True, (30, 70, 30)).get_rect(center=(WIDTH // 2, 50)))
        panel = pygame.Rect(WIDTH // 2 - 650, 110, 1300, 500)
        pygame.draw.rect(self.screen, (240, 250, 240), panel, border_radius=12)
        pygame.draw.rect(self.screen, (100, 160, 100), panel, 3, border_radius=12)
        y0 = panel.y + 30; step = 100
        for i, (label, key, color) in enumerate([("Убито зомби:", "kills", (200,40,40)),
                                                  ("Побед:", "wins", (220,180,0)),
                                                  ("Смертей:", "deaths", (80,80,100))]):
            self.screen.blit(self.font.render(label, True, (40, 40, 60)), (panel.x + 40, y0 + i*step))
            self.screen.blit(self.big.render(str(self.trophies.get(key, 0)), True, color), (panel.x + 40, y0 + i*step + 26))
        rx = panel.x + 340
        self.screen.blit(self.font.render("СЮЖЕТ", True, (40, 60, 100)), (rx, y0))
        cur = self._my_stage()
        for i, st in enumerate([0, 1, 2]):
            if i < cur: status, col = "пройден", (40,160,40)
            elif i == cur: status, col = "текущий", (220,160,40)
            else: status, col = "заблокирован", (140,140,140)
            self.screen.blit(self.small.render(f"Этап {i+1}: {STAGE_NAMES[st]} — {status}", True, col), (rx, y0 + 34 + i * 26))
        y = y0 + 34 + 3 * 26 + 12
        self.screen.blit(self.small.render("Разблокировано:", True, (40, 60, 100)), (rx, y)); y += 22
        for k in [UNLOCK_BOSSRUSH, UNLOCK_PVP, UNLOCK_HARD, UNLOCK_STAGE100, UNLOCK_FORBIDDEN]:
            ok = self._is_unlocked(k); col = (40,160,40) if ok else (140,140,140)
            self.screen.blit(self.small.render(f"  {'✓' if ok else '✗'} {UNLOCK_NAMES[k]}", True, col), (rx, y)); y += 22
        ax = panel.x + 720
        self.screen.blit(self.font.render("ДОСТИЖЕНИЯ", True, (120, 40, 120)), (ax, y0))
        ay = y0 + 34; got = 0
        for k in [ACH_ONE_MAN_ARMY, ACH_NOT_FUNNY, ACH_HORRORS_OF_PAST, ACH_BOB]:
            ok = self._has_achievement(k); got += 1 if ok else 0
            col = (40,160,40) if ok else (140,140,140)
            self.screen.blit(self.small.render(f"  {'✓' if ok else '✗'} {ACHIEVEMENT_NAMES[k]}", True, col), (ax, ay)); ay += 20
            self.screen.blit(self.tiny.render(f"     {ACHIEVEMENT_DESCS[k]}", True, (100,100,100)), (ax, ay)); ay += 18
            self.screen.blit(self.tiny.render(f"     Эффект: {ACHIEVEMENT_EFFECTS[k]}", True, (160,100,40)), (ax, ay)); ay += 28
        self.screen.blit(self.small.render(f"Получено: {got}/4", True, (120, 40, 120)), (ax, ay))
        mouse = pygame.mouse.get_pos(); self.btn_stats_back.draw(self.screen, self.font, mouse)

    def _draw_settings(self):
        self.screen.blit(self.big.render("НАСТРОЙКИ", True, (30, 70, 30)),
                         self.big.render("НАСТРОЙКИ", True, (30, 70, 30)).get_rect(center=(WIDTH // 2, 80)))
        label = self.font.render("Показ кнопок магазинов", True, (30, 50, 30))
        self.screen.blit(label, label.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 70)))
        mouse = pygame.mouse.get_pos()
        self.btn_mode_default.draw(self.screen, self.font, mouse)
        self.btn_mode_center.draw(self.screen, self.font, mouse)
        self.btn_preview_toggle.draw(self.screen, self.font, mouse)
        self.btn_input_toggle.draw(self.screen, self.font, mouse)
        self.btn_keybinds.draw(self.screen, self.font, mouse)
        self.btn_pixelate.draw(self.screen, self.font, mouse)
        hint = self.small.render("Настройки сохраняются автоматически.", True, (60, 80, 60))
        self.screen.blit(hint, hint.get_rect(center=(WIDTH // 2, HEIGHT - 160)))
        self.btn_settings_back.draw(self.screen, self.font, mouse)

    def _draw_mods_settings(self):
        self.screen.blit(self.big.render("МОДЫ", True, (30, 70, 30)),
                         self.big.render("МОДЫ", True, (30, 70, 30)).get_rect(center=(WIDTH // 2, 40)))
        sub = self.small.render("Отметь галочкой моды. Листай кнопками ▲▼ справа.", True, (60, 80, 60))
        self.screen.blit(sub, sub.get_rect(center=(WIDTH // 2, 80)))
        _s = load_settings()
        enabled = set(_s.get("enabled_mods", []))
        self._mods_checkboxes = []
        found = discover_mods()

        top = 120
        bottom = HEIGHT - 100
        row_h = 90
        total_h = len(found) * row_h
        max_scroll = max(0, total_h - (bottom - top))
        if not hasattr(self, "mods_scroll"): self.mods_scroll = 0.0
        if self.mods_scroll < 0: self.mods_scroll = 0
        if self.mods_scroll > max_scroll: self.mods_scroll = max_scroll
        self._mods_last_max_scroll = max_scroll

        clip = pygame.Rect(0, top, WIDTH, bottom - top)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(clip)

        y = top - int(self.mods_scroll)
        if not found:
            self.screen.blit(self.font.render("Папка addon/ пуста.", True, (120,120,120)), (60, top + 20))
        for mod in found:
            r = pygame.Rect(60, y, WIDTH - 120, 80)
            if y + 80 < top or y > bottom:
                y += row_h
                continue
            active = mod["id"] in enabled
            pygame.draw.rect(self.screen, (60,100,60) if active else (50,50,60), r, border_radius=8)
            pygame.draw.rect(self.screen, (180,180,200), r, 2, border_radius=8)
            box_r = pygame.Rect(r.x + 16, r.y + 24, 32, 32)
            pygame.draw.rect(self.screen, (40,120,40) if active else (60,60,70), box_r, border_radius=4)
            pygame.draw.rect(self.screen, (220,220,220), box_r, 2, border_radius=4)
            if active:
                pygame.draw.line(self.screen, (255,255,255),
                                 (box_r.x+6, box_r.centery), (box_r.centerx, box_r.bottom-8), 4)
                pygame.draw.line(self.screen, (255,255,255),
                                 (box_r.centerx, box_r.bottom-8), (box_r.right-6, box_r.y+8), 4)
            self.screen.blit(self.font.render(mod["name"], True, (240,240,240)), (r.x + 60, r.y + 12))
            _desc = str(mod.get("description", ""))[:120]
            self.screen.blit(self.small.render(_desc, True, (180,180,180)), (r.x + 60, r.y + 42))
            self._mods_checkboxes.append((mod["id"], r))
            y += row_h

        self.screen.set_clip(old_clip)

        # Кнопки ▲▼ справа
        if max_scroll > 0:
            bx = WIDTH - 90
            up_r = pygame.Rect(bx, top + 10, 60, 60)
            dn_r = pygame.Rect(bx, bottom - 70, 60, 60)
            pygame.draw.rect(self.screen, (60,90,140) if self.mods_scroll > 0 else (50,50,60), up_r, border_radius=10)
            pygame.draw.rect(self.screen, (200,200,240), up_r, 2, border_radius=10)
            ut = self.big.render("▲", True, (240,240,240))
            self.screen.blit(ut, ut.get_rect(center=up_r.center))
            can_dn = self.mods_scroll < max_scroll
            pygame.draw.rect(self.screen, (60,90,140) if can_dn else (50,50,60), dn_r, border_radius=10)
            pygame.draw.rect(self.screen, (200,200,240), dn_r, 2, border_radius=10)
            dt = self.big.render("▼", True, (240,240,240))
            self.screen.blit(dt, dt.get_rect(center=dn_r.center))
            self.mods_btn_up = up_r
            self.mods_btn_down = dn_r
        else:
            self.mods_btn_up = None
            self.mods_btn_down = None

        mouse = pygame.mouse.get_pos()
        self.btn_settings_back.draw(self.screen, self.font, mouse)

    def _handle_mods_click(self, e):
        if self.btn_settings_back.clicked(e) or self.btn_settings_back.clicked_touch(e):
            self.state = "server_settings"; return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.state = "server_settings"; return

        # Кнопки ▲▼
        pos = None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1: pos = e.pos
        elif e.type == pygame.FINGERDOWN: pos = (e.x * WIDTH, e.y * HEIGHT)
        if pos is not None:
            if getattr(self, "mods_btn_up", None) and self.mods_btn_up.collidepoint(pos):
                self.mods_scroll = max(0, self.mods_scroll - 180)
                return
            if getattr(self, "mods_btn_down", None) and self.mods_btn_down.collidepoint(pos):
                self.mods_scroll = min(float(self._mods_last_max_scroll), self.mods_scroll + 180)
                return

        # Колесо мыши
        if e.type == pygame.MOUSEWHEEL:
            self.mods_scroll -= e.y * 50
            if self.mods_scroll < 0: self.mods_scroll = 0
            if self.mods_scroll > self._mods_last_max_scroll: self.mods_scroll = float(self._mods_last_max_scroll)
            return

        # Свайп пальцем
        if e.type == pygame.FINGERDOWN:
            self._mods_drag_start = e.y * HEIGHT
            self._mods_drag_last = self._mods_drag_start
            return
        if e.type == pygame.FINGERMOTION and getattr(self, "_mods_drag_start", None) is not None:
            cur = e.y * HEIGHT
            self.mods_scroll -= (cur - self._mods_drag_last)
            self._mods_drag_last = cur
            if self.mods_scroll < 0: self.mods_scroll = 0
            if self.mods_scroll > self._mods_last_max_scroll: self.mods_scroll = float(self._mods_last_max_scroll)
            return
        if e.type == pygame.FINGERUP:
            if getattr(self, "_mods_drag_start", None) is not None:
                moved = abs((e.y * HEIGHT) - self._mods_drag_start) > 10
                self._mods_drag_start = None
                if not moved:
                    self._mods_click_check((e.x * WIDTH, e.y * HEIGHT))
            return

        # Клик/тап мышью — это клик или drag
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self._mods_drag_start = e.pos[1]
            self._mods_drag_last = e.pos[1]
            return
        if e.type == pygame.MOUSEMOTION and getattr(self, "_mods_drag_start", None) is not None and e.buttons[0]:
            cur = e.pos[1]
            self.mods_scroll -= (cur - self._mods_drag_last)
            self._mods_drag_last = cur
            if self.mods_scroll < 0: self.mods_scroll = 0
            if self.mods_scroll > self._mods_last_max_scroll: self.mods_scroll = float(self._mods_last_max_scroll)
            return
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if getattr(self, "_mods_drag_start", None) is not None:
                moved = abs(e.pos[1] - self._mods_drag_start) > 10
                self._mods_drag_start = None
                if not moved:
                    self._mods_click_check(e.pos)
            return

    def _mods_click_check(self, pos):
        for mid, r in getattr(self, "_mods_checkboxes", []):
            if r.collidepoint(pos):
                _s = load_settings()
                en = list(_s.get("enabled_mods", []))
                if mid in en: en.remove(mid)
                else: en.append(mid)
                _s["enabled_mods"] = en
                save_settings(_s); return

    def _draw_mods_warning(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,210))
        self.screen.blit(overlay, (0,0))
        panel = pygame.Rect(WIDTH//2 - 500, HEIGHT//2 - 260, 1000, 560)
        pygame.draw.rect(self.screen, (40, 30, 20), panel, border_radius=16)
        pygame.draw.rect(self.screen, (255, 120, 40), panel, 4, border_radius=16)
        title = self.big.render("ВНИМАНИЕ!!! Это сервер с модами", True, (255, 180, 80))
        self.screen.blit(title, title.get_rect(center=(WIDTH//2, panel.y + 50)))
        sub = self.font.render("Чтобы зайти на сервер, вам нужно загрузить эти моды:",
                               True, (240,220,200))
        self.screen.blit(sub, sub.get_rect(center=(WIDTH//2, panel.y + 100)))
        y = panel.y + 140
        for m in self.mods_warning.get("mods", [])[:8]:
            name = m.get("name", m.get("id", "?"))
            desc = m.get("description", "")
            self.screen.blit(self.font.render(f"• {name}", True, (255,255,255)),
                             (panel.x + 80, y)); y += 28
            self.screen.blit(self.small.render(desc[:110], True, (200,200,200)),
                             (panel.x + 100, y)); y += 24
        # === Полоса прогресса ===
        _prog = self.mods_warning.get("progress")
        if _prog:
            done, total, errors = _prog
            bar_w = 600
            bar_x = WIDTH // 2 - bar_w // 2
            bar_y = panel.bottom - 200
            pygame.draw.rect(self.screen, (20, 20, 20), (bar_x, bar_y, bar_w, 20), border_radius=8)
            if total > 0:
                fill_w = int(bar_w * done / total)
                pygame.draw.rect(self.screen, (60, 200, 100), (bar_x, bar_y, fill_w, 20), border_radius=8)
            pygame.draw.rect(self.screen, (200, 200, 200), (bar_x, bar_y, bar_w, 20), 2, border_radius=8)
            _prog_text = f"Загружено: {done} / {total}"
            if errors: _prog_text += f"   Ошибок: {len(errors)}"
            self.screen.blit(self.small.render(_prog_text, True, (220, 220, 220)),
                             self.small.render(_prog_text, True, (220, 220, 220)).get_rect(center=(WIDTH//2, bar_y - 15)))
        
        st = self.mods_warning.get("status", "")
        if st:
            stt = self.small.render(st, True, (255, 200, 120))
            self.screen.blit(stt, stt.get_rect(center=(WIDTH//2, panel.bottom - 110)))
        mouse = pygame.mouse.get_pos()
        self.mods_warning_btn.rect = pygame.Rect(WIDTH//2 - 180, panel.bottom - 140, 360, 55)
        self.mods_warning_close.rect = pygame.Rect(WIDTH//2 - 180, panel.bottom - 75, 360, 55)
        self.mods_warning_btn.draw(self.screen, self.font, mouse)
        self.mods_warning_close.draw(self.screen, self.font, mouse)

    def _start_mods_download(self):
        if self.client is None or self.mods_warning is None: return
        mods = self.mods_warning.get("mods", [])
        ids = [m.get("id") for m in mods if m.get("id")]
        if not ids:
            self.client.send_mods_ack()
            self.mods_warning = None; return
        self.mods_warning["status"] = "Загрузка модов..."
        real_ids = []
        for mid in ids:
            mdir = os.path.join("addon", mid)
            if os.path.isdir(mdir) and os.path.isfile(os.path.join(mdir, "manifest.json")):
                continue
            real_ids.append(mid)
        if not real_ids:
            self.mods_warning["status"] = "Все моды уже установлены. Вход..."
            self.mods_warning["progress"] = (len(ids), len(ids), [])
            self.client.send_mods_ack()
            self.mods_warning = None
            return
        self._mods_pending_ids = set(real_ids)
        self._mods_errors = []
        self._mods_download_deadline = time.time() + 20.0
        self.mods_warning["progress"] = (len(ids) - len(real_ids), len(ids), [])
        for mid in real_ids:
            self.client.request_mod(mid)

    def _update_mods_download(self):
        if self.client is None: return
        if self.mods_warning is None: return
        _pending = getattr(self, "_mods_pending_ids", set())
        _deadline = getattr(self, "_mods_download_deadline", 0.0)
        _downloaded = getattr(self.client, "_mods_downloaded", set())
        _mod_errors = getattr(self.client, "mod_errors", [])
        _errors = [e for e in _mod_errors if e[0] in _pending]
        # убираем из pending уже скачанные / ошибочные / уже лежащие в addon/
        for mid in list(_pending):
            mdir = os.path.join("addon", mid)
            if mid in _downloaded or (os.path.isdir(mdir) and os.path.isfile(os.path.join(mdir, "manifest.json"))):
                _pending.discard(mid)
            elif any(e[0] == mid for e in _errors):
                _pending.discard(mid)
                if not hasattr(self, "_mods_errors"): self._mods_errors = []
                self._mods_errors.append((mid, "error"))
        total = len(self.mods_warning.get("mods", []))
        done = total - len(_pending)
        _err_list = getattr(self, "_mods_errors", [])
        self.mods_warning["progress"] = (done, total, _err_list)
        if not _pending:
            if _err_list:
                self.mods_warning["status"] = f"Ошибки: {len(_err_list)} модов не загружено"
            else:
                self.mods_warning["status"] = "Готово. Вход..."
                self.client.send_mods_ack()
                self.mods_warning = None
            return
        if time.time() > _deadline:
            self.mods_warning["status"] = "Таймаут. Повтор через 3 сек..."
            self._mods_download_deadline = time.time() + 3.0
            for mid in list(_pending):
                self.client.request_mod(mid)

    def _draw_server_settings(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((240, 250, 240))
        self.screen.blit(overlay, (0, 0))
        title = "НАСТРОЙКИ СОЛО" if self.solo_mode else "НАСТРОЙКИ СЕРВЕРА"
        self.screen.blit(self.big.render(title, True, (30, 70, 30)),
                         self.big.render(title, True, (30, 70, 30)).get_rect(center=(WIDTH // 2, 60)))
        cur = self._my_stage()
        t = self.font.render(f"Сюжет: {STAGE_NAMES.get(cur, '10 волн')}   Побед: {self._my_wins()}", True, (80, 20, 20))
        self.screen.blit(t, t.get_rect(center=(WIDTH // 2, 100)))
        self.screen.blit(self.font.render("Режим игры:", True, (30, 50, 30)), (WIDTH//2 - 200, HEIGHT//2 - 170))
        mouse = pygame.mouse.get_pos()
        for _, btn in self.sv_mode_buttons: btn.draw(self.screen, self.font, mouse)
        self.screen.blit(self.font.render("Сложность:", True, (30, 50, 30)), (WIDTH//2 - 200, HEIGHT//2 - 60))
        for _, btn in self.sv_diff_buttons: btn.draw(self.screen, self.font, mouse)
        self.btn_sv_cheats.draw(self.screen, self.font, mouse)
        self.btn_sv_mods.draw(self.screen, self.font, mouse)
        hint = self.small.render("50 волн → босс-раш, ПвП, сложный. 100 волн → Запретное знание.", True, (100, 100, 100))
        self.screen.blit(hint, hint.get_rect(center=(WIDTH // 2, HEIGHT//2 + 180)))
        self.btn_sv_back.draw(self.screen, self.font, mouse)
        self.btn_sv_start.draw(self.screen, self.font, mouse)

    def _draw_servers(self):
        self.screen.blit(self.big.render("Локальные серверы", True, (30, 70, 30)), (60, 40))
        cur = self._my_stage()
        s = self.small.render(f"Твой сюжет: {STAGE_NAMES.get(cur, '10 волн')}", True, (80, 20, 20))
        self.screen.blit(s, (WIDTH - 320, 60))
        for i, sv in enumerate(self.servers):
            ip, port, name = sv[0], sv[1], sv[2]; stage = sv[3] if len(sv) > 3 else 0
            r = pygame.Rect(80, 120 + i * 60, WIDTH - 160, 50)
            can = cur >= stage
            pygame.draw.rect(self.screen, (250, 255, 250) if can else (240, 220, 220), r, border_radius=8)
            pygame.draw.rect(self.screen, (100, 160, 100) if can else (180, 100, 100), r, 2, border_radius=8)
            label = f"{name}  —  {ip}:{port}   [{STAGE_NAMES.get(stage, '10 волн')}]" + ("" if can else "  🔒")
            self.screen.blit(self.font.render(label, True, (30, 50, 30)), (r.x + 16, r.y + 12))
        if self.status: self.screen.blit(self.small.render(self.status, True, (100, 60, 10)), (80, HEIGHT - 150))
        mouse = pygame.mouse.get_pos()
        self.btn_plus.draw(self.screen, self.font, mouse)
        self.btn_back.draw(self.screen, self.font, mouse)

        # === ПРИНУДИТЕЛЬНОЕ ПОДКЛЮЧЕНИЕ ===
        _fr = pygame.Rect(WIDTH // 2 - 200, HEIGHT - 190, 400, 60)
        _fh = _fr.collidepoint(mouse)
        if self.force_connecting:
            _fbg = (120, 80, 40)
            _ftxt = "Сканирую..."
        else:
            _fbg = (60, 140, 90) if _fh else (40, 100, 70)
            _ftxt = "ПРИНУДИТЕЛЬНО ПОДКЛЮЧИТЬСЯ"
        pygame.draw.rect(self.screen, _fbg, _fr, border_radius=10)
        pygame.draw.rect(self.screen, (220, 255, 220), _fr, 3, border_radius=10)
        _ft = self.font.render(_ftxt, True, (255, 255, 255))
        self.screen.blit(_ft, _ft.get_rect(center=_fr.center))
        self._btn_force_connect = _fr


        """Сканирует сеть и подключается к первому ответившему серверу."""
        if self.force_connecting:
            return
        self.force_connecting = True
        self.status = "Принудительное подключение: сканирую сеть..."
        threading.Thread(target=self._force_connect_worker, daemon=True).start()


    def _force_connect(self):
        """Сканирует сеть и подключается к первому ответившему серверу."""
        if self.force_connecting:
            return
        self.force_connecting = True
        self.status = "Принудительное подключение: сканирую сеть..."
        threading.Thread(target=self._force_connect_worker, daemon=True).start()

    def _force_connect_worker(self):
        try:
            found = discover(timeout=2.0)
            if not found:
                self.status = "Сервер не найден (broadcast не дошёл)"
                self.force_connecting = False
                return
            real = [s for s in found if s[2] != "__solo__"]
            if not real:
                self.status = "Найден только соло-сервер"
                self.force_connecting = False
                return
            ip, port, name = real[0][0], real[0][1], real[0][2]
            self.status = f"Подключаюсь к {name} ({ip}:{port})..."
            self._connect(ip, port)
        except Exception as e:
            self.status = f"Ошибка подключения: {e}"
        finally:
            self.force_connecting = False

    def _draw_game(self):
        me = self.players.get(self.my_id)
        if me and not me.get("dead") and self.local_init:
            tx = self.local_x - WIDTH / 2; ty = self.local_y - HEIGHT / 2
        elif me:
            tx = me["x"] - WIDTH / 2; ty = me["y"] - HEIGHT / 2
        else: tx, ty = self.camera
        self.camera[0] += (tx - self.camera[0]) * 0.35
        self.camera[1] += (ty - self.camera[1]) * 0.35
        self.camera[0] = max(0, min(self.map_w - WIDTH, self.camera[0]))
        self.camera[1] = max(0, min(self.map_h - HEIGHT, self.camera[1]))
        cx, cy = self.camera
        step = BARRICADE_GRID
        x0 = int(cx // step) * step; y0 = int(cy // step) * step
        for gx in range(x0, int(cx + WIDTH) + step, step):
            sx = gx - cx; pygame.draw.line(self.screen, (170, 220, 170), (sx, 0), (sx, HEIGHT))
        for gy in range(y0, int(cy + HEIGHT) + step, step):
            sy = gy - cy; pygame.draw.line(self.screen, (170, 220, 170), (0, sy), (WIDTH, sy))
        pygame.draw.rect(self.screen, (60, 120, 60), (0 - cx, 0 - cy, self.map_w, self.map_h), 6)
        now_server = time.time() + self.server_time_offset
        _me_w = me.get("weapon", "base") if me else "base"
        _me_ws = WEAPON_STATS.get(_me_w, {})
        _is_tool = bool(_me_ws.get("hammer") or _me_ws.get("wrench"))
        _show_preview = self.show_barricade_preview and (self.barricade_mode or _is_tool)
        if me and not me.get("dead") and _show_preview and self.local_init:
            mgx = int(self.local_x // BARRICADE_GRID); mgy = int(self.local_y // BARRICADE_GRID)
            psurf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            cells = {(b.get("gx"), b.get("gy")) for b in self.buildings}
            for dx in range(-BARRICADE_RANGE, BARRICADE_RANGE + 1):
                for dy in range(-BARRICADE_RANGE, BARRICADE_RANGE + 1):
                    gx_ = mgx + dx; gy_ = mgy + dy
                    if gx_ < 0 or gy_ < 0: continue
                    if (gx_+1)*BARRICADE_GRID > self.map_w or (gy_+1)*BARRICADE_GRID > self.map_h: continue
                    occ = (gx_, gy_) in cells
                    cxx = gx_ * BARRICADE_GRID + BARRICADE_GRID / 2
                    cyy = gy_ * BARRICADE_GRID + BARRICADE_GRID / 2
                    tc = math.hypot(cxx - self.local_x, cyy - self.local_y) < PLAYER_R + BARRICADE_GRID / 2
                    col = (220, 60, 60) if (occ or tc) else (60, 220, 60)
                    r = pygame.Rect(int(cxx - cx - BARRICADE_GRID / 2), int(cyy - cy - BARRICADE_GRID / 2),
                                     BARRICADE_GRID, BARRICADE_GRID)
                    pygame.draw.rect(psurf, (*col, 40), r); pygame.draw.rect(psurf, (*col, 180), r, 2)
            self.screen.blit(psurf, (0, 0))
        for pd in self.puddles:
            sx = pd["x"] - cx; sy = pd["y"] - cy
            r = int(pd["r"])
            s = pygame.Surface((r*2, r*2), pygame.SRCALPHA)
            pygame.draw.circle(s, (60, 180, 60, 90), (r, r), r)
            pygame.draw.circle(s, (40, 120, 40, 220), (r, r), r, 3)
            self.screen.blit(s, (int(sx - r), int(sy - r)))
        for cr in self.crates:
            sx = cr["x"] - cx; sy = cr["y"] - cy
            if not (-100 < sx < WIDTH + 100 and -100 < sy < HEIGHT + 100): continue
            col = tuple(cr["color"])
            pygame.draw.rect(self.screen, col, (int(sx-CRATE_R), int(sy-CRATE_R), CRATE_R*2, CRATE_R*2), border_radius=6)
            pygame.draw.rect(self.screen, (20,20,25), (int(sx-CRATE_R), int(sy-CRATE_R), CRATE_R*2, CRATE_R*2), 4, border_radius=6)
        for b in self.buildings:
            half = BARRICADE_GRID / 2
            sx = b["x"] - cx - half; sy = b["y"] - cy - half
            size = BARRICADE_GRID; hp = max(0, b["hp"]) / max(1, b["max_hp"])
            kind = b.get("kind")
            if kind == BUILD_BARRICADE:
                col = (130,95,55) if hp > 0.66 else ((170,120,60) if hp > 0.33 else (200,80,60))
                rect = pygame.Rect(int(sx), int(sy), size, size)
                pygame.draw.rect(self.screen, col, rect); pygame.draw.rect(self.screen, (40,30,20), rect, 3)
                pygame.draw.rect(self.screen, (40,30,20), (sx, sy-8, size, 4))
                pygame.draw.rect(self.screen, (60,200,60), (sx, sy-8, size*hp, 4))
            elif kind == BUILD_DOOR:
                # Дверь: коричневая рама + светлая середина
                rect = pygame.Rect(int(sx), int(sy), size, size)
                pygame.draw.rect(self.screen, (120, 80, 50), rect, border_radius=4)
                pygame.draw.rect(self.screen, (60, 40, 20), rect, 3, border_radius=4)
                inner = pygame.Rect(int(sx)+6, int(sy)+6, size-12, size-12)
                pygame.draw.rect(self.screen, (200, 170, 120), inner, border_radius=3)
                pygame.draw.rect(self.screen, (60, 40, 20), inner, 2, border_radius=3)
                # Ручка
                pygame.draw.circle(self.screen, (255, 220, 100),
                                   (int(sx) + size - 10, int(sy) + size // 2), 3)
                # Полоска HP сверху
                pygame.draw.rect(self.screen, (40,30,20), (sx, sy-8, size, 4))
                pygame.draw.rect(self.screen, (60,200,60), (sx, sy-8, size*hp, 4))
            else:
                if kind == BUILD_TURRET: base = (120,120,130)
                elif kind == BUILD_FIRE_TURRET: base = (150,80,40)
                elif kind == BUILD_REPAIR_TURRET: base = (60,140,80)
                elif kind == BUILD_ELECTRIC_TURRET: base = (80,140,220)
                else: base = (100,100,100)
                rect = pygame.Rect(int(sx), int(sy), size, size)
                pygame.draw.rect(self.screen, base, rect, border_radius=6)
                pygame.draw.rect(self.screen, (40,40,50) if kind == BUILD_TURRET else (60,30,20), rect, 3, border_radius=6)
                cxt = b["x"] - cx; cyt = b["y"] - cy
                ang = b.get("angle", 0.0)
                ex = cxt + math.cos(ang) * (size // 2 + 4); ey = cyt + math.sin(ang) * (size // 2 + 4)
                pygame.draw.line(self.screen, (60,60,70), (cxt, cyt), (ex, ey), 8)
                pygame.draw.circle(self.screen,
                                   (255,140,30) if kind == BUILD_FIRE_TURRET
                                   else ((150,220,255) if kind == BUILD_ELECTRIC_TURRET else (180,200,240)),
                                   (int(ex), int(ey)), 6 if kind == BUILD_FIRE_TURRET else 5)
        for fi in self.forbidden_items:
            sx, sy = fi["x"] - cx, fi["y"] - cy
            t = time.time() * 3; r = FORBIDDEN_R + int(2 * math.sin(t))
            pygame.draw.circle(self.screen, (60,20,90), (int(sx), int(sy)), r)
            pygame.draw.circle(self.screen, (180,80,240), (int(sx), int(sy)), r, 3)
        for m in self.meteors:
            sx, sy = m["x"] - cx, m["y"] - cy
            pygame.draw.circle(self.screen, (30,20,40), (int(sx), int(sy)), 100)
            pygame.draw.circle(self.screen, (255,120,40), (int(sx), int(sy)), 100, 4)
            pygame.draw.circle(self.screen, (255,200,60), (int(sx), int(sy)), 120, 3)
        for tb in self.turret_bullets:
            sx, sy = tb["x"] - cx, tb["y"] - cy
            if tb.get("fire"):
                pygame.draw.circle(self.screen, (255,120,40), (int(sx), int(sy)), 12)
                pygame.draw.circle(self.screen, (255,240,120), (int(sx), int(sy)), 6)
            else:
                pygame.draw.circle(self.screen, (200,220,255), (int(sx), int(sy)), 5)
        for sb in self.spitter_bullets:
            sx, sy = sb["x"] - cx, sb["y"] - cy
            pygame.draw.circle(self.screen, (200, 200, 60), (int(sx), int(sy)), int(sb["r"]))
            pygame.draw.circle(self.screen, (140, 140, 40), (int(sx), int(sy)), int(sb["r"]), 3)
        for z in self.zombies:
            zr = z.get("r", ZOMBIE_R)
            sx, sy = z["x"] - cx, z["y"] - cy
            if not (-zr-100 < sx < WIDTH + zr+100 and -zr-100 < sy < HEIGHT + zr+100): continue
            is_boss = z.get("boss", False); is_final = z.get("final", False)
            is_s50 = z.get("stage50", False); ch = z.get("charmed", False); shadow = z.get("shadow", False)
            is_golden = z.get("golden", False)
            kind = z.get("kind", "normal")
            if ch:
                if shadow: body, outline = (20, 20, 20), (80, 80, 80)
                else: body, outline = (255, 170, 210), (200, 60, 140)
            elif is_final: body, outline = (120,20,20), (255,220,60)
            elif is_s50: body, outline = (80,40,140), (255,220,60)
            elif is_boss: body, outline = (140,40,100), (255,100,255)
            elif is_golden: body, outline = (255, 215, 0), (180, 120, 0)
            elif kind in ZOMBIE_TYPES: body, outline = ZOMBIE_TYPES[kind]["color"], (30,60,30)
            else: body, outline = (70,140,70), (30,60,30)
            if not ch and not is_golden:
                if z.get("fire_until", 0) > now_server: body = (200,100,40)
                if z.get("frozen_until", 0) > now_server: body = (120,180,255)
            if is_s50 and z.get("dash_state") == "telegraph":
                pygame.draw.circle(self.screen, (255,60,60), (int(sx), int(sy)), zr + 20, 5)
            if is_golden:
                pygame.draw.circle(self.screen, (255, 245, 180), (int(sx), int(sy)), zr + 8, 4)
            pygame.draw.circle(self.screen, body, (int(sx), int(sy)), zr)
            pygame.draw.circle(self.screen, outline, (int(sx), int(sy)), zr,
                               6 if (is_final or is_s50 or is_golden) else (5 if is_boss else 3))
            eye_off = zr // 3; eye_r = max(5, zr // 8)
            eye_col = (200, 60, 200) if shadow else ((255,40,140) if ch else (255,40,40))
            pygame.draw.circle(self.screen, eye_col, (int(sx - eye_off), int(sy - eye_off // 2)), eye_r)
            pygame.draw.circle(self.screen, eye_col, (int(sx + eye_off), int(sy - eye_off // 2)), eye_r)
            bw = 400 if is_final else (300 if (is_s50 or is_boss) else 70)
            frac = max(0, z["hp"]) / max(1, z["max_hp"])
            bar_h = 10 if (is_boss or is_final or is_s50) else 6
            pygame.draw.rect(self.screen, (60,30,30), (sx - bw//2, sy - zr - 18, bw, bar_h))
            if shadow: hp_col = (100, 100, 100)
            elif ch: hp_col = (255,130,200)
            elif is_final: hp_col = (255,60,200)
            elif is_s50: hp_col = (180,100,255)
            elif is_boss: hp_col = (255,180,40)
            elif is_golden: hp_col = (255, 230, 80)
            else: hp_col = (220,60,60)
            pygame.draw.rect(self.screen, hp_col, (sx - bw//2, sy - zr - 18, int(bw * frac), bar_h))
        # Лазеры
        for pid, p in self.players.items():
            if p.get("dead"): continue
            wkey = p.get("weapon", "base")
            if wkey not in ("laser", "first_prism", "last_prism"): continue
            if p.get("laser_until", 0) <= now_server: continue
            px, py = (self.local_x, self.local_y) if (pid == self.my_id and self.local_init) else (p["x"], p["y"])
            sx, sy = px - cx, py - cy
            ang = p.get("laser_angle", p.get("angle", 0))
            if wkey == "last_prism":
                rng = max(self.map_w, self.map_h) * 2
                col_outer, col_inner = (255, 255, 255), (255, 255, 240)
                w = LASER_WIDTH + 10
            elif wkey == "first_prism":
                rng = LASER_RANGE
                col_outer, col_inner = (255, 255, 255), (255, 255, 200)
                w = LASER_WIDTH
            else:
                rng = LASER_RANGE
                col_outer, col_inner = (255, 0, 0), (255, 200, 200)
                w = LASER_WIDTH
            ex = sx + math.cos(ang) * rng; ey = sy + math.sin(ang) * rng
            pygame.draw.line(self.screen, col_outer, (sx, sy), (ex, ey), w)
            pygame.draw.line(self.screen, col_inner, (sx, sy), (ex, ey), max(2, w // 3))
        for b in self.bullets:
            sx, sy = b["x"] - cx, b["y"] - cy
            wkey = b.get("weapon", "base")
            if wkey == "star":
                col = (255,240,120) if b.get("special") else (255,200,60)
                r = 18 if b.get("special") else 12
                pts = []
                for k in range(16):
                    ang = k * math.pi / 8; rad = r if k % 2 == 0 else r * 0.4
                    pts.append((sx + math.cos(ang) * rad, sy + math.sin(ang) * rad))
                pygame.draw.polygon(self.screen, col, pts); continue
            if wkey == "true_star":
                col = (255, 250, 180)
                r = 24
                pts = []
                for k in range(16):
                    ang = k * math.pi / 8; rad = r if k % 2 == 0 else r * 0.4
                    pts.append((sx + math.cos(ang) * rad, sy + math.sin(ang) * rad))
                pygame.draw.polygon(self.screen, col, pts)
                pygame.draw.polygon(self.screen, (255, 255, 255), pts, 2)
                continue
            if wkey == "hexagon":
                pts = []
                for k in range(6):
                    ang = k * math.pi / 3
                    pts.append((sx + math.cos(ang) * 9, sy + math.sin(ang) * 9))
                pygame.draw.polygon(self.screen, (30, 30, 30), pts)
                pygame.draw.polygon(self.screen, (200, 200, 200), pts, 2); continue
            _ak = b.get("ammo_kind")
            if _ak:
                try:
                    _rd = MOD_API.ammo_renderers.get(_ak)
                    if _rd and _rd.get("sprite"):
                        _spr = _rd["sprite"]()
                        if _spr is not None:
                            _ang = math.atan2(b["vy"], b["vx"])
                            _rot = pygame.transform.rotate(_spr, -math.degrees(_ang))
                            s.blit(_rot, _rot.get_rect(center=(int(sx), int(sy))))
                            continue
                except Exception as _e:
                    print("[mods] ammo draw error:", _e)
            col = (255,240,120)
            if wkey == "shotgun": col = (240,200,100)
            elif wkey == "smg": col = (200,255,120)
            elif wkey == "sniper": col = (180,220,255)
            elif wkey == "laser": col = (255,80,80)
            elif wkey == "first_prism": col = (255, 255, 255)
            elif wkey == "last_prism": col = (255, 255, 255)
            elif wkey == "plasma": col = (150,100,255)
            elif wkey == "stone": col = (170,170,180)
            elif wkey == "meteor": col = (180,100,255)
            elif wkey == "charm_staff": col = (255,150,220)
            if b.get("firedoom"): col = (255,140,30)
            pygame.draw.circle(self.screen, col, (int(sx), int(sy)), 5)
        for pid, p in self.players.items():
            if p.get("dead"): continue
            if p.get("wanish") and pid != self.my_id: continue
            px, py = (self.local_x, self.local_y) if (pid == self.my_id and self.local_init) else (p["x"], p["y"])
            sx, sy = px - cx, py - cy
            color = tuple(p.get("color", (200,100,100))); r = PLAYER_R
            if p.get("wanish"): color = tuple(min(255, c + 100) for c in color)
            if p.get("speed_until", 0) > now_server: pygame.draw.circle(self.screen, (255,240,100), (int(sx), int(sy)), r + 12, 4)
            if p.get("shoot_until", 0) > now_server: pygame.draw.circle(self.screen, (120,180,255), (int(sx), int(sy)), r + 20, 4)
            if p.get("firedoom_until", 0) > now_server: pygame.draw.circle(self.screen, (255,90,0), (int(sx), int(sy)), r + 28, 3)
            if p.get("crazy_until", 0) > now_server:
                pygame.draw.circle(self.screen, (255,60,200), (int(sx), int(sy)), r + 34, 4)
                pygame.draw.circle(self.screen, (255,200,255), (int(sx), int(sy)), r + 42, 2)
            if p.get("frozen_until", 0) > now_server:
                pygame.draw.circle(self.screen, (120,200,255), (int(sx), int(sy)), r + 6, 6)
            if p.get("weapon") == "shield":
                pygame.draw.circle(self.screen, (180,200,240), (int(sx), int(sy)), r + 8, 6)
            a_ = p.get("angle", 0); wkey = p.get("weapon", "base")
            if wkey in ARSENAL: self._draw_weapon_in_hand(sx, sy, wkey, a_)
            pygame.draw.circle(self.screen, color, (int(sx), int(sy)), r)
            bright = sum(color) / 3
            outline = (30,30,30) if bright > 128 else (240,240,240)
            pygame.draw.circle(self.screen, outline, (int(sx), int(sy)), r, 3)
            hp = p.get("hp", 0); bw = 70
            pygame.draw.rect(self.screen, (80,80,80), (sx - bw//2, sy - r - 16, bw, 7))
            pygame.draw.rect(self.screen, (60,200,60), (sx - bw//2, sy - r - 16, int(bw * hp / MAX_HP), 7))
            cname = color_name_of(tuple(p.get("color", (200,100,100))))
            if cname:
                nm = self.tiny.render(cname, True, (20,20,20))
                self.screen.blit(nm, nm.get_rect(center=(sx, sy - r - 42)))
            lvl = p.get("level", 0)
            self.screen.blit(self.small.render(f"Lv{lvl}", True, (20,20,20)),
                             self.small.render(f"Lv{lvl}", True, (20,20,20)).get_rect(center=(sx, sy - r - 28)))
            if p.get("wanish"):
                w = self.small.render("WANISH", True, (200, 200, 255))
                self.screen.blit(w, w.get_rect(center=(sx, sy - r - 56)))
        for pid, p in self.players.items():
            if p.get("dead"): continue
            wkey = p.get("weapon")
            if wkey not in ("sword", "cursed_sword", "charm_sword"): continue
            until = p.get("melee_until", 0)
            if until <= now_server: continue
            elapsed = max(0.0, 0.25 - (until - now_server)); t = elapsed / 0.25
            px, py = (self.local_x, self.local_y) if (pid == self.my_id and self.local_init) else (p["x"], p["y"])
            sx, sy = px - cx, py - cy
            a = p.get("melee_angle", 0); arc_half = 0.55
            start = a - arc_half; end = start + arc_half * 2 * t
            pts = []
            for k in range(13):
                ang = start + (end - start) * k / 12
                rr = PLAYER_R + 30
                pts.append((sx + math.cos(ang) * rr, sy + math.sin(ang) * rr))
            if len(pts) >= 2:
                if wkey == "sword": pygame.draw.lines(self.screen, (230,230,240), False, pts, 5)
                elif wkey == "charm_sword": pygame.draw.lines(self.screen, (255,150,220), False, pts, 6)
                else: pygame.draw.lines(self.screen, (200,100,240), False, pts, 6)
        for pop in self.popups:
            sx, sy = pop["x"] - cx, pop["y"] - cy - pop["t"] * 40
            alpha = max(0, 1 - pop["t"] / pop["life"])
            txt = self.small.render(str(pop["v"]), True, tuple(pop["color"]))
            txt.set_alpha(int(255 * alpha))
            self.screen.blit(txt, txt.get_rect(center=(sx, sy)))
        # Кнопка старта волны
        if self.wave_button_active and not self.victory:
            bx = self.wave_button_x - cx; by = self.wave_button_y - cy
            if -200 < bx < WIDTH + 200 and -200 < by < HEIGHT + 200:
                pulse = int(6 + 4 * math.sin(time.time() * 4))
                pygame.draw.circle(self.screen, (40, 90, 40), (int(bx), int(by)), WAVE_BUTTON_R + 8)
                pygame.draw.circle(self.screen, (70, 180, 70), (int(bx), int(by)), WAVE_BUTTON_R)
                pygame.draw.circle(self.screen, (240, 240, 200), (int(bx), int(by)), WAVE_BUTTON_R + pulse, 4)
                pygame.draw.circle(self.screen, (255, 255, 255), (int(bx), int(by)), WAVE_BUTTON_R, 3)
        # Миникарта — рисуется в первом слое (чёткая).
        self._draw_minimap(me, cx, cy)


    def _draw_drop_menu(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,200))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(WIDTH//2 - 500, HEIGHT//2 - 250, 1000, 500)
        pygame.draw.rect(self.screen, (30, 30, 45), panel, border_radius=14)
        pygame.draw.rect(self.screen, (200, 200, 220), panel, 3, border_radius=14)
        self.screen.blit(self.big.render("ВЫКИНУТЬ", True, (255, 180, 120)),
                         self.big.render("ВЫКИНУТЬ", True, (255, 180, 120)).get_rect(center=(panel.centerx, panel.y + 30)))
        me = self.players.get(self.my_id)
        if me:
            weapons = [w for w in me.get("owned_weapons", []) if w != "base"]
            self.screen.blit(self.small.render("Оружие (клик — выкинуть):",
                                                 True, (240, 200, 160)), (panel.x + 30, panel.y + 42))
            for i, wkey in enumerate(weapons):
                col = i % 5; row = i // 5
                r = pygame.Rect(panel.x + 30 + col * 90, panel.y + 60 + row * 90, 80, 80)
                pygame.draw.rect(self.screen, (70, 70, 100), r, border_radius=6)
                pygame.draw.rect(self.screen, (200, 200, 220), r, 2, border_radius=6)
                self._draw_weapon_icon(wkey, r)
                lbl = ARSENAL.get(wkey, {}).get("label", wkey)[:12]
                t = self.tiny.render(lbl, True, (220, 220, 240))
                self.screen.blit(t, t.get_rect(center=(r.centerx, r.bottom + 10)))
            self.screen.blit(self.small.render("Расходники (клик — минус 1 шт):",
                                                 True, (240, 200, 160)), (panel.x + 540, panel.y + 42))
            for i, bkey in enumerate(SHOP_BUFFS.keys()):
                r = pygame.Rect(panel.x + 540, panel.y + 60 + i * 70, 440, 60)
                have = me.get("inventory", {}).get(bkey, 0)
                pygame.draw.rect(self.screen, (70, 70, 100), r, border_radius=6)
                pygame.draw.rect(self.screen, (200, 200, 220), r, 2, border_radius=6)
                label = f"{SHOP_BUFFS[bkey]['label']}  ({have} шт)"
                t = self.font.render(label, True, (240, 240, 240))
                self.screen.blit(t, (r.x + 16, r.y + 18))
        close_rect = pygame.Rect(panel.centerx - 100, panel.bottom - 70, 200, 50)
        pygame.draw.rect(self.screen, (140,50,50), close_rect, border_radius=8)
        pygame.draw.rect(self.screen, (220,220,220), close_rect, 2, border_radius=8)
        ct = self.font.render("Закрыть", True, (255,255,255))
        self.screen.blit(ct, ct.get_rect(center=close_rect.center))

    def _draw_achievement_popup(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,210))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 400, HEIGHT // 2 - 180, 800, 360)
        pygame.draw.rect(self.screen, (25,40,25), panel, border_radius=16)
        pygame.draw.rect(self.screen, (240,200,60), panel, 4, border_radius=16)
        self.screen.blit(self.big.render("ДОСТИЖЕНИЕ ПОЛУЧЕНО!", True, (255,220,60)),
                         self.big.render("ДОСТИЖЕНИЕ ПОЛУЧЕНО!", True, (255,220,60)).get_rect(center=(WIDTH // 2, panel.y + 50)))
        key = self.achievement_popup
        self.screen.blit(self.huge.render(ACHIEVEMENT_NAMES.get(key, key), True, (255,255,255)),
                         self.huge.render(ACHIEVEMENT_NAMES.get(key, key), True, (255,255,255)).get_rect(center=(WIDTH // 2, panel.y + 130)))
        self.screen.blit(self.font.render(ACHIEVEMENT_DESCS.get(key, ""), True, (200,220,200)),
                         self.font.render(ACHIEVEMENT_DESCS.get(key, ""), True, (200,220,200)).get_rect(center=(WIDTH // 2, panel.y + 200)))
        self.screen.blit(self.font.render(f"Эффект: {ACHIEVEMENT_EFFECTS.get(key, '')}", True, (255,200,120)),
                         self.font.render(f"Эффект: {ACHIEVEMENT_EFFECTS.get(key, '')}", True, (255,200,120)).get_rect(center=(WIDTH // 2, panel.y + 240)))
        mouse = pygame.mouse.get_pos()
        self.achievement_popup_close.rect = pygame.Rect(WIDTH // 2 - 100, panel.bottom - 70, 200, 55)
        self.achievement_popup_close.draw(self.screen, self.font, mouse)

    def _draw_unlock_popup(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,210))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 400, HEIGHT // 2 - 220, 800, 440)
        pygame.draw.rect(self.screen, (25,25,40), panel, border_radius=16)
        pygame.draw.rect(self.screen, (240,200,60), panel, 4, border_radius=16)
        self.screen.blit(self.big.render("РАЗБЛОКИРОВАНО!", True, (255,220,60)),
                         self.big.render("РАЗБЛОКИРОВАНО!", True, (255,220,60)).get_rect(center=(WIDTH // 2, panel.y + 60)))
        y = panel.y + 130
        for label, ok in self.unlock_popup.get("items", []):
            self.screen.blit(self.font.render(f"{'✓' if ok else '—'}  {label}", True, (240,240,240)), (panel.x + 80, y)); y += 44
        mouse = pygame.mouse.get_pos()
        self.unlock_popup_close.rect = pygame.Rect(WIDTH // 2 - 100, panel.bottom - 70, 200, 55)
        self.unlock_popup_close.draw(self.screen, self.font, mouse)

    def _draw_weapon_desc_popup(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 400, HEIGHT // 2 - 220, 800, 440)
        pygame.draw.rect(self.screen, (30, 30, 45), panel, border_radius=16)
        pygame.draw.rect(self.screen, (200, 200, 240), panel, 3, border_radius=16)
        key = self.weapon_desc_popup
        info = ARSENAL.get(key, {})
        label = info.get("label", key)
        price = info.get("price", 0)
        desc = WEAPON_DESCS.get(key, "Описание отсутствует.")
        # заголовок
        t = self.big.render(label, True, (255, 240, 180))
        self.screen.blit(t, t.get_rect(center=(panel.centerx, panel.y + 50)))
        # цена
        pt = self.font.render(f"Цена: {price} монет", True, (255, 220, 120))
        self.screen.blit(pt, pt.get_rect(center=(panel.centerx, panel.y + 100)))
        # иконка слева
        icon_r = pygame.Rect(panel.x + 40, panel.y + 140, 140, 140)
        pygame.draw.rect(self.screen, (50, 50, 70), icon_r, border_radius=10)
        pygame.draw.rect(self.screen, (180, 180, 220), icon_r, 2, border_radius=10)
        self._draw_weapon_icon(key, icon_r)
        # описание справа
        desc_rect = pygame.Rect(panel.x + 200, panel.y + 140, panel.w - 240, panel.h - 180)
        words = desc.split()
        lines = []; cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if self.font.size(test)[0] <= desc_rect.width:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        y = desc_rect.y
        for line in lines[:14]:
            self.screen.blit(self.font.render(line, True, (230, 230, 240)),
                             (desc_rect.x, y))
            y += 28
        # крестик
        close_btn = pygame.Rect(panel.right - 60, panel.top + 16, 44, 44)
        pygame.draw.rect(self.screen, (140, 50, 50), close_btn, border_radius=8)
        pygame.draw.rect(self.screen, (220, 220, 220), close_btn, 2, border_radius=8)
        ct = self.font.render("✕", True, (255, 255, 255))
        self.screen.blit(ct, ct.get_rect(center=close_btn.center))
        # подсказка
        hint = self.small.render("Тапни вне окна, чтобы закрыть", True, (160, 160, 180))
        self.screen.blit(hint, hint.get_rect(center=(panel.centerx, panel.bottom - 24)))

    def _draw_slot_picker(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,200))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 300, HEIGHT // 2 - 130, 600, 300)
        pygame.draw.rect(self.screen, (30,30,45), panel, border_radius=14)
        pygame.draw.rect(self.screen, (180,180,220), panel, 3, border_radius=14)
        self.screen.blit(self.big.render("СЛОТ", True, (255,220,120)),
                         self.big.render("СЛОТ", True, (255,220,120)).get_rect(center=(WIDTH // 2, HEIGHT // 2 - 95)))
        info = ARSENAL.get(self.slot_picker, {})
        self.screen.blit(self.font.render(info.get("label", ""), True, (220,220,240)),
                         self.font.render(info.get("label", ""), True, (220,220,240)).get_rect(center=(WIDTH // 2, HEIGHT // 2 - 55)))
        me = self.players.get(self.my_id)
        slots = me.get("weapon_slots", [None]*MAX_WEAPON_SLOTS) if me else [None]*MAX_WEAPON_SLOTS
        mouse = pygame.mouse.get_pos()
        for i in range(MAX_WEAPON_SLOTS):
            r = pygame.Rect(WIDTH // 2 - 250 + i * 100, HEIGHT // 2 - 20, 90, 100)
            base = (60,60,90); cur = slots[i]
            if cur == self.slot_picker: base = (200,160,40)
            elif cur is not None: base = (90,60,60)
            c = tuple(min(255, v + 30) for v in base) if r.collidepoint(mouse) else base
            pygame.draw.rect(self.screen, c, r, border_radius=8)
            pygame.draw.rect(self.screen, (200,200,220), r, 2, border_radius=8)
            self.screen.blit(self.huge.render(str(i+1), True, (240,240,240)),
                             self.huge.render(str(i+1), True, (240,240,240)).get_rect(center=(r.centerx, r.centery - 10)))
        close_rect = pygame.Rect(WIDTH // 2 - 100, HEIGHT // 2 + 110, 200, 50)
        pygame.draw.rect(self.screen, (140,50,50), close_rect, border_radius=8)
        pygame.draw.rect(self.screen, (220,220,220), close_rect, 2, border_radius=8)
        self.screen.blit(self.font.render("Отмена", True, (255,255,255)),
                         self.font.render("Отмена", True, (255,255,255)).get_rect(center=close_rect.center))

    def _draw_crate_popup(self, pop):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,200))
        self.screen.blit(overlay, (0, 0))
        pw = 600; ph = 400; px = WIDTH // 2 - pw // 2; py = HEIGHT // 2 - ph // 2
        panel = pygame.Rect(px, py, pw, ph)
        pygame.draw.rect(self.screen, (30,30,40), panel, border_radius=16)
        color = tuple(pop["color"]); pygame.draw.rect(self.screen, color, panel, 4, border_radius=16)
        title = CRATE_RARITY_NAMES.get(pop["rarity"], "ЯЩИК")
        self.screen.blit(self.big.render(title, True, color),
                         self.big.render(title, True, color).get_rect(center=(WIDTH // 2, py + 50)))
        y = py + 120
        if pop["buffs"]:
            self.screen.blit(self.font.render("Бафы:", True, (240,240,240)), (px + 40, y)); y += 30
            from collections import Counter
            for bkey, bcnt in Counter(pop["buffs"]).items():
                label = SHOP_BUFFS.get(bkey, {}).get("label", bkey)
                self.screen.blit(self.font.render(f"  • {label} × {bcnt}", True, (200,220,200)), (px + 60, y)); y += 28
        self.screen.blit(self.font.render(f"Монеты: +{pop['coins']}", True, (255,220,60)), (px + 40, py + ph - 120))
        self.screen.blit(self.font.render(f"Опыт: +{pop['xp']}", True, (120,200,255)), (px + 40, py + ph - 80))
        self.screen.blit(self.small.render("Тапни, чтобы закрыть", True, (180,180,180)),
                         self.small.render("Тапни, чтобы закрыть", True, (180,180,180)).get_rect(center=(WIDTH // 2, py + ph - 35)))

    def _draw_minimap(self, me, cx, cy):
        mm_size = 200; mm_x = 20; mm_y = HEIGHT // 2 - mm_size // 2
        scale = mm_size / self.map_w
        bg = pygame.Surface((mm_size, mm_size), pygame.SRCALPHA); bg.fill((30,60,30,210))
        self.screen.blit(bg, (mm_x, mm_y))
        pygame.draw.rect(self.screen, (200,200,220), (mm_x, mm_y, mm_size, mm_size), 2, border_radius=6)
        for b in self.buildings:
            half = BARRICADE_GRID / 2
            bx = mm_x + int((b["x"] - half) * scale); by = mm_y + int((b["y"] - half) * scale)
            bs = max(2, int(BARRICADE_GRID * scale))
            col = (170,120,60)
            if b.get("kind") == BUILD_TURRET: col = (140,140,150)
            elif b.get("kind") == BUILD_FIRE_TURRET: col = (200,100,40)
            elif b.get("kind") == BUILD_ELECTRIC_TURRET: col = (80,140,220)
            elif b.get("kind") == BUILD_REPAIR_TURRET: col = (60,140,80)
            elif b.get("kind") == BUILD_DOOR: col = (200, 170, 120)
            elif b.get("kind") == BUILD_HAMMER: continue  # молоток не рисуем
            pygame.draw.rect(self.screen, col, (bx, by, bs, bs))
        for cr in self.crates:
            zx = mm_x + int(cr["x"] * scale); zy = mm_y + int(cr["y"] * scale)
            pygame.draw.rect(self.screen, tuple(cr["color"]), (zx-3, zy-3, 6, 6))
        if self.wave_button_active and not self.victory:
            wx = mm_x + int(self.wave_button_x * scale); wy = mm_y + int(self.wave_button_y * scale)
            pygame.draw.circle(self.screen, (60, 200, 60), (wx, wy), 6)
            pygame.draw.circle(self.screen, (255, 255, 255), (wx, wy), 6, 2)
        # кристалл на миникарте
        if (self.host is not None and self.host.mode == MODE_CRYSTAL
                and getattr(self.host, "crystal", None) is not None):
            _c = self.host.crystal
            _cx_mm = mm_x + int(_c["x"] * scale)
            _cy_mm = mm_y + int(_c["y"] * scale)
            pygame.draw.circle(self.screen, (60, 180, 240), (_cx_mm, _cy_mm), 6)
            pygame.draw.circle(self.screen, (200, 240, 255), (_cx_mm, _cy_mm), 6, 2)

        for z in self.zombies:
            zx = mm_x + int(z["x"] * scale); zy = mm_y + int(z["y"] * scale)
            if z.get("shadow"): pygame.draw.circle(self.screen, (60,60,60), (zx, zy), 3)
            elif z.get("charmed"): pygame.draw.circle(self.screen, (255,150,220), (zx, zy), 3)
            elif z.get("final"): pygame.draw.circle(self.screen, (255,60,200), (zx, zy), 6)
            elif z.get("stage50"): pygame.draw.circle(self.screen, (180,100,255), (zx, zy), 5)
            elif z.get("boss"): pygame.draw.circle(self.screen, (255,100,255), (zx, zy), 4)
            elif z.get("golden"): pygame.draw.circle(self.screen, (255, 215, 0), (zx, zy), 5)
            else: pygame.draw.circle(self.screen, (220,40,40), (zx, zy), 2)
        for pid, p in self.players.items():
            if p.get("dead"): continue
            if p.get("wanish") and pid != self.my_id: continue
            px, py = (self.local_x, self.local_y) if (pid == self.my_id and self.local_init) else (p["x"], p["y"])
            px_ = mm_x + int(px * scale); py_ = mm_y + int(py * scale)
            pygame.draw.circle(self.screen, tuple(p.get("color", (200,100,100))), (px_, py_), 4)
            pygame.draw.circle(self.screen, (0,0,0), (px_, py_), 4, 1)

    def _draw_hotbar(self, me):
        slots = me.get("weapon_slots", [None]*MAX_WEAPON_SLOTS)
        current = me.get("weapon", "base")
        inv = me.get("inventory", {})
        inv_keys = list(SHOP_BUFFS.keys())
        has_forbidden = self.forbidden_count_local > 0
        slot_w = self.hotbar_slot_size; gap = self.hotbar_gap
        build_slot = me.get("build_slot")
        n_w = MAX_WEAPON_SLOTS
        n_i = len(inv_keys) + (1 if has_forbidden else 0) + 1 + 1
        total_w = (n_w + n_i) * slot_w + (n_w + n_i - 1) * gap
        x0 = WIDTH // 2 - total_w // 2; y0 = HEIGHT - slot_w - 15
        self.hotbar_rects = []; self.hotbar_keys = []; self.hotbar_is_item = []
        x = x0
        for i in range(MAX_WEAPON_SLOTS):
            wkey = slots[i]; r = pygame.Rect(x, y0, slot_w, slot_w)
            self.hotbar_rects.append(r); self.hotbar_keys.append(wkey); self.hotbar_is_item.append(False)
            active = (wkey is not None and wkey == current)
            bg = (40,40,50) if wkey is None else ((90,90,130) if active else (60,60,80))
            border = (100,100,110) if wkey is None else ((255,220,120) if active else (200,200,220))
            pygame.draw.rect(self.screen, bg, r, border_radius=6)
            pygame.draw.rect(self.screen, border, r, 3 if active else 2, border_radius=6)
            self.screen.blit(self.tiny.render(str(i+1), True, (200,200,200)), (r.x + 4, r.y + 2))
            if wkey: self._draw_weapon_icon(wkey, r)
            x += slot_w + gap
        for key in inv_keys:
            r = pygame.Rect(x, y0, slot_w, slot_w)
            self.hotbar_rects.append(r); self.hotbar_keys.append(key); self.hotbar_is_item.append(True)
            cnt = inv.get(key, 0); has = cnt > 0
            bg = (80,60,100) if has else (40,40,50)
            border = (200,180,240) if has else (120,120,130)
            pygame.draw.rect(self.screen, bg, r, border_radius=6)
            pygame.draw.rect(self.screen, border, r, 2, border_radius=6)
            self._draw_buff_icon(key, r)
            if has:
                cnt_txt = self.tiny.render(str(cnt), True, (255,255,255))
                bgr = pygame.Rect(r.right - cnt_txt.get_width() - 6,
                                   r.bottom - cnt_txt.get_height() - 2,
                                   cnt_txt.get_width() + 4, cnt_txt.get_height() + 2)
                pygame.draw.rect(self.screen, (0,0,0), bgr, border_radius=3)
                self.screen.blit(cnt_txt, (bgr.x + 2, bgr.y + 1))
            x += slot_w + gap
        r = pygame.Rect(x, y0, slot_w, slot_w)
        self.hotbar_rects.append(r); self.hotbar_keys.append("__build__"); self.hotbar_is_item.append(True)
        has_build = build_slot is not None and me.get("build_inventory", {}).get(build_slot, 0) > 0
        bg = (90,80,50) if has_build else (40,40,50)
        border = (255,220,120) if has_build else (120,120,130)
        if self.barricade_mode: bg = (140,110,40); border = (255,240,60)
        pygame.draw.rect(self.screen, bg, r, border_radius=6)
        pygame.draw.rect(self.screen, border, r, 3 if self.barricade_mode else 2, border_radius=6)
        if build_slot: self._draw_build_icon(build_slot, r)
        else:
            self.screen.blit(self.tiny.render("СТР", True, (160, 160, 160)),
                             self.tiny.render("СТР", True, (160, 160, 160)).get_rect(center=r.center))
        x += slot_w + gap
        if has_forbidden:
            r = pygame.Rect(x, y0, slot_w, slot_w)
            self.hotbar_rects.append(r); self.hotbar_keys.append("forbidden"); self.hotbar_is_item.append(True)
            pygame.draw.rect(self.screen, (60,20,90), r, border_radius=6)
            pygame.draw.rect(self.screen, (220,140,255), r, 3, border_radius=6)
            pygame.draw.circle(self.screen, (180,80,240), (int(r.centerx), int(r.centery)), 18)
            cnt_txt = self.tiny.render(str(self.forbidden_count_local), True, (255,255,255))
            bgr = pygame.Rect(r.right - cnt_txt.get_width() - 6,
                               r.bottom - cnt_txt.get_height() - 2,
                               cnt_txt.get_width() + 4, cnt_txt.get_height() + 2)
            pygame.draw.rect(self.screen, (0,0,0), bgr, border_radius=3)
            self.screen.blit(cnt_txt, (bgr.x + 2, bgr.y + 1))
            x += slot_w + gap
        r = pygame.Rect(x, y0, slot_w, slot_w)
        self.hotbar_rects.append(r); self.hotbar_keys.append("__drop__"); self.hotbar_is_item.append(True)
        pygame.draw.rect(self.screen, (120, 60, 60), r, border_radius=6)
        pygame.draw.rect(self.screen, (220, 200, 200), r, 2, border_radius=6)
        x_txt = self.big.render("×", True, (255, 255, 255))
        self.screen.blit(x_txt, x_txt.get_rect(center=r.center))

    def _draw_shop(self):
        # Обновим максимальный скролл заранее — по текущей вкладке.
        cells_count = 0
        if self.shop_tab == "weapons":   cells_count = len(self._arsenal_visible())
        elif self.shop_tab == "buffs":   cells_count = len(SHOP_BUFFS)
        elif self.shop_tab == "build":   cells_count = len(BUILD_LABELS)
        elif self.shop_tab == "passives":cells_count = len(PASSIVES)
        total_h = cells_count * (self.SHOP_CELL_H + self.SHOP_GAP)
        window_top = self.SHOP_TOP_Y
        window_bottom = HEIGHT - 100
        window_h = max(1, window_bottom - window_top)
        self._shop_scroll_max = max(0, total_h - window_h)

        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((0,0,0,180))
        self.screen.blit(overlay, (0, 0))
        # Заголовок
        self.screen.blit(self.big.render("МАГАЗИН", True, (255,220,120)),
                         self.big.render("МАГАЗИН", True, (255,220,120)).get_rect(center=(WIDTH // 2, 40)))
        me = self.players.get(self.my_id); coins = me.get("coins", 0) if me else 0
        xpt = self.font.render(f"Монеты: {coins}   Побед: {self.server_wins}", True, (255,220,120))
        self.screen.blit(xpt, xpt.get_rect(center=(WIDTH // 2, 100)))
        # Вкладки
        if not hasattr(self, "shop_tab") or self.shop_tab is None:
            self.shop_tab = "weapons"
        tabs = [("weapons", "ОРУЖИЕ"), ("buffs", "БАФЫ"),
                ("build", "СТРОИТЕЛЬНОЕ"), ("passives", "ПАССИВКИ")]
        tw = 200; th = 44; tgap = 12
        total = len(tabs) * tw + (len(tabs) - 1) * tgap
        tx0 = WIDTH // 2 - total // 2; ty = 130
        mouse_t = pygame.mouse.get_pos()
        for i, (key, label) in enumerate(tabs):
            r = pygame.Rect(tx0 + i * (tw + tgap), ty, tw, th)
            active = (self.shop_tab == key)
            hov = r.collidepoint(mouse_t)
            bg = (200, 160, 40) if active else ((90, 90, 130) if hov else (60, 60, 90))
            pygame.draw.rect(self.screen, bg, r, border_radius=8)
            pygame.draw.rect(self.screen, (220, 220, 240) if active else (150, 150, 180),
                             r, 3 if active else 2, border_radius=8)
            t = self.font.render(label, True, (255, 255, 255))
            self.screen.blit(t, t.get_rect(center=r.center))

        # Ячейки рисуются прямо в self.screen; те, что выходят за границы
        # окна [SHOP_TOP_Y, HEIGHT-100], пропускаются внутри
        # _draw_shop_content_cells. Никаких чёрных полос.
        self._draw_shop_content_cells(window_h, 0)

        # Кнопка закрыть
        close_rect = pygame.Rect(WIDTH // 2 - 60, HEIGHT - 70, 120, 50)
        pygame.draw.rect(self.screen, (140,50,50), close_rect, border_radius=8)
        pygame.draw.rect(self.screen, (220,220,220), close_rect, 2, border_radius=8)
        self.screen.blit(self.font.render("Закрыть", True, (255,255,255)),
                         self.font.render("Закрыть", True, (255,255,255)).get_rect(center=close_rect.center))

    def _draw_shop_content(self, window_h):
        """Рисует ячейки со сдвигом _shop_scroll_cur."""
        self._draw_shop_content_cells(window_h)

    def _draw_shop_content_cells(self, window_h, y_offset):
        """Отрисовка ячеек текущей вкладки. Ячейки, вышедшие за пределы
        окна [SHOP_TOP_Y, HEIGHT-100], пропускаются."""
        me = self.players.get(self.my_id)
        coins = me.get("coins", 0) if me else 0
        items = []
        if self.shop_tab == "weapons":
            items = [(k, info) for (k, info) in self._arsenal_visible()]
        elif self.shop_tab == "buffs":
            items = list(SHOP_BUFFS.items())
        elif self.shop_tab == "build":
            items = [(k, {"label": v}) for k, v in BUILD_LABELS.items()]
        elif self.shop_tab == "passives":
            items = list(PASSIVES.items())

        cw = min(WIDTH - 200, self.SHOP_CELL_W)
        x0 = WIDTH // 2 - cw // 2
        top = self.SHOP_TOP_Y
        bot = HEIGHT - 100
        y0 = top - int(self._shop_scroll_cur)
        for idx, (key, info) in enumerate(items):
            y = y0 + idx * (self.SHOP_CELL_H + self.SHOP_GAP)
            if y + self.SHOP_CELL_H < top: continue
            if y > bot: break
            r = pygame.Rect(x0, y, cw, self.SHOP_CELL_H)
            self._draw_shop_cell(key, info, r, me, coins)

    def _draw_shop_cell(self, key, info, r, me, coins):
        """Отрисовка одной ячейки в зависимости от вкладки."""
        if self.shop_tab == "weapons":
            can = coins >= info["price"]
            owned = bool(me) and key in me.get("owned_weapons", [])
            locked = False
            if key == "hexagon":
                locked = not (self._my_wins() >= 10 or self.server_wins >= 10)
            elif key == "cursed_sword":
                locked = not (self._has_achievement(ACH_HORRORS_OF_PAST))
            if key == "last_prism": locked = not self.last_prism_unlocked
            if key == "true_star": locked = not self.true_star_unlocked
            bg = (60,90,60) if can and not owned and not locked else (50,50,60)
            if locked: bg = (50, 30, 30)
            pygame.draw.rect(self.screen, bg, r, border_radius=8)
            pygame.draw.rect(self.screen, (180,180,200), r, 2, border_radius=8)
            col_text = (140,220,140) if owned else ((240,240,240) if can and not locked else (160,160,160))
            self.screen.blit(self.font.render(info["label"], True, col_text), (r.x + 16, r.y + 10))
            sub = "КУПЛЕНО" if owned else (f"{info['price']} монет" if info["price"] else "СТАРТОВОЕ")
            sub_col = (140,220,140) if owned else ((255,220,120) if can and not locked else (160,160,160))
            if locked:
                sub = "Заблокировано"; sub_col = (200, 80, 80)
            self.screen.blit(self.small.render(sub, True, sub_col), (r.x + 16, r.y + 45))
            if owned:
                _sb = pygame.Rect(r.right - 110, r.bottom - 34, 96, 26)
                pygame.draw.rect(self.screen, (90,60,130), _sb, border_radius=5)
                pygame.draw.rect(self.screen, (220,200,255), _sb, 2, border_radius=5)
                self.screen.blit(self.small.render("СЛОТ", True, (255,255,255)),
                                 self.small.render("СЛОТ", True, (255,255,255)).get_rect(center=_sb.center))
            # === кнопка "?" в правом верхнем углу ===
            _qb = pygame.Rect(r.right - 40, r.top + 8, 30, 30)
            pygame.draw.rect(self.screen, (50, 80, 130), _qb, border_radius=15)
            pygame.draw.rect(self.screen, (200, 220, 255), _qb, 2, border_radius=15)
            _qt = self.font.render("?", True, (255, 255, 255))
            self.screen.blit(_qt, _qt.get_rect(center=_qb.center))
        elif self.shop_tab == "buffs":
            can = coins >= info["price"]
            have = me.get("inventory", {}).get(key, 0) if me else 0
            bg = (90,70,130) if can else (50,50,60)
            pygame.draw.rect(self.screen, bg, r, border_radius=8)
            pygame.draw.rect(self.screen, (180,180,200), r, 2, border_radius=8)
            label = f"{info['label']}  —  {info['price']} монет   (в наличии: {have})"
            self.screen.blit(self.font.render(label, True, (240,240,240) if can else (160,160,160)),
                             (r.x + 16, r.y + 30))
        elif self.shop_tab == "build":
            price = BUILD_PRICES.get(key, 0); can = coins >= price
            have = me.get("build_inventory", {}).get(key, 0) if me else 0
            in_slot = bool(me) and me.get("build_slot") == key
            bg = (50,80,110) if can else (50,50,60)
            if in_slot: bg = (100,70,40)
            pygame.draw.rect(self.screen, bg, r, border_radius=8)
            pygame.draw.rect(self.screen, (180,180,200), r, 2, border_radius=8)
            label = f"{info.get('label', BUILD_LABELS.get(key, key))}  —  {price} монет   (в наличии: {have})"
            self.screen.blit(self.font.render(label, True, (240,240,240) if can else (160,160,160)),
                             (r.x + 16, r.y + 30))
            sb = pygame.Rect(r.right - 110, r.bottom - 34, 96, 26)
            sb_bg = (90,60,130) if have > 0 else (60,50,60)
            if in_slot: sb_bg = (160,120,40)
            pygame.draw.rect(self.screen, sb_bg, sb, border_radius=5)
            pygame.draw.rect(self.screen, (220,200,255), sb, 2, border_radius=5)
            sb_text = "В СЛОТЕ" if in_slot else "В СЛОТ"
            self.screen.blit(self.small.render(sb_text, True, (255,255,255)),
                             self.small.render(sb_text, True, (255,255,255)).get_rect(center=sb.center))
        elif self.shop_tab == "passives":
            price = info["price"]; can = coins >= price
            owned = bool(me) and key in me.get("passive_owned", [])
            active = bool(me) and me.get("passive") == key
            req = info.get("requires_achievement")
            locked = bool(req) and not self._has_achievement(req)
            bg = (80,60,40) if can and not owned and not locked else (50,50,60)
            if active: bg = (140,100,40)
            if locked: bg = (50,30,30)
            pygame.draw.rect(self.screen, bg, r, border_radius=8)
            pygame.draw.rect(self.screen, (180,180,200), r, 2, border_radius=8)
            self.screen.blit(self.font.render(info["label"], True,
                             (240,240,240) if not locked else (160,160,160)), (r.x + 16, r.y + 8))
            self.screen.blit(self.tiny.render(info["desc"], True, (200,200,200)), (r.x + 16, r.y + 34))
            sub = "АКТИВНА" if active else ("КУПЛЕНО" if owned else f"{price} монет")
            sub_col = (255,220,120) if active else ((140,220,140) if owned else ((255,220,120) if can and not locked else (160,160,160)))
            if locked:
                sub = f"Требуется достижение: {ACHIEVEMENT_NAMES.get(req, req)}"; sub_col = (200,80,80)
            self.screen.blit(self.small.render(sub, True, sub_col), (r.x + 16, r.y + 58))
            # кнопка СНЯТЬ/ВКЛ для купленной пассивки — как "В СЛОТ"
            if owned:
                sb = pygame.Rect(r.right - 110, r.bottom - 34, 96, 26)
                sb_bg = (160,120,40) if active else (90,60,130)
                pygame.draw.rect(self.screen, sb_bg, sb, border_radius=5)
                pygame.draw.rect(self.screen, (220,200,255), sb, 2, border_radius=5)
                sb_text = "СНЯТЬ" if active else "ВКЛ"
                self.screen.blit(self.small.render(sb_text, True, (255,255,255)),
                                 self.small.render(sb_text, True, (255,255,255)).get_rect(center=sb.center))

    # ============================================================
    #  МУЗЫКА: переключение меню <-> игра
    # ============================================================
    def _update_music(self):
        if not getattr(self, "audio_ok", False):
            # один раз сообщим, что микшер не работает
            if not getattr(self, "_music_warned", False):
                print("[music] audio_ok = False, музыка недоступна")
                self._music_warned = True
            return

        in_menu = self.state in ("menu", "choose_input", "settings",
                                  "servers", "server_settings", "stats",
                                  "keybinds")
        in_game = (self.state == "game")

        def _play(path):
            if not path:
                return False
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(0.35)
                pygame.mixer.music.play(-1)
                return True
            except Exception as e:
                print("[music] ошибка воспроизведения:", path, "->", e)
                return False

        if in_menu:
            if not self.music_menu_started:
                if _play(_MUSIC_MENU_PATH):
                    self.music_menu_started = True
                    self.music_game_started = False
        elif in_game:
            if not self.music_game_started:
                if _play(_MUSIC_GAME_PATH):
                    self.music_game_started = True
                    self.music_menu_started = False
        else:
            # например, "choose_input" мы уже отнесли к меню — сюда не попадёт
            pass

    def _interpolate_network(self, dt):
        """NumPy-сглаживание: между серверными тиками (20 Гц) интерполируем
        позиции игроков и зомби, чтобы на 60 FPS движение было плавным."""
        try:
            alpha = max(0.0, min(1.0, dt * TICK_RATE * 0.5))

            # Игроки
            for pid, p in self.players.items():
                tgt_x = p.get("x", 0.0); tgt_y = p.get("y", 0.0)
                sx = p.setdefault("_sx", tgt_x)
                sy = p.setdefault("_sy", tgt_y)
                p["_sx"] = sx + (tgt_x - sx) * alpha
                p["_sy"] = sy + (tgt_y - sy) * alpha

            # Зомби — быстрее, массивом через numpy
            if self.zombies:
                xs = np.fromiter((z.get("x", 0.0) for z in self.zombies),
                                 dtype=np.float32, count=len(self.zombies))
                ys = np.fromiter((z.get("y", 0.0) for z in self.zombies),
                                 dtype=np.float32, count=len(self.zombies))
                sxs = np.fromiter((z.setdefault("_sx", z.get("x", 0.0))
                                   for z in self.zombies),
                                  dtype=np.float32, count=len(self.zombies))
                sys_ = np.fromiter((z.setdefault("_sy", z.get("y", 0.0))
                                    for z in self.zombies),
                                   dtype=np.float32, count=len(self.zombies))
                sxs += (xs - sxs) * alpha
                sys_ += (ys - sys_) * alpha
                for i, z in enumerate(self.zombies):
                    z["_sx"] = float(sxs[i])
                    z["_sy"] = float(sys_[i])
        except Exception:
            pass

    def _draw_overlay_pixel(self):
        """Рисует ТОЛЬКО то, что должно быть пиксельным. Вызывается в draw()
        когда self.screen == self.overlay_canvas."""
        st = self.state
        if st == "game":
            if self.choosing_weapon:
                self._draw_choose_weapon_overlay()
            else:
                self._draw_game_overlay()
        elif st == "menu":
            self._draw_menu_overlay()
        elif st == "choose_input":
            self._draw_choose_input_overlay()
        # на остальных экранах (settings / stats / servers / keybinds)
        # ничего не пикселизируем

    # -------- Игра: пиксельный слой --------
    def _draw_game_overlay(self):
        # локальные алиасы для читаемости
        s = self.screen
        me = self.players.get(self.my_id)
        # === ОБНОВЛЕНИЕ КАМЕРЫ (перенесено из _draw_game) ===
        if me and not me.get("dead") and self.local_init:
            tx = self.local_x - WIDTH / 2; ty = self.local_y - HEIGHT / 2
        elif me:
            tx = me["x"] - WIDTH / 2; ty = me["y"] - HEIGHT / 2
        else:
            tx, ty = self.camera
        self.camera[0] += (tx - self.camera[0]) * 0.35
        self.camera[1] += (ty - self.camera[1]) * 0.35
        self.camera[0] = max(0, min(self.map_w - WIDTH, self.camera[0]))
        self.camera[1] = max(0, min(self.map_h - HEIGHT, self.camera[1]))
        cx, cy = self.camera
        now_server = time.time() + self.server_time_offset

        # === СЕТКА И ГРАНИЦА КАРТЫ (перенесено из _draw_game) ===
        step = BARRICADE_GRID
        _x0 = int(cx // step) * step; _y0 = int(cy // step) * step
        for _gx in range(_x0, int(cx + WIDTH) + step, step):
            _sx = _gx - cx
            pygame.draw.line(s, (170, 220, 170), (_sx, 0), (_sx, HEIGHT))
        for _gy in range(_y0, int(cy + HEIGHT) + step, step):
            _sy = _gy - cy
            pygame.draw.line(s, (170, 220, 170), (0, _sy), (WIDTH, _sy))
        pygame.draw.rect(s, (60, 120, 60), (0 - cx, 0 - cy, self.map_w, self.map_h), 6)

        # --- постройки ---
        for b in self.buildings:
            half = BARRICADE_GRID / 2
            sx = b["x"] - cx - half; sy = b["y"] - cy - half
            size = BARRICADE_GRID; hp = max(0, b["hp"]) / max(1, b["max_hp"])
            kind = b.get("kind")
            if kind == BUILD_BARRICADE:
                col = (130,95,55) if hp > 0.66 else ((170,120,60) if hp > 0.33 else (200,80,60))
                rect = pygame.Rect(int(sx), int(sy), size, size)
                pygame.draw.rect(s, col, rect); pygame.draw.rect(s, (40,30,20), rect, 3)
                pygame.draw.rect(s, (40,30,20), (sx, sy-8, size, 4))
                pygame.draw.rect(s, (60,200,60), (sx, sy-8, size*hp, 4))
            elif kind == BUILD_DOOR:
                rect = pygame.Rect(int(sx), int(sy), size, size)
                pygame.draw.rect(s, (120, 80, 50), rect, border_radius=4)
                pygame.draw.rect(s, (60, 40, 20), rect, 3, border_radius=4)
                inner = pygame.Rect(int(sx)+6, int(sy)+6, size-12, size-12)
                pygame.draw.rect(s, (200, 170, 120), inner, border_radius=3)
                pygame.draw.rect(s, (60, 40, 20), inner, 2, border_radius=3)
                pygame.draw.circle(s, (255, 220, 100),
                                   (int(sx) + size - 10, int(sy) + size // 2), 3)
                pygame.draw.rect(s, (40,30,20), (sx, sy-8, size, 4))
                pygame.draw.rect(s, (60,200,60), (sx, sy-8, size*hp, 4))
            else:
                if kind == BUILD_TURRET: base = (120,120,130)
                elif kind == BUILD_FIRE_TURRET: base = (150,80,40)
                elif kind == BUILD_REPAIR_TURRET: base = (60,140,80)
                elif kind == BUILD_ELECTRIC_TURRET: base = (80,140,220)
                else: base = (100,100,100)
                rect = pygame.Rect(int(sx), int(sy), size, size)
                pygame.draw.rect(s, base, rect, border_radius=6)
                pygame.draw.rect(s, (40,40,50) if kind == BUILD_TURRET else (60,30,20), rect, 3, border_radius=6)
                cxt = b["x"] - cx; cyt = b["y"] - cy
                ang = b.get("angle", 0.0)
                ex = cxt + math.cos(ang) * (size // 2 + 4); ey = cyt + math.sin(ang) * (size // 2 + 4)
                pygame.draw.line(s, (60,60,70), (cxt, cyt), (ex, ey), 8)
                pygame.draw.circle(s,
                                   (255,140,30) if kind == BUILD_FIRE_TURRET
                                   else ((150,220,255) if kind == BUILD_ELECTRIC_TURRET else (180,200,240)),
                                   (int(ex), int(ey)), 6 if kind == BUILD_FIRE_TURRET else 5)

        # --- ящики ---
        for cr in self.crates:
            sx = cr["x"] - cx; sy = cr["y"] - cy
            if not (-100 < sx < WIDTH + 100 and -100 < sy < HEIGHT + 100): continue
            col = tuple(cr["color"])
            pygame.draw.rect(s, col, (int(sx-CRATE_R), int(sy-CRATE_R), CRATE_R*2, CRATE_R*2), border_radius=6)
            pygame.draw.rect(s, (20,20,25), (int(sx-CRATE_R), int(sy-CRATE_R), CRATE_R*2, CRATE_R*2), 4, border_radius=6)

        # --- запретные ---
        for fi in self.forbidden_items:
            sx, sy = fi["x"] - cx, fi["y"] - cy
            t = time.time() * 3; r = FORBIDDEN_R + int(2 * math.sin(t))
            pygame.draw.circle(s, (60,20,90), (int(sx), int(sy)), r)
            pygame.draw.circle(s, (180,80,240), (int(sx), int(sy)), r, 3)

        # --- метеоры ---
        for m in self.meteors:
            sx, sy = m["x"] - cx, m["y"] - cy
            pygame.draw.circle(s, (30,20,40), (int(sx), int(sy)), 100)
            pygame.draw.circle(s, (255,120,40), (int(sx), int(sy)), 100, 4)
            pygame.draw.circle(s, (255,200,60), (int(sx), int(sy)), 120, 3)

        # --- снаряды турелей ---
        for tb in self.turret_bullets:
            sx, sy = tb["x"] - cx, tb["y"] - cy
            if tb.get("fire"):
                pygame.draw.circle(s, (255,120,40), (int(sx), int(sy)), 12)
                pygame.draw.circle(s, (255,240,120), (int(sx), int(sy)), 6)
            else:
                pygame.draw.circle(s, (200,220,255), (int(sx), int(sy)), 5)

        # --- спиттер-снаряды ---
        for sb in self.spitter_bullets:
            sx, sy = sb["x"] - cx, sb["y"] - cy
            pygame.draw.circle(s, (200, 200, 60), (int(sx), int(sy)), int(sb["r"]))
            pygame.draw.circle(s, (140, 140, 40), (int(sx), int(sy)), int(sb["r"]), 3)

        # --- пули финального босса ---
        for fb in self.final_boss_bullets:
            sx, sy = fb["x"] - cx, fb["y"] - cy
            r = fb.get("r", FINAL_BOSS_HOMING_R)
            pulse = 2 + int(2 * math.sin(time.time() * 8))
            pygame.draw.circle(s, (255, 60, 200), (int(sx), int(sy)), r + pulse)
            pygame.draw.circle(s, (255, 220, 240), (int(sx), int(sy)), r)
            pygame.draw.circle(s, (255, 255, 255), (int(sx), int(sy)), max(3, r // 3))

        # --- лазеры ---
        for pid, p in self.players.items():
            if p.get("dead"): continue
            wkey = p.get("weapon", "base")
            if wkey not in ("laser", "first_prism", "last_prism"): continue
            if p.get("laser_until", 0) <= now_server: continue
            px, py = (self.local_x, self.local_y) if (pid == self.my_id and self.local_init) else (p["x"], p["y"])
            sx, sy = px - cx, py - cy
            ang = p.get("laser_angle", p.get("angle", 0))
            if wkey == "last_prism":
                rng = max(self.map_w, self.map_h) * 2
                col_outer, col_inner = (255, 255, 255), (255, 255, 240)
                w = LASER_WIDTH + 10
            elif wkey == "first_prism":
                rng = LASER_RANGE
                col_outer, col_inner = (255, 255, 255), (255, 255, 200)
                w = LASER_WIDTH
            else:
                rng = LASER_RANGE
                col_outer, col_inner = (255, 0, 0), (255, 200, 200)
                w = LASER_WIDTH
            ex = sx + math.cos(ang) * rng; ey = sy + math.sin(ang) * rng
            pygame.draw.line(s, col_outer, (sx, sy), (ex, ey), w)
            pygame.draw.line(s, col_inner, (sx, sy), (ex, ey), max(2, w // 3))

        # --- пули ---
        for b in self.bullets:
            sx, sy = b["x"] - cx, b["y"] - cy
            wkey = b.get("weapon", "base")
            if wkey == "star":
                col = (255,240,120) if b.get("special") else (255,200,60)
                r = 18 if b.get("special") else 12
                pts = []
                for k in range(16):
                    ang = k * math.pi / 8; rad = r if k % 2 == 0 else r * 0.4
                    pts.append((sx + math.cos(ang) * rad, sy + math.sin(ang) * rad))
                pygame.draw.polygon(s, col, pts); continue
            if wkey == "true_star":
                col = (255, 250, 180); r = 24
                pts = []
                for k in range(16):
                    ang = k * math.pi / 8; rad = r if k % 2 == 0 else r * 0.4
                    pts.append((sx + math.cos(ang) * rad, sy + math.sin(ang) * rad))
                pygame.draw.polygon(s, col, pts)
                pygame.draw.polygon(s, (255, 255, 255), pts, 2); continue
            if wkey == "secret_beam":
                # рука (простая: ладонь + 4 пальца)
                pygame.draw.circle(s, (220, 180, 140), (int(sx), int(sy)), 10)
                for _k in range(4):
                    _a = math.radians(b.get("angle", 0)) + (-0.3 + _k * 0.2)
                    pygame.draw.line(s, (150, 110, 80),
                                     (sx, sy), (sx + math.cos(_a) * 16, sy + math.sin(_a) * 16), 3)
                pygame.draw.circle(s, (255, 100, 255), (int(sx), int(sy)), 4, 2)
                continue
            if wkey == "hexagon":
                pts = []
                for k in range(6):
                    ang = k * math.pi / 3
                    pts.append((sx + math.cos(ang) * 9, sy + math.sin(ang) * 9))
                pygame.draw.polygon(s, (30, 30, 30), pts)
                pygame.draw.polygon(s, (200, 200, 200), pts, 2); continue
            if wkey == "bow":
                # Стрела: древко + наконечник + оперение
                ang = math.atan2(b["vy"], b["vx"])
                L = 22
                ex = sx + math.cos(ang) * L
                ey = sy + math.sin(ang) * L
                bx = sx - math.cos(ang) * L * 0.3
                by = sy - math.sin(ang) * L * 0.3
                pygame.draw.line(s, (139, 69, 19), (int(bx), int(by)), (int(ex), int(ey)), 2)
                tip1 = (ex + math.cos(ang + 2.7) * 6, ey + math.sin(ang + 2.7) * 6)
                tip2 = (ex + math.cos(ang - 2.7) * 6, ey + math.sin(ang - 2.7) * 6)
                pygame.draw.polygon(s, (200, 200, 220), [(ex, ey), tip1, tip2])
                f1 = (bx + math.cos(ang + 1.8) * 5, by + math.sin(ang + 1.8) * 5)
                f2 = (bx + math.cos(ang - 1.8) * 5, by + math.sin(ang - 1.8) * 5)
                pygame.draw.line(s, (255, 255, 255), (int(bx), int(by)), (int(f1[0]), int(f1[1])), 2)
                pygame.draw.line(s, (255, 255, 255), (int(bx), int(by)), (int(f2[0]), int(f2[1])), 2)
                continue
            col = (255,240,120)
            if wkey == "shotgun": col = (240,200,100)
            elif wkey == "smg": col = (200,255,120)
            elif wkey == "sniper": col = (180,220,255)
            elif wkey == "laser": col = (255,80,80)
            elif wkey == "first_prism": col = (255, 255, 255)
            elif wkey == "last_prism": col = (255, 255, 255)
            elif wkey == "plasma": col = (150,100,255)
            elif wkey == "stone": col = (170,170,180)
            elif wkey == "meteor": col = (180,100,255)
            elif wkey == "charm_staff": col = (255,150,220)
            if b.get("firedoom"): col = (255,140,30)
            pygame.draw.circle(s, col, (int(sx), int(sy)), 5)

        # --- игроки ---
        for pid, p in self.players.items():
            if p.get("dead"): continue
            if p.get("wanish") and pid != self.my_id: continue
            px, py = (self.local_x, self.local_y) if (pid == self.my_id and self.local_init) else (p["x"], p["y"])
            sx, sy = px - cx, py - cy
            color = tuple(p.get("color", (200,100,100))); r = PLAYER_R
            if p.get("wanish"): color = tuple(min(255, c + 100) for c in color)
            if p.get("speed_until", 0) > now_server: pygame.draw.circle(s, (255,240,100), (int(sx), int(sy)), r + 12, 4)
            if p.get("shoot_until", 0) > now_server: pygame.draw.circle(s, (120,180,255), (int(sx), int(sy)), r + 20, 4)
            if p.get("firedoom_until", 0) > now_server: pygame.draw.circle(s, (255,90,0), (int(sx), int(sy)), r + 28, 3)
            if p.get("crazy_until", 0) > now_server:
                pygame.draw.circle(s, (255,60,200), (int(sx), int(sy)), r + 34, 4)
                pygame.draw.circle(s, (255,200,255), (int(sx), int(sy)), r + 42, 2)
            if p.get("frozen_until", 0) > now_server:
                pygame.draw.circle(s, (120,200,255), (int(sx), int(sy)), r + 6, 6)
            if p.get("weapon") == "shield":
                pygame.draw.circle(s, (180,200,240), (int(sx), int(sy)), r + 8, 6)
            a_ = p.get("angle", 0); wkey = p.get("weapon", "base")
            if wkey in ARSENAL: self._draw_weapon_in_hand(sx, sy, wkey, a_)
            pygame.draw.circle(s, color, (int(sx), int(sy)), r)
            bright = sum(color) / 3
            outline = (30,30,30) if bright > 128 else (240,240,240)
            pygame.draw.circle(s, outline, (int(sx), int(sy)), r, 3)
            hp = p.get("hp", 0); bw = 70
            pygame.draw.rect(s, (80,80,80), (sx - bw//2, sy - r - 16, bw, 7))
            pygame.draw.rect(s, (60,200,60), (sx - bw//2, sy - r - 16, int(bw * hp / MAX_HP), 7))
            cname = color_name_of(tuple(p.get("color", (200,100,100))))
            if cname:
                nm = self.tiny.render(cname, True, (20,20,20))
                s.blit(nm, nm.get_rect(center=(sx, sy - r - 42)))
            lvl = p.get("level", 0)
            lv = self.small.render(f"Lv{lvl}", True, (20,20,20))
            s.blit(lv, lv.get_rect(center=(sx, sy - r - 28)))

        # --- зомби (через кэш спрайтов) ---
        for z in self.zombies:
            zr = z.get("r", ZOMBIE_R)
            sx, sy = z["x"] - cx, z["y"] - cy
            if not (-zr-100 < sx < WIDTH + zr+100 and -zr-100 < sy < HEIGHT + zr+100): continue
            sprite = self._get_zombie_sprite(z, now_server)
            s.blit(sprite, (int(sx - sprite.get_width() // 2),
                            int(sy - sprite.get_height() // 2)))
            # HP-бар — рисуем отдельно, он меняется с каждым ударом
            is_boss = z.get("boss", False); is_final = z.get("final", False)
            is_s50 = z.get("stage50", False); is_golden = z.get("golden", False)
            ch = z.get("charmed", False); shadow = z.get("shadow", False)
            bw = 400 if is_final else (300 if (is_s50 or is_boss) else 70)
            frac = max(0, z["hp"]) / max(1, z["max_hp"])
            bar_h = 10 if (is_boss or is_final or is_s50) else 6
            pygame.draw.rect(s, (60,30,30), (sx - bw//2, sy - zr - 18, bw, bar_h))
            if shadow:      hp_col = (100, 100, 100)
            elif ch:        hp_col = (255, 130, 200)
            elif is_final:  hp_col = (255, 60, 200)
            elif is_s50:    hp_col = (180, 100, 255)
            elif is_boss:   hp_col = (255, 180, 40)
            elif is_golden: hp_col = (255, 230, 80)
            else:           hp_col = (220, 60, 60)
            pygame.draw.rect(s, hp_col, (sx - bw//2, sy - zr - 18, int(bw * frac), bar_h))

        # --- попапы урона ---
        for pop in self.popups:
            sx, sy = pop["x"] - cx, pop["y"] - cy - pop["t"] * 40
            alpha = max(0, 1 - pop["t"] / pop["life"])
            txt = self.small.render(str(pop["v"]), True, tuple(pop["color"]))
            txt.set_alpha(int(255 * alpha))
            s.blit(txt, txt.get_rect(center=(sx, sy)))

        # --- кристалл ---
        if (self.host is not None and self.host.mode == MODE_CRYSTAL
                and getattr(self.host, "crystal", None) is not None):
            c = self.host.crystal
            csx = c["x"] - cx; csy = c["y"] - cy
            pygame.draw.circle(s, (60, 180, 240), (int(csx), int(csy)), CRYSTAL_R)
            pygame.draw.circle(s, (200, 240, 255), (int(csx), int(csy)), CRYSTAL_R, 4)
            frac_c = max(0, c["hp"]) / max(1, c["max_hp"])
            pygame.draw.rect(s, (60, 30, 30), (csx - CRYSTAL_R, csy - CRYSTAL_R - 14, CRYSTAL_R * 2, 8))
            pygame.draw.rect(s, (80, 200, 255), (csx - CRYSTAL_R, csy - CRYSTAL_R - 14, int(CRYSTAL_R * 2 * frac_c), 8))
        # --- кнопка старта волны ---
        if self.wave_button_active and not self.victory:
            bx = self.wave_button_x - cx; by = self.wave_button_y - cy
            if -200 < bx < WIDTH + 200 and -200 < by < HEIGHT + 200:
                pulse = int(6 + 4 * math.sin(time.time() * 4))
                pygame.draw.circle(s, (40, 90, 40), (int(bx), int(by)), WAVE_BUTTON_R + 8)
                pygame.draw.circle(s, (70, 180, 70), (int(bx), int(by)), WAVE_BUTTON_R)
                pygame.draw.circle(s, (240, 240, 200), (int(bx), int(by)), WAVE_BUTTON_R + pulse, 4)
                pygame.draw.circle(s, (255, 255, 255), (int(bx), int(by)), WAVE_BUTTON_R, 3)

        # --- джойстики (тач) ---
        if self.input_mode == "touch":
            self.move_joy.draw(s); self.aim_joy.draw(s)

    # -------- Меню: пиксельный слой --------
    def _draw_menu_overlay(self):
        s = self.screen
        # декоративные зомби
        for z in self._menu_zombies:
            sx = int(z["x"]); sy = int(z["y"]); r = z["r"]
            dark = tuple(max(0, c - 40) for c in z["body"])
            pygame.draw.circle(s, (12, 20, 12), (sx + 4, sy + 6), r + 2)
            pygame.draw.circle(s, dark, (sx, sy), r)
            eye_off = r // 3; eye_r = max(3, r // 8)
            pygame.draw.circle(s, (180, 40, 40), (sx - eye_off, sy - eye_off // 2), eye_r)
            pygame.draw.circle(s, (180, 40, 40), (sx + eye_off, sy - eye_off // 2), eye_r)
        # заголовок
        title = "Piu piu.io"
        sh = self.menu_title.render(title, True, (10, 40, 10))
        s.blit(sh, sh.get_rect(center=(WIDTH // 2 + 4, HEIGHT // 2 - 210 + 4)))
        tm = self.menu_title.render(title, True, (150, 255, 150))
        s.blit(tm, tm.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 210)))
        # подзаголовок
        cur = self._my_stage()
        sub = self.font.render(f"Сюжет: {STAGE_NAMES.get(cur, '10 волн')}   Побед: {self._my_wins()}",
                                True, (180, 230, 180))
        s.blit(sub, sub.get_rect(center=(WIDTH//2, HEIGHT//2 - 140)))
        if self.info_msg and time.time() < self.info_msg_until:
            im = self.font.render(self.info_msg, True, (255, 80, 80))
            s.blit(im, im.get_rect(center=(WIDTH//2, HEIGHT//2 + 260)))
        # кнопки
        mouse = pygame.mouse.get_pos()
        self.btn_play.draw(s, self.font, mouse)
        self.btn_solo.draw(s, self.font, mouse)
        self.btn_settings.draw(s, self.font, mouse)
        self.btn_stats.draw(s, self.font, mouse)
        # версия патча — правый нижний угол меню
        if patch_version:
            _pvsurf = self.font.render(patch_version, True, (70, 70, 70))
            s.blit(_pvsurf, _pvsurf.get_rect(bottomright=(WIDTH - 140, HEIGHT - 20)))
        # версия патча — правый нижний угол меню
        if patch_version:
            _pvsurf = self.small.render(patch_version, True, (90, 90, 90))
            s.blit(_pvsurf, _pvsurf.get_rect(bottomright=(WIDTH - 10, HEIGHT - 10)))

    def _draw_choose_input_overlay(self):
        s = self.screen
        # декоративные зомби тоже
        for z in self._menu_zombies:
            sx = int(z["x"]); sy = int(z["y"]); r = z["r"]
            dark = tuple(max(0, c - 40) for c in z["body"])
            pygame.draw.circle(s, (12, 20, 12), (sx + 4, sy + 6), r + 2)
            pygame.draw.circle(s, dark, (sx, sy), r)
            eye_off = r // 3; eye_r = max(3, r // 8)
            pygame.draw.circle(s, (180, 40, 40), (sx - eye_off, sy - eye_off // 2), eye_r)
            pygame.draw.circle(s, (180, 40, 40), (sx + eye_off, sy - eye_off // 2), eye_r)
        # заголовок
        t1 = self.huge.render("ВЫБЕРИ УПРАВЛЕНИЕ", True, (255, 240, 180))
        s.blit(t1, t1.get_rect(center=(WIDTH//2, HEIGHT//2 - 160)))
        t2 = self.font.render("Это можно поменять в настройках", True, (200, 220, 200))
        s.blit(t2, t2.get_rect(center=(WIDTH//2, HEIGHT//2 - 100)))
        # кнопки
        mouse = pygame.mouse.get_pos()
        self.btn_choose_pc.draw(s, self.huge, mouse)
        self.btn_choose_touch.draw(s, self.huge, mouse)

    def _draw_choose_weapon_overlay(self):
        """Пиксельный слой выбора оружия."""
        s = self.screen
        self.screen.blit(self.huge.render("ВЫБЕРИ ОРУЖИЕ", True, (255, 240, 180)),
                         self.huge.render("ВЫБЕРИ ОРУЖИЕ", True, (255, 240, 180)).get_rect(center=(WIDTH // 2, 120)))
        cols = [("base", "Пистолет", "Стартовое, слабое, но вечное"),
                ("rifle", "Автомат", "Скорострельный, средний урон"),
                ("shotgun", "Дробовик", "Убойный вблизи, 7 дробин")]
        bw = 360; bh = 400; gap = 40
        total = len(cols) * bw + (len(cols) - 1) * gap
        x0 = WIDTH // 2 - total // 2; y0 = HEIGHT // 2 - bh // 2 + 60
        rects = []
        for i, (key, label, desc) in enumerate(cols):
            r = pygame.Rect(x0 + i * (bw + gap), y0, bw, bh)
            rects.append((key, r))
            mouse = pygame.mouse.get_pos()
            hov = r.collidepoint(mouse)
            bg = (70, 100, 70) if hov else (45, 65, 45)
            pygame.draw.rect(s, bg, r, border_radius=14)
            pygame.draw.rect(s, (240, 220, 160), r, 4, border_radius=14)
            s.blit(self.big.render(label, True, (255, 240, 200)),
                   self.big.render(label, True, (255, 240, 200)).get_rect(center=(r.centerx, r.y + 50)))
            icon_r = pygame.Rect(r.centerx - 70, r.y + 110, 140, 140)
            self._draw_weapon_icon(key, icon_r)
            s.blit(self.font.render(desc, True, (230, 230, 230)),
                   self.font.render(desc, True, (230, 230, 230)).get_rect(center=(r.centerx, r.bottom - 60)))
        self.choose_btn_base = rects[0][1]
        self.choose_btn_rifle = rects[1][1]
        self.choose_btn_shotgun = rects[2][1]

    # -------- Пикселизация overlay через NumPy (RGBA) --------
    def _pixelate_overlay(self):
        """Пикселизация overlay через pygame.transform.scale.
        Если self.pixelate == False — ничего не делает (экран чёткий)."""
        if not getattr(self, "pixelate", True):
            return
        try:
            w = max(1, WIDTH // PIXEL_SCALE)
            h = max(1, HEIGHT // PIXEL_SCALE)
            small = pygame.transform.scale(self.overlay_canvas, (w, h))
            self.overlay_canvas = pygame.transform.scale(small, (WIDTH, HEIGHT))
        except Exception as e:
            if not getattr(self, "_pix_warned", False):
                print("[pixelate overlay] ошибка:", e); self._pix_warned = True

    def _get_zombie_sprite(self, z, now_server):
        """Возвращает закэшированный Surface с телом, глазами, обводкой
        и, если нужно, телеграф/золотое свечение. HP-бар рисуется отдельно
        (зависит от текущего hp)."""
        cache = getattr(self, "_zombie_sprite_cache", None)
        if cache is None:
            cache = {}; self._zombie_sprite_cache = cache

        zr = z.get("r", ZOMBIE_R)
        is_boss = z.get("boss", False); is_final = z.get("final", False)
        is_s50 = z.get("stage50", False); ch = z.get("charmed", False)
        shadow = z.get("shadow", False); is_golden = z.get("golden", False)
        kind = z.get("kind", "normal")
        fire = z.get("fire_until", 0) > now_server
        frozen = z.get("frozen_until", 0) > now_server
        telegraph = bool(is_s50 and z.get("dash_state") == "telegraph")

        key = (kind, is_boss, is_final, is_s50, ch, shadow,
               is_golden, zr, fire, frozen, telegraph)
        cached = cache.get(key)
        if cached is not None:
            return cached

        pad = zr + 30
        size = pad * 2
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        cs = pad  # центр

        # цвета тела / обводки
        if ch:
            if shadow: body, outline = (20, 20, 20), (80, 80, 80)
            else:      body, outline = (255, 170, 210), (200, 60, 140)
        elif is_final:  body, outline = (120, 20, 20), (255, 220, 60)
        elif is_s50:    body, outline = (80, 40, 140), (255, 220, 60)
        elif is_boss:   body, outline = (140, 40, 100), (255, 100, 255)
        elif is_golden: body, outline = (255, 215, 0), (180, 120, 0)
        elif kind in ZOMBIE_TYPES:
            body, outline = ZOMBIE_TYPES[kind]["color"], (30, 60, 30)
        else:
            body, outline = (70, 140, 70), (30, 60, 30)

        if not ch and not is_golden:
            if fire:   body = (200, 100, 40)
            if frozen: body = (120, 180, 255)

        # телеграф (красное кольцо)
        if telegraph:
            pygame.draw.circle(surf, (255, 60, 60), (cs, cs), zr + 20, 5)
        # золотое свечение
        if is_golden:
            pygame.draw.circle(surf, (255, 245, 180), (cs, cs), zr + 8, 4)
        # тело
        pygame.draw.circle(surf, body, (cs, cs), zr)
        outline_w = 6 if (is_final or is_s50 or is_golden) else (5 if is_boss else 3)
        pygame.draw.circle(surf, outline, (cs, cs), zr, outline_w)
        # глаза
        eye_off = zr // 3; eye_r = max(5, zr // 8)
        eye_col = (200, 60, 200) if shadow else ((255, 40, 140) if ch else (255, 40, 40))
        pygame.draw.circle(surf, eye_col, (cs - eye_off, cs - eye_off // 2), eye_r)
        pygame.draw.circle(surf, eye_col, (cs + eye_off, cs - eye_off // 2), eye_r)

        cache[key] = surf
        return surf

    def run(self):
        try:
            while True:
                dt = self.clock.tick(FPS) / 1000
                self.events(); self.update(dt); self.draw()
        finally:
            self.leave(); pygame.quit()


if __name__ == "__main__":
    App().run()