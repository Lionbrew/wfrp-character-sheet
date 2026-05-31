#!/usr/bin/env python3
"""
WFRP4e Character Sheet — Main Application
==========================================
Double-click this file to start, or run:  python wfrp_app.py
The app opens automatically in your default browser.
Press Ctrl+C in this window (or close it) to stop.
"""

import sys
import os
import json
import io
import re
import time
import socket
import threading
import webbrowser
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Constants ──────────────────────────────────────────────────────────────────
APP_NAME    = "WFRP4e Character Sheet"
APP_VERSION = "1.0"
PORT        = 5000

# Heartbeat: shut down if no browser ping received within this many seconds.
PING_TIMEOUT      = 15   # seconds without a ping → assume tab was closed
PING_GRACE        = 25   # seconds to wait on startup before watchdog activates
PING_INTERVAL     = 5    # how often the browser pings (must match the HTML)

_last_ping = [0.0]       # [0] updated by /api/ping handler; list so threads share it

# Capacities of the main character sheet (row counts visible on the printed form).
# Overflow beyond these triggers the extra talent/trapping page.
MAIN_TALENT_CAPACITY = 4   # talent entries visible on main sheet
MAIN_TRAP_CAPACITY   = 10  # trapping rows visible on main sheet
MAIN_SPELL_CAPACITY  = 8   # spell/prayer rows visible on main sheet

# Support both normal Python and PyInstaller frozen bundles
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running as PyInstaller bundle - resources are in _MEIPASS temp dir
    HERE = sys._MEIPASS
    # Also look next to the .exe for the PDF (user may put it there)
    EXE_DIR = os.path.dirname(sys.executable)
else:
    HERE    = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = HERE

# ── Locate required files ──────────────────────────────────────────────────────
HTML_FILE = os.path.join(HERE, "index.html")
PDF_TEMPLATE          = None
ARMOR_PAGE_TEMPLATE   = None
TALENT_PAGE_TEMPLATE  = None
EXTRA_SPELLS_TEMPLATE = None
BLANK_PDF             = None

# Search order: exe dir first (user-placed), then bundle dir
for search_dir in [EXE_DIR, HERE]:
    for fname in os.listdir(search_dir):
        fl = fname.lower()
        if fl == 'armorpage_fillable.pdf':
            ARMOR_PAGE_TEMPLATE = os.path.join(search_dir, fname)
        elif fl == 'talentextra_fillable.pdf':
            TALENT_PAGE_TEMPLATE = os.path.join(search_dir, fname)
        elif fl == 'extraspells_fillable.pdf':
            EXTRA_SPELLS_TEMPLATE = os.path.join(search_dir, fname)
        elif fl == 'blank.pdf':
            BLANK_PDF = os.path.join(search_dir, fname)
        elif (fl.endswith('.pdf') and 'fillable' in fl
              and 'armor' not in fl and 'armour' not in fl
              and 'talent' not in fl and 'spell' not in fl):
            PDF_TEMPLATE = os.path.join(search_dir, fname)
    if PDF_TEMPLATE and ARMOR_PAGE_TEMPLATE and TALENT_PAGE_TEMPLATE and EXTRA_SPELLS_TEMPLATE:
        break
# Fallback: any WFRP-named PDF
if not PDF_TEMPLATE:
    for search_dir in [EXE_DIR, HERE]:
        for fname in os.listdir(search_dir):
            if fname.lower().endswith('.pdf') and 'wfrp' in fname.lower():
                PDF_TEMPLATE = os.path.join(search_dir, fname)
                break
        if PDF_TEMPLATE:
            break

# ── Saves directory (next to EXE / script) ────────────────────────────────────
SAVES_DIR = os.path.join(EXE_DIR, "saves")

# ── Verify dependencies ────────────────────────────────────────────────────────
def check_dependencies():
    missing = []
    try:
        import pypdf
    except ImportError:
        missing.append("pypdf")
    return missing

# ── PDF filling ────────────────────────────────────────────────────────────────
SKILL_FIELD_MAP = [
    ("Dex",   "AdvDex",   "SkillDex"),
    ("Ag",    "AdvAg",    "SkillAg"),
    ("Fel_3", "AdvFel_3", "SkillFel_3"),
    ("Fel_4", "AdvFel_4", "SkillFel_4"),
    ("WP",    "AdvWP",    "SkillWP"),
    ("S_2",   "AdvS_2",   "SkillS_2"),
    ("WP_2",  "AdvWP_2",  "SkillWP_2"),
    ("T",     "AdvT",     "SkillT"),
    ("Ag_2",  "AdvAg_2",  "SkillAg_2"),
    ("Ag_3",  "AdvAg_3",  "SkillAg_3"),
    ("T_2",   "AdvT_2",   "SkillT_2"),
    ("Fel_6", "AdvFel_6", "SkillFel_6"),
    ("Int_2", "AdvInt_2", "SkillInt_2"),
    ("Fel",   "AdvFel",   "SkillFel"),
    ("Fel_2", "AdvFel_2", "SkillFel_2"),
    ("S",     "AdvS",     "SkillS"),
    ("I",     "AdvI",     "SkillI"),
    ("Fel_5", "AdvFel_5", "SkillFel_5"),
    ("WS",    "AdvWS",    "SkillWS"),
    ("WS_2",  "AdvWS_2",  "SkillWS_2"),
    ("I_2",   "AdvI_2",   "SkillI_2"),
    ("Int",   "AdvInt",   "SkillInt"),
    ("I_3",   "AdvI_3",   "SkillI_3"),
    ("Ag_4",  "AdvAg_4",  "SkillAg_4"),
    ("S_3",   "AdvS_3",   "SkillS_3"),
    ("Ag_5",  "AdvAg_5",  "SkillAg_5"),
]

def build_field_values(data):
    fv = {}

    def f(field_id, value, page=1):
        fv[(field_id, page)] = str(value) if value is not None else ""

    # Page 1 — Identity
    f("Name",          data.get("name", ""))
    f("Species",       data.get("species", ""))
    f("Class",         data.get("cls", ""))
    f("Career",        data.get("career", ""))
    f("Career Level",  data.get("careerLevel", ""))
    f("Career Path",   data.get("careerPath", ""))
    f("Status",        data.get("status", ""))
    f("Age",           data.get("age", ""))
    f("Height",        data.get("height", ""))
    f("Hair",          data.get("hair", ""))
    f("Eyes",          data.get("eyes", ""))

    # Characteristics
    chars = data.get("chars", {})
    char_map = {
        "ws":  ("WSInitial", "WSAdvances", "WSCurrent"),
        "bs":  ("BSInitial", "BSAdvances", "BSCurrent"),
        "s":   ("SInitial",  "SAdvances",  "SCurrent"),
        "t":   ("TInitial",  "TAdvances",  "TCurrent"),
        "i":   ("IInitial",  "IAdvances",  "ICurrent"),
        "ag":  ("AgInitial", "AgAdvances", "AgCurrent"),
        "dex": ("DexInitial","DexAdvances","DexCurrent"),
        "int": ("IntInitial","IntAdvances","IntCurrent"),
        "wp":  ("WPInitial", "WPAdvances", "WPCurrent"),
        "fel": ("FelInitial","FelAdvances","FelCurrent"),
    }
    for key, (fi, fa, fc) in char_map.items():
        c = chars.get(key, {})
        f(fi, c.get("i", "0"))
        f(fa, c.get("a", "0"))
        f(fc, c.get("cur", "0"))

    # Fate / Resilience / XP / Movement
    f("Fate",           data.get("fate", "0"))
    f("Fortune",        data.get("fortune", "0"))
    f("ResilienceRow1", data.get("res", "0"))
    f("ResolveRow1",    data.get("resolve", "0"))
    f("MotivationRow1", data.get("motivation", ""))
    f("CurrentRow1",    data.get("xpC", "0"))
    f("SpentRow1",      data.get("xpS", "0"))
    f("TotalRow1",      data.get("xpT", "0"))
    f("Movement",       data.get("move", "0"))
    f("Walk",           data.get("walk", "0"))
    f("Run",            data.get("run", "0"))

    # ── Characteristic helpers (used by both Basic and Advanced skills) ─────────
    # Map display abbreviation → chars dict key for current-score lookup
    _CHAR_KEY = {
        'WS':'ws','BS':'bs','S':'s','T':'t','I':'i',
        'Ag':'ag','Dex':'dex','Int':'int','WP':'wp','Fel':'fel',
    }
    # Reverse: lowercase key → display abbreviation (new saves store lowercase)
    _CHAR_ABBR = {v: k for k, v in _CHAR_KEY.items()}
    chars_data = data.get("chars", {})
    def _char_current(abbr):
        # abbr may be lowercase key ("int") or display text ("Int") — both accepted
        key = _CHAR_KEY.get(abbr, abbr.lower())
        cd  = chars_data.get(key, {})
        try:
            return str(int(cd.get("i", 0)) + int(cd.get("a", 0)))
        except (ValueError, TypeError):
            return ""
    def _char_display(abbr):
        # Normalise to display form: "int" → "Int", "Int" → "Int"
        return _CHAR_ABBR.get(abbr.lower(), abbr) if abbr else ""

    # Basic Skills — cf field holds the characteristic VALUE (numeric), not the label
    basic = data.get("basicSkills", [])
    for i, (cf, af, sf) in enumerate(SKILL_FIELD_MAP):
        sk = basic[i] if i < len(basic) else {}
        char_abbr = sk.get("char", "")
        f(cf, _char_current(char_abbr))   # numeric value of the characteristic
        f(af, sk.get("adv",   "0"))
        f(sf, sk.get("total", "0"))

    # Grouped & Advanced Skills — all five columns are tall multiline fields
    # (~185pt, room for ~18 skills). Pack all skills using newlines.
    # When a name wraps to multiple lines, blank lines are inserted in the
    # other columns so every row stays horizontally aligned.
    SKILL_NAME_W = 17   # approx char width of the NameRow1 column (~67pt field)

    adv = data.get("advSkills", [])
    named_adv = [s for s in adv if s.get("name", "").strip()]
    adv_name_lines, adv_char_lines, adv_char2_lines, adv_adv_lines, adv_skill_lines = [], [], [], [], []
    for s in named_adv:
        n_wrap = wrap_to_lines(s.get("name", ""), SKILL_NAME_W)
        rows   = len(n_wrap)
        abbr   = s.get("char", "")
        display = _char_display(abbr)
        adv_name_lines.extend(n_wrap)
        adv_char_lines.append(display);                 adv_char_lines.extend([""] * (rows - 1))
        adv_char2_lines.append(_char_current(abbr));    adv_char2_lines.extend([""] * (rows - 1))
        adv_adv_lines.append(s.get("adv",   "0"));     adv_adv_lines.extend([""] * (rows - 1))
        adv_skill_lines.append(s.get("total", "0"));    adv_skill_lines.extend([""] * (rows - 1))
    f("NameRow1",             "\n".join(adv_name_lines))
    f("CharacteristicRow1",   "\n".join(adv_char_lines))
    f("CharacteristicRow1_2", "\n".join(adv_char2_lines))
    f("AdvRow1",              "\n".join(adv_adv_lines))
    f("SkillRow1",            "\n".join(adv_skill_lines))

    # Talents — one tall multiline field per column; pack all talents in, keeping
    # rows aligned by padding name/times when a long description wraps.
    # Field widths: Name≈78pt (~14 chars), Times≈30pt, Description≈124pt (~24 chars)
    TALENT_NAME_W = 14
    TALENT_DESC_W = 24
    talents = data.get("talents", [])
    named_talents = [t for t in talents if t.get("name", "").strip()]
    t_name_lines, t_times_lines, t_desc_lines = [], [], []
    for t in named_talents:
        n_wrap = wrap_to_lines(t.get("name",  ""), TALENT_NAME_W)
        d_wrap = wrap_to_lines(t.get("desc",  ""), TALENT_DESC_W)
        rows   = max(len(n_wrap), len(d_wrap))
        # Name column — pad to same row count as description
        t_name_lines.extend(n_wrap)
        t_name_lines.extend([""] * (rows - len(n_wrap)))
        # Times column — one value on the first row, blanks for the rest
        t_times_lines.append(t.get("times", ""))
        t_times_lines.extend([""] * (rows - 1))
        # Description column
        t_desc_lines.extend(d_wrap)
        t_desc_lines.extend([""] * (rows - len(d_wrap)))
    f("Talent NameRow1", "\n".join(t_name_lines))
    f("Times takenRow1", "\n".join(t_times_lines))
    f("DescriptionRow1", "\n".join(t_desc_lines))

    # Ambitions / Party
    f("Ambitions-short",       data.get("ambS", ""))
    f("Ambitions-long",        data.get("ambL", ""))
    f("party-ambitions-short", data.get("partyS", ""))
    f("Party-ambitions-long",  data.get("partyL", ""))
    f("Party-members",         data.get("partyM", ""))

    # Page 2 — Armour rows (5 in PDF)
    # Long qualities strings overflow to the next physical row (same pattern as spells).
    armour = data.get("armour", [])
    named_armour = [a for a in armour if a.get("name", "").strip()]
    arm_fields = [
        ("NameRow1_2","LocationsRow1","EncRow1","APRow1","QualitiesRow1"),
        ("NameRow2",  "LocationsRow2","EncRow2","APRow2","QualitiesRow2"),
        ("NameRow3",  "LocationsRow3","EncRow3","APRow3","QualitiesRow3"),
        ("NameRow4",  "LocationsRow4","EncRow4","APRow4","QualitiesRow4"),
        ("NameRow5",  "LocationsRow5","EncRow5","APRow5","QualitiesRow5"),
    ]
    row_idx = 0
    for piece in named_armour:
        if row_idx >= len(arm_fields):
            break
        qual_lines = wrap_to_lines(piece.get("qualities", ""), width=26)
        # First physical row: all columns
        nf, lf, ef, af2, qf = arm_fields[row_idx]
        f(nf,  piece.get("name", ""), page=2)
        f(lf,  piece.get("loc",  ""), page=2)
        f(ef,  piece.get("enc",  ""), page=2)
        f(af2, piece.get("ap",   ""), page=2)
        f(qf,  qual_lines[0],         page=2)
        row_idx += 1
        # Overflow rows: qualities only
        for extra in qual_lines[1:]:
            if row_idx >= len(arm_fields):
                break
            nf2, lf2, ef2, af2b, qf2 = arm_fields[row_idx]
            f(nf2, "", page=2); f(lf2, "", page=2)
            f(ef2, "", page=2); f(af2b,"", page=2)
            f(qf2, extra, page=2)
            row_idx += 1
    # Clear remaining rows
    for nf, lf, ef, af2, qf in arm_fields[row_idx:]:
        f(nf, "", page=2); f(lf, "", page=2)
        f(ef, "", page=2); f(af2,"", page=2); f(qf, "", page=2)

    # Armour Points (hit location boxes)
    f("0109",   data.get("apHead",   "0"), page=2)
    f("1024",   data.get("apRarm",   "0"), page=2)
    f("2544",   data.get("apLarm",   "0"), page=2)
    f("4579",   data.get("apBody",   "0"), page=2)
    f("9000",   data.get("apRleg",   "0"), page=2)
    f("8089",   data.get("apLleg",   "0"), page=2)
    f("Shield", data.get("apShield", "0"), page=2)

    # Trappings — NameRow1_3 (136pt wide, 216pt tall, multiline) and
    # EncRow1_2 (21pt wide, 217pt tall, multiline) are the actual large fields.
    # Packed items get a 🐴 prefix and their enc is blanked (it counts on the mount).
    trappings = data.get("trappings", [])
    named_trappings = [r for r in trappings if r.get("name", "").strip()]
    trap_names = "\n".join(
        ("🛒 " + r.get("name", "")) if r.get("stowed") else
        ("🐴 " + r.get("name", "")) if r.get("packed") else
        r.get("name", "")
        for r in named_trappings
    )
    trap_encs = "\n".join(
        "" if (r.get("packed") or r.get("stowed")) else r.get("enc", "")
        for r in named_trappings
    )
    f("NameRow1_3", trap_names, page=2)
    f("EncRow1_2",  trap_encs,  page=2)

    # Psychology / Corruption
    f("PSYCHOLOGY 1",    data.get("psych",   ""), page=2)
    f("PSYCHOLOGY 2",    "",                       page=2)
    f("PSYCHOLOGY 3",    "",                       page=2)
    f("CorruptionMutation", data.get("corrupt",""),page=2)

    # Wealth
    f("GC",     data.get("gc", "0"), page=2)
    f("SS",     data.get("ss", "0"), page=2)
    f("WEALTH", data.get("d",  "0"), page=2)

    # Encumbrance — recalculate trapping enc excluding packed items (which are on the mount)
    def _fmt_enc(v):
        try:
            fv = float(v)
            return str(int(fv)) if fv == int(fv) else f"{fv:.1f}"
        except Exception:
            return str(v)

    enc_t_val = sum(float(r.get("enc") or 0) for r in named_trappings
                    if not r.get("packed") and not r.get("stowed"))
    try:
        enc_w_val   = float(data.get("encW", 0) or 0)
        enc_a_val   = float(data.get("encA", 0) or 0)
        enc_tot_val = enc_w_val + enc_a_val + enc_t_val
        enc_tot_str = _fmt_enc(enc_tot_val)
    except Exception:
        enc_tot_str = data.get("encTotal", "0")

    f("ENCUMBRANCE", data.get("encW",   "0"),          page=2)
    f("Armour",      data.get("encA",   "0"),          page=2)
    f("Trappings",   _fmt_enc(enc_t_val),              page=2)
    f("Max Enc",     data.get("encMax", "0"),          page=2)
    f("Total",       enc_tot_str,                       page=2)

    # Wounds
    f("WOUNDS",  data.get("wSb",    "0"), page=2)
    f("TB2",     data.get("wTb2",   "0"), page=2)
    f("WPB",     data.get("wWpb",   "0"), page=2)
    f("Hardy",   data.get("wHardy", "0"), page=2)
    f("Wounds",  data.get("wMax",   "0"), page=2)

    # Strength current value for SB calculation
    _s = chars_data.get("s", {})
    try:
        _strength_cur = int(_s.get("i", 0)) + int(_s.get("a", 0))
    except (ValueError, TypeError):
        _strength_cur = 0

    # Weapons (7 rows in PDF)
    weapons = data.get("weapons", [])
    wpn_fields = [
        ("NameRow1_4","GroupRow1","EncRow1_3","RangeReachRow1","DamageRow1","QualitiesRow1_2"),
        ("NameRow2_2","GroupRow2","EncRow2_2","RangeReachRow2","DamageRow2","QualitiesRow2_2"),
        ("NameRow3_2","GroupRow3","EncRow3_2","RangeReachRow3","DamageRow3","QualitiesRow3_2"),
        ("NameRow4_2","GroupRow4","EncRow4_2","RangeReachRow4","DamageRow4","QualitiesRow4_2"),
        ("NameRow5_2","GroupRow5","EncRow5_2","RangeReachRow5","DamageRow5","QualitiesRow5_2"),
        ("NameRow6",  "GroupRow6","EncRow6",  "RangeReachRow6","DamageRow6","QualitiesRow6"),
        ("NameRow7",  "GroupRow7","EncRow7",  "RangeReachRow7","DamageRow7","QualitiesRow7"),
    ]
    for i, (nf, gf, ef, rf, df, qf) in enumerate(wpn_fields):
        row = weapons[i] if i < len(weapons) else {}
        f(nf, row.get("name",     ""),                                        page=2)
        f(gf, abbr_group(row.get("group", "")),                               page=2)
        f(ef, row.get("enc",      ""),                                        page=2)
        f(rf, row.get("range",    ""),                                        page=2)
        f(df, resolve_weapon_damage(row.get("damage", ""), _strength_cur),    page=2)
        f(qf, row.get("qualities",""),                                        page=2)

    # Spells & Prayers (8 physical rows in PDF)
    # Long effect text is split across consecutive rows; overflow rows leave
    # Name/TN/Range/Target/Duration blank so only the Effect column is filled.
    spells = data.get("spells", [])
    named_spells = [s for s in spells if s.get("name", "").strip()]
    sp_fields = [
        ("NameRow1_5","TNRow1","RangeRow1","TargetRow1","DurationRow1","EffectRow1"),
        ("NameRow2_3","TNRow2","RangeRow2","TargetRow2","DurationRow2","EffectRow2"),
        ("NameRow3_3","TNRow3","RangeRow3","TargetRow3","DurationRow3","EffectRow3"),
        ("NameRow4_3","TNRow4","RangeRow4","TargetRow4","DurationRow4","EffectRow4"),
        ("NameRow5_3","TNRow5","RangeRow5","TargetRow5","DurationRow5","EffectRow5"),
        ("NameRow6_2","TNRow6","RangeRow6","TargetRow6","DurationRow6","EffectRow6"),
        ("NameRow7_2","TNRow7","RangeRow7","TargetRow7","DurationRow7","EffectRow7"),
        ("NameRow8",  "TNRow8","RangeRow8","TargetRow8","DurationRow8","EffectRow8"),
    ]
    row_idx = 0
    for spell in named_spells:
        if row_idx >= len(sp_fields):
            break
        effect_lines = wrap_to_lines(spell.get("effect", ""), width=44)
        # First physical row: all columns
        nf, tnf, rf, tgf, df, ef = sp_fields[row_idx]
        f(nf,  spell.get("name",     ""), page=2)
        f(tnf, spell.get("tn",       ""), page=2)
        f(rf,  spell.get("range",    ""), page=2)
        f(tgf, spell.get("target",   ""), page=2)
        f(df,  spell.get("duration", ""), page=2)
        f(ef,  effect_lines[0],           page=2)
        row_idx += 1
        # Overflow rows: Effect only, other columns blank
        for extra_line in effect_lines[1:]:
            if row_idx >= len(sp_fields):
                break
            nf2, tnf2, rf2, tgf2, df2, ef2 = sp_fields[row_idx]
            f(nf2,  "", page=2); f(tnf2, "", page=2); f(rf2,  "", page=2)
            f(tgf2, "", page=2); f(df2,  "", page=2)
            f(ef2, extra_line, page=2)
            row_idx += 1
    # Clear any remaining rows
    for nf, tnf, rf, tgf, df, ef in sp_fields[row_idx:]:
        f(nf,  "", page=2); f(tnf, "", page=2); f(rf,  "", page=2)
        f(tgf, "", page=2); f(df,  "", page=2); f(ef,  "", page=2)

    f("Sin", data.get("sin", "0"), page=2)

    return fv


def resolve_weapon_damage(damage_str, strength):
    """Replace SB in a damage string with the computed Strength Bonus value.
    E.g. '+SB+4' with S=35 (SB=3) → '+7'. Returns original string if no SB token.
    """
    if not damage_str or "SB" not in damage_str.upper():
        return damage_str
    try:
        sb = int(strength) // 10
        expr = re.sub(r'\bSB\b', str(sb), damage_str, flags=re.IGNORECASE)
        # Only evaluate if the result is a safe arithmetic expression
        if re.match(r'^[+\-\d]+$', expr):
            result = eval(expr)  # safe: only digits and +/-
            return f"+{result}" if result >= 0 else str(result)
    except Exception:
        pass
    return damage_str


def abbr_group(g):
    """Strip 'Melee (...)' / 'Ranged (...)' prefix, returning just the inner word.
    E.g. 'Ranged (Blackpowder)' → 'Blackpowder', 'Melee (Two-Handed)' → 'Two-Handed'.
    """
    m = re.match(r'^(?:Melee|Ranged)\s*\((.+)\)$', g.strip(), re.IGNORECASE)
    return m.group(1) if m else g.strip()


def wrap_to_lines(text, width=44):
    """Word-wrap *text* and return a **list** of line strings (one per PDF row).
    Each line is at most *width* characters wide.
    """
    if not text:
        return [""]
    words = text.split()
    lines, line, cur = [], [], 0
    for w in words:
        needed = len(w) + (1 if line else 0)
        if cur + needed > width and line:
            lines.append(" ".join(line))
            line, cur = [w], len(w)
        else:
            line.append(w)
            cur += needed
    if line:
        lines.append(" ".join(line))
    return lines if lines else [""]


def wrap_text(text, width=52):
    """Legacy wrapper — joins wrap_to_lines with newlines (kept for any callers)."""
    return "\n".join(wrap_to_lines(text, width))


def _patch_field_properties(writer):
    """
    Fix Group and Effect field appearance.
    - GroupRow*: auto-size font + centered text (the column border stays put,
      so we keep the original rect and just abbreviate the value at fill time).
    - EffectRow*: auto-size font (each row gets one line-chunk of the effect text).
    Must be called BEFORE update_page_form_field_values.
    """
    from pypdf.generic import (
        NameObject, NumberObject, TextStringObject
    )

    AUTO_DA = TextStringObject('/Helv 0 Tf 0 g')   # font-size 0 = auto-fit

    page2 = writer.pages[1]
    annots = page2.get('/Annots', [])
    if not annots:
        return

    for annot_ref in annots:
        try:
            annot = annot_ref.get_object()
        except Exception:
            continue
        name = str(annot.get('/T', ''))

        if name.startswith('GroupRow'):
            # Auto-size font so abbreviated group name fits the narrow column.
            # /Q = 1 → centered horizontally (matches the "Group" header).
            annot[NameObject('/DA')] = AUTO_DA
            annot[NameObject('/Q')]  = NumberObject(1)
            annot.pop(NameObject('/AP'), None)

        elif name == 'NameRow1':
            # Advanced skill names can be long (e.g. "Lore (Reiklander)").
            # Auto-size ensures each line shrinks to fit the 67pt column.
            annot[NameObject('/DA')] = AUTO_DA
            annot.pop(NameObject('/AP'), None)

        elif name.startswith('EffectRow') or name.startswith('QualitiesRow'):
            # Auto-size font; each row receives one wrapped line of text.
            annot[NameObject('/DA')] = AUTO_DA
            annot.pop(NameObject('/AP'), None)


def _count_arm_rows(named_armour):
    """Return total physical PDF rows required (name row + quality-overflow rows)."""
    return sum(
        len(wrap_to_lines(a.get("qualities", ""), width=26))
        for a in named_armour
    )


def _count_spell_rows(named_spells):
    """Return total physical rows needed by all spells.

    Each spell takes at least 1 row.  Long effect text wraps into additional
    rows (same width used when filling the main sheet: 44 chars).
    """
    total = 0
    for s in named_spells:
        effect_lines = wrap_to_lines(s.get("effect", ""), width=44)
        total += max(1, len(effect_lines))
    return total


def fill_armor_page(data):
    """Fill armorpage_fillable.pdf with the full armour table, AP boxes, and weapons.
    Returns bytes of the filled PDF, or None if the template is not available.
    """
    from pypdf import PdfReader, PdfWriter

    _log(f"fill_armor_page: ARMOR_PAGE_TEMPLATE={ARMOR_PAGE_TEMPLATE!r}")
    if not ARMOR_PAGE_TEMPLATE:
        return None

    reader = PdfReader(ARMOR_PAGE_TEMPLATE)
    writer = PdfWriter(clone_from=reader)
    _log(f"fill_armor_page: template opened OK, {len(reader.pages)} page(s)")
    fv = {}

    # ── Armour table (up to 24 rows) ────────────────────────────────────────────
    armour       = data.get("armour", [])
    named_armour = [a for a in armour if a.get("name", "").strip()]
    MAX_ARM_ROWS = 24
    arm_row      = 1

    for piece in named_armour:
        if arm_row > MAX_ARM_ROWS:
            break
        qual_lines = wrap_to_lines(piece.get("qualities", ""), width=26)
        fv[f"arm_name_{arm_row}"]      = piece.get("name", "")
        fv[f"arm_loc_{arm_row}"]       = piece.get("loc",  "")
        fv[f"arm_enc_{arm_row}"]       = piece.get("enc",  "")
        fv[f"arm_ap_{arm_row}"]        = piece.get("ap",   "")
        fv[f"arm_qualities_{arm_row}"] = qual_lines[0]
        arm_row += 1
        for extra in qual_lines[1:]:
            if arm_row > MAX_ARM_ROWS:
                break
            fv[f"arm_name_{arm_row}"]      = ""
            fv[f"arm_loc_{arm_row}"]       = ""
            fv[f"arm_enc_{arm_row}"]       = ""
            fv[f"arm_ap_{arm_row}"]        = ""
            fv[f"arm_qualities_{arm_row}"] = extra
            arm_row += 1

    # Clear unused rows
    for r in range(arm_row, MAX_ARM_ROWS + 1):
        fv[f"arm_name_{r}"]      = ""
        fv[f"arm_loc_{r}"]       = ""
        fv[f"arm_enc_{r}"]       = ""
        fv[f"arm_ap_{r}"]        = ""
        fv[f"arm_qualities_{r}"] = ""

    # ── Armour Points boxes ──────────────────────────────────────────────────────
    # Mapping: data key → armorpage field name (matched by hit-location range number)
    # apRarm / "1024" in main sheet = 10-24 range = "Left arm (secondary)"  → ap_left_arm
    # apLarm / "2544" in main sheet = 25-44 range = "Right arm (primary)"   → ap_right_arm
    fv["ap_head"]      = str(data.get("apHead",   "") or "")
    fv["ap_left_arm"]  = str(data.get("apRarm",   "") or "")   # 10-24
    fv["ap_right_arm"] = str(data.get("apLarm",   "") or "")   # 25-44
    fv["ap_body"]      = str(data.get("apBody",   "") or "")
    fv["ap_right_leg"] = str(data.get("apRleg",   "") or "")   # 90-00
    fv["ap_left_leg"]  = str(data.get("apLleg",   "") or "")   # 80-89
    fv["ap_shield"]    = str(data.get("apShield", "") or "")

    # ── Wounds ──────────────────────────────────────────────────────────────────
    fv["wounds_sb"]    = str(data.get("wSb",    "") or "")
    fv["wounds_tb2"]   = str(data.get("wTb2",   "") or "")
    fv["wounds_wpb"]   = str(data.get("wWpb",   "") or "")
    fv["wounds_hardy"] = str(data.get("wHardy", "") or "")
    fv["wounds_max"]   = str(data.get("wMax",   "") or "")

    # ── Weapons table (7 rows) ──────────────────────────────────────────────────
    _s2 = data.get("chars", {}).get("s", {})
    try:
        _strength_cur2 = int(_s2.get("i", 0)) + int(_s2.get("a", 0))
    except (ValueError, TypeError):
        _strength_cur2 = 0

    weapons = data.get("weapons", [])
    for i in range(7):
        r   = i + 1
        row = weapons[i] if i < len(weapons) else {}
        fv[f"wpn_name_{r}"]      = row.get("name",      "")
        fv[f"wpn_group_{r}"]     = abbr_group(row.get("group", ""))
        fv[f"wpn_enc_{r}"]       = row.get("enc",       "")
        fv[f"wpn_range_{r}"]     = row.get("range",     "")
        fv[f"wpn_damage_{r}"]    = resolve_weapon_damage(row.get("damage", ""), _strength_cur2)
        fv[f"wpn_qualities_{r}"] = row.get("qualities", "")

    writer.update_page_form_field_values(writer.pages[0], fv, auto_regenerate=True)
    writer.set_need_appearances_writer(True)

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.read()


def fill_talent_page(data, fill_talents=True, fill_trappings=True):
    """Fill talentextra_fillable.pdf with overflow talents and/or trappings.
    fill_talents / fill_trappings control which sections are populated.
    Returns bytes of the filled PDF, or None if the template is unavailable.
    """
    from pypdf import PdfReader, PdfWriter

    if not TALENT_PAGE_TEMPLATE:
        return None

    reader = PdfReader(TALENT_PAGE_TEMPLATE)
    writer = PdfWriter(clone_from=reader)
    fv = {}

    # ── Talents (22 individual rows) ─────────────────────────────────────────
    talents       = data.get("talents", [])
    named_talents = [t for t in talents if t.get("name", "").strip()]
    for i in range(22):
        row = i + 1
        t = named_talents[i] if (fill_talents and i < len(named_talents)) else {}
        fv[f"tal_name_{row}"]  = t.get("name",  "")
        fv[f"tal_times_{row}"] = t.get("times", "")
        fv[f"tal_desc_{row}"]  = t.get("desc",  "")

    # ── Trappings distributed across 3 columns of 15 rows each ───────────────
    # Packed items get a 🐴 prefix and blank enc (enc is on the mount, not the player).
    trappings       = data.get("trappings", [])
    named_trappings = [t for t in trappings if t.get("name", "").strip()]
    TRAP_ROWS = 15
    for ci in range(3):
        col_num = ci + 1
        for ri in range(TRAP_ROWS):
            row  = ri + 1
            idx  = ci * TRAP_ROWS + ri
            item = named_trappings[idx] if (fill_trappings and idx < len(named_trappings)) else {}
            name = item.get("name", "")
            enc  = item.get("enc",  "")
            if item.get("stowed"):
                name = "🛒 " + name
                enc  = ""   # enc is stowed in vehicle
            elif item.get("packed"):
                name = "🐴 " + name
                enc  = ""   # enc is carried by mount, not counted here
            fv[f"trap{col_num}_name_{row}"] = name
            fv[f"trap{col_num}_enc_{row}"]  = enc

    writer.update_page_form_field_values(writer.pages[0], fv, auto_regenerate=True)
    writer.set_need_appearances_writer(True)

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.read()


def fill_spell_page(data):
    """Fill extraspells_fillable.pdf with all spells and prayers.

    Long effect text is wrapped across consecutive rows (same strategy as the
    main sheet): the overflow rows leave Name/TN/Range/Target/Duration blank
    and only populate the Effect column.

    Returns bytes of the filled PDF, or None if the template is unavailable.
    """
    from pypdf import PdfReader, PdfWriter

    if not EXTRA_SPELLS_TEMPLATE:
        return None

    reader = PdfReader(EXTRA_SPELLS_TEMPLATE)
    writer = PdfWriter(clone_from=reader)
    fv = {}

    spells       = data.get("spells", [])
    named_spells = [s for s in spells if s.get("name", "").strip()]
    MAX_SPELL_ROWS = 36   # rows in the regenerated template

    # Pre-fill every field with empty string so no stale data appears
    for row in range(1, MAX_SPELL_ROWS + 1):
        fv[f"sp_name_{row}"]     = ""
        fv[f"sp_tn_{row}"]       = ""
        fv[f"sp_range_{row}"]    = ""
        fv[f"sp_target_{row}"]   = ""
        fv[f"sp_duration_{row}"] = ""
        fv[f"sp_effect_{row}"]   = ""

    row_idx = 0
    for sp in named_spells:
        if row_idx >= MAX_SPELL_ROWS:
            break
        effect_lines = wrap_to_lines(sp.get("effect", ""), width=60)
        row = row_idx + 1
        # First physical row: all columns
        fv[f"sp_name_{row}"]     = sp.get("name",     "")
        fv[f"sp_tn_{row}"]       = sp.get("tn",       "")
        fv[f"sp_range_{row}"]    = sp.get("range",    "")
        fv[f"sp_target_{row}"]   = sp.get("target",   "")
        fv[f"sp_duration_{row}"] = sp.get("duration", "")
        fv[f"sp_effect_{row}"]   = effect_lines[0]
        row_idx += 1
        # Overflow rows: Effect column only, other columns blank
        for extra_line in effect_lines[1:]:
            if row_idx >= MAX_SPELL_ROWS:
                break
            row = row_idx + 1
            fv[f"sp_effect_{row}"] = extra_line
            row_idx += 1

    fv["notes"] = ""

    writer.update_page_form_field_values(writer.pages[0], fv, auto_regenerate=True)
    writer.set_need_appearances_writer(True)

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.read()


def _log(msg):
    """Append a timestamped line to wfrp_export.log next to the EXE."""
    try:
        log_path = os.path.join(EXE_DIR, "wfrp_export.log")
        with open(log_path, "a", encoding="utf-8") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def fill_mount_page(data):
    """Generate a styled mount sheet page using reportlab drawn over blank.pdf.
    Returns bytes of the finished PDF page, or None if prerequisites are missing.

    Coordinate model: cy = cursor at the TOP of the next element to draw.
    All drawing functions consume cy downward (subtract from it).
    section_bar: bar top = cy, bar bottom = cy - BAR_H.
    labeled_field: label just below cy, box below label.
    This guarantees no element ever overlaps the bar drawn above it.
    """
    mount = data.get("mount", {})
    if not mount:
        return None
    has_content = (mount.get("type") or mount.get("customName") or
                   mount.get("equipment") or mount.get("traits") or mount.get("notes"))
    if not has_content:
        return None
    if not BLANK_PDF:
        _log("blank.pdf not found — mount page skipped")
        return None

    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.colors import Color
        from reportlab.lib.utils import simpleSplit
    except ImportError:
        _log("reportlab not available — mount page skipped")
        return None

    from pypdf import PdfReader, PdfWriter

    # ── Page geometry ──────────────────────────────────────────────────────────
    W, H = 609.6, 765.36
    LM   = 50.0          # left margin
    RM   = 560.0         # right margin
    CW   = RM - LM       # 510 pts usable width

    # Layout constants
    BAR_H   = 14   # section header bar height
    LBL_H   = 10   # space reserved for field label above each box
    BOX_H   = 16   # field box height
    GAP     = 9    # standard gap between sections
    ROW_H   = 15   # equipment table row height

    # ── Palette ────────────────────────────────────────────────────────────────
    INK      = Color(0.08, 0.06, 0.02)
    HDR_BG   = Color(0.13, 0.10, 0.05)
    HDR_FG   = Color(0.93, 0.85, 0.55)
    FIELD_BG = Color(0.97, 0.94, 0.88)
    BORDER   = Color(0.40, 0.27, 0.06)
    GOLD     = Color(0.72, 0.52, 0.03)
    DIVIDER  = Color(0.55, 0.38, 0.08)
    SUB_BG   = Color(0.22, 0.17, 0.07)

    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=(W, H))

    # ── Drawing primitives ─────────────────────────────────────────────────────

    def hline(cy, x1=LM, x2=RM, color=DIVIDER, lw=0.7):
        c.setStrokeColor(color); c.setLineWidth(lw)
        c.line(x1, cy, x2, cy)

    def section_bar(cy, title):
        """Draw dark bar with top at cy. Returns cy - BAR_H (cursor at bar bottom)."""
        c.setFillColor(HDR_BG)
        c.rect(LM, cy - BAR_H, CW, BAR_H, fill=1, stroke=0)
        c.setFillColor(HDR_FG); c.setFont("Times-Bold", 8)
        c.drawString(LM + 5, cy - BAR_H + 4, title.upper())
        return cy - BAR_H

    def labeled_field(label, value, x, cy, w, bold_val=False, val_sz=9.5):
        """Label at cy, box below. Draws within cy → cy - LBL_H - BOX_H."""
        # label sits in the LBL_H band just below cy
        c.setFillColor(GOLD); c.setFont("Times-Bold", 6.5)
        c.drawString(x, cy - LBL_H + 2, label)
        # box below label
        box_bot = cy - LBL_H - BOX_H
        c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.rect(x, box_bot, w, BOX_H, fill=1, stroke=1)
        c.setFillColor(INK)
        c.setFont("Times-Bold" if bold_val else "Times-Roman", val_sz)
        c.drawString(x + 4, box_bot + 4.5, str(value or ""))

    def stat_cell(label, value, x, cy, w):
        """Centred stat cell. Draws within cy → cy - LBL_H - BOX_H."""
        c.setFillColor(GOLD); c.setFont("Times-Bold", 6.5)
        c.drawCentredString(x + w / 2, cy - LBL_H + 2, label)
        box_bot = cy - LBL_H - BOX_H
        c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.rect(x, box_bot, w, BOX_H, fill=1, stroke=1)
        c.setFillColor(INK); c.setFont("Times-Bold", 10)
        c.drawCentredString(x + w / 2, box_bot + 4.5, str(value or ""))

    FIELD_TOTAL = LBL_H + BOX_H   # vertical space consumed by one labeled_field row

    # ── Pre-compute from equipment ─────────────────────────────────────────────
    _AP_DB    = {"barding, full plate": 5, "barding, heavy mail": 3,
                 "barding, light leather": 1}
    _CARRY_DB = {"saddlebags (pair)": 8}
    equipment        = [e for e in (mount.get("equipment") or []) if e.get("name", "").strip()]
    packed_trappings = [t for t in data.get("trappings", [])
                        if t.get("packed") and t.get("name", "").strip()]
    ap_total   = sum(_AP_DB.get(e["name"].strip().lower(), 0)    for e in equipment)
    # carry_bonus = saddlebag trapping capacity (NOT added to mount max enc)
    saddle_cap = sum(_CARRY_DB.get(e["name"].strip().lower(), 0) for e in equipment)
    enc_equip  = sum(float(e.get("enc") or 0) for e in equipment)
    enc_packed = sum(float(t.get("enc") or 0) for t in packed_trappings)
    enc_total  = enc_equip + enc_packed   # combined weight for dragging/pulling
    try:
        sb = int(mount.get("s") or 0) // 10
    except (ValueError, TypeError):
        sb = 0
    enc_max    = sb * 10                  # mount max enc = SB×10 only
    enc_remain = enc_max - enc_total

    # ── Layout ─────────────────────────────────────────────────────────────────
    cy = 716.0   # cursor starts near top of content area

    # ── Title ─────────────────────────────────────────────────────────────────
    c.setFillColor(INK); c.setFont("Times-Bold", 22)
    c.drawCentredString(W / 2, cy - 22, "MOUNT")
    cy -= 32
    hline(cy, lw=1.4, color=DIVIDER)
    cy -= 12

    # ── IDENTITY ──────────────────────────────────────────────────────────────
    cy = section_bar(cy, "Identity")
    cy -= 7   # breathing room below bar before labels
    half = CW / 2 - 4
    labeled_field("Mount Type",   mount.get("type",       ""), LM,            cy, half)
    labeled_field("Custom Name",  mount.get("customName", ""), LM + half + 8, cy, half)
    cy -= FIELD_TOTAL + GAP + 4
    hline(cy); cy -= GAP

    # ── CHARACTERISTICS ───────────────────────────────────────────────────────
    cy = section_bar(cy, "Characteristics")
    cy -= 7
    stats = [("M",   mount.get("m",   "")), ("WS",  mount.get("ws",  "")),
             ("BS",  mount.get("bs",  "")), ("S",   mount.get("s",   "")),
             ("T",   mount.get("t",   "")), ("I",   mount.get("i",   "")),
             ("Ag",  mount.get("ag",  "")), ("Dex", mount.get("dex", "")),
             ("Int", mount.get("int", "")), ("WP",  mount.get("wp",  "")),
             ("Fel", mount.get("fel", ""))]
    cell_w = CW / len(stats)
    for idx, (lbl, val) in enumerate(stats):
        stat_cell(lbl, val, LM + idx * cell_w, cy, cell_w - 1.5)
    cy -= FIELD_TOTAL + 8

    # Size / Wounds / Advantage / AP row
    labeled_field("Size",          mount.get("size", ""),  LM,        cy, 88)
    labeled_field("Wounds (Max)",  mount.get("wmax", ""),  LM + 96,   cy, 88, bold_val=True)
    labeled_field("Wounds (Cur.)", mount.get("wcur", ""),  LM + 192,  cy, 88, bold_val=True)
    labeled_field("Advantage",     mount.get("adv",  ""),  LM + 288,  cy, 62, bold_val=True)
    labeled_field("AP (Barding)",  str(ap_total) if ap_total else "0",
                  LM + 358, cy, 62, bold_val=True)
    cy -= FIELD_TOTAL + GAP + 4
    hline(cy); cy -= GAP

    # ── TRAITS & SKILLS ───────────────────────────────────────────────────────
    cy = section_bar(cy, "Traits & Skills")
    cy -= 7
    col_w = CW / 2 - 4

    def text_block(label, text, x, top_cy, w):
        """Two-column text area. Returns height consumed (label + box)."""
        lines = [s.strip() for s in (text or "").replace(";", ",").split(",") if s.strip()]
        lbl_sp = 11
        box_h  = max(40, min(70, len(lines) * 13 + 12))
        c.setFillColor(GOLD); c.setFont("Times-Bold", 7)
        c.drawString(x, top_cy - lbl_sp + 2, label.upper())
        box_bot = top_cy - lbl_sp - box_h
        c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.rect(x, box_bot, w, box_h, fill=1, stroke=1)
        c.setFillColor(INK); c.setFont("Times-Roman", 9)
        ly = box_bot + box_h - 13
        for ln in lines:
            if ly < box_bot + 4: break
            c.drawString(x + 4, ly, ln); ly -= 13
        return lbl_sp + box_h

    trait_h = text_block("Traits", mount.get("traits", ""), LM,             cy, col_w)
    skill_h = text_block("Skills", mount.get("skills", ""), LM + col_w + 8, cy, col_w)
    cy -= max(trait_h, skill_h) + GAP + 4
    hline(cy); cy -= GAP

    # ── EQUIPMENT & BARDING ───────────────────────────────────────────────────
    cy = section_bar(cy, "Equipment & Barding")
    name_w = CW - 64 - 4

    # Sub-header row
    cy -= 2
    c.setFillColor(SUB_BG)
    c.rect(LM, cy - 13, name_w, 13, fill=1, stroke=0)
    c.rect(LM + name_w + 4, cy - 13, 64, 13, fill=1, stroke=0)
    c.setFillColor(HDR_FG); c.setFont("Times-Bold", 8)
    c.drawString(LM + 4, cy - 10, "ITEM")
    c.drawCentredString(LM + name_w + 4 + 32, cy - 10, "ENC")
    cy -= 13

    for item in equipment:
        c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.35)
        c.rect(LM, cy - ROW_H, name_w, ROW_H, fill=1, stroke=1)
        c.rect(LM + name_w + 4, cy - ROW_H, 64, ROW_H, fill=1, stroke=1)
        c.setFillColor(INK); c.setFont("Times-Roman", 9)
        c.drawString(LM + 4, cy - ROW_H + 4.5, item.get("name", ""))
        enc_v = item.get("enc")
        enc_s = str(enc_v) if enc_v not in (None, "") else ""
        c.drawCentredString(LM + name_w + 4 + 32, cy - ROW_H + 4.5, enc_s)
        cy -= ROW_H

    # Packed trappings from player — shown with a gold dot indicator
    if packed_trappings:
        cy -= 2
        c.setFillColor(SUB_BG)
        c.rect(LM, cy - 13, name_w + 68, 13, fill=1, stroke=0)
        c.setFillColor(GOLD); c.setFont("Times-Bold", 7)
        c.drawString(LM + 4, cy - 10, "PACKED TRAPPINGS (PLAYER ITEMS)")
        cy -= 13
        for t in packed_trappings:
            c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.35)
            c.rect(LM, cy - ROW_H, name_w, ROW_H, fill=1, stroke=1)
            c.rect(LM + name_w + 4, cy - ROW_H, 64, ROW_H, fill=1, stroke=1)
            # Small gold dot as "packed" icon
            c.setFillColor(GOLD); c.setStrokeColor(GOLD); c.setLineWidth(0)
            c.circle(LM + 7, cy - ROW_H + ROW_H / 2, 3, fill=1, stroke=0)
            c.setFillColor(INK); c.setFont("Times-Roman", 9)
            c.drawString(LM + 14, cy - ROW_H + 4.5, t.get("name", ""))
            enc_v = t.get("enc")
            enc_s = str(enc_v) if enc_v not in (None, "") else ""
            c.drawCentredString(LM + name_w + 4 + 32, cy - ROW_H + 4.5, enc_s)
            cy -= ROW_H

    cy -= GAP; hline(cy); cy -= GAP

    # ── ENCUMBRANCE ───────────────────────────────────────────────────────────
    cy = section_bar(cy, "Encumbrance")
    cy -= 7
    # Row 1: Equipment Enc / Packed Trappings (X / cap)
    # Row 2: Max (SB×10) / Remaining
    fw2 = CW / 2 - 6
    labeled_field("Equipment Enc.",      f"{enc_equip:g}",  LM,        cy, fw2)
    if packed_trappings and saddle_cap:
        pack_lbl = f"Packed ({enc_packed:g} / {saddle_cap} enc)"
    elif packed_trappings:
        pack_lbl = f"Packed Trappings"
    else:
        pack_lbl = "Packed Trappings"
    labeled_field(pack_lbl, f"{enc_packed:g}" if packed_trappings else "—",
                  LM + CW / 2 + 6, cy, fw2)
    cy -= FIELD_TOTAL + GAP
    labeled_field("Total Enc. (dragging/weight)", f"{enc_total:g}", LM,        cy, fw2, bold_val=True)
    labeled_field("Max Enc. (SB×10)",        str(enc_max),     LM + CW/2+6, cy, fw2)
    cy -= FIELD_TOTAL + GAP
    labeled_field("Remaining",                    f"{enc_remain:g}", LM,        cy, fw2, bold_val=True)
    cy -= FIELD_TOTAL + GAP + 4
    hline(cy); cy -= GAP

    # ── NOTES ─────────────────────────────────────────────────────────────────
    cy = section_bar(cy, "Notes")
    cy -= 5
    notes_h  = max(50, cy - 46)   # fill remaining safe area
    notes_bot = cy - notes_h
    c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.4)
    c.rect(LM, notes_bot, CW, notes_h, fill=1, stroke=1)
    notes_text = mount.get("notes", "") or ""
    if notes_text:
        c.setFillColor(INK); c.setFont("Times-Roman", 9.5)
        for nl in simpleSplit(notes_text, "Times-Roman", 9.5, CW - 10):
            if cy - 13 < notes_bot + 4: break
            cy -= 13
            c.drawString(LM + 5, cy, nl)

    c.save()
    buf.seek(0)
    overlay_bytes = buf.read()

    # ── Merge overlay onto blank.pdf border ───────────────────────────────────
    blank_reader   = PdfReader(BLANK_PDF)
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
    writer         = PdfWriter()
    page           = blank_reader.pages[0]
    page.merge_page(overlay_reader.pages[0])
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()


def fill_vehicle_page(data):
    """Generate a vehicle sheet page using reportlab over blank.pdf.
    Returns bytes or None if no vehicle data / prerequisites missing."""
    vehicle = data.get("vehicle", {})
    if not vehicle:
        return None
    has_content = (vehicle.get("type") or vehicle.get("customName") or
                   vehicle.get("cargo") or vehicle.get("notes"))
    if not has_content:
        return None
    if not BLANK_PDF:
        _log("blank.pdf not found — vehicle page skipped")
        return None
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.colors import Color
        from reportlab.lib.utils import simpleSplit
    except ImportError:
        _log("reportlab not available — vehicle page skipped")
        return None
    from pypdf import PdfReader, PdfWriter

    # ── Page geometry (matches mount page exactly) ────────────────────────────
    W, H = 609.6, 765.36
    LM   = 50.0
    RM   = 560.0
    CW   = RM - LM       # 510 pts usable width
    # Layout constants (matches mount page)
    BAR_H = 14
    LBL_H = 10
    BOX_H = 16
    GAP   = 9
    ROW_H = 15
    FIELD_TOTAL = LBL_H + BOX_H   # 26
    # Palette (matches mount page)
    INK     = Color(0.08, 0.06, 0.02)
    HDR_BG  = Color(0.13, 0.10, 0.05)
    HDR_FG  = Color(0.93, 0.85, 0.55)
    FIELD_BG = Color(0.97, 0.94, 0.88)
    BORDER  = Color(0.40, 0.27, 0.06)
    GOLD    = Color(0.72, 0.52, 0.03)
    SUB_BG  = Color(0.22, 0.17, 0.07)

    # Vessel upgrade/weapon key → display name lookup
    _VESSEL_UPG_NAMES = {
        'armour_bronze':'Armour Plating (Bronze)', 'armour_iron':'Armour Plating (Iron)',
        'racing_hull':'Racing Hull', 'smoothing':'Smoothing',
        'broad_rudder':'Broad Rudder', 'fore_aft_rudder':'Fore-and-Aft Rudder',
        'water_brakes':'Water Brakes', 'armoured_walls':'Armoured Walls',
        'gun_ports_small':'Gun Ports (Small)', 'gun_ports_large':'Gun Ports (Large)',
        'luxury_cabins':'Luxury Cabins', 'raised_gunwales':'Raised Gunwales',
        'stripped':'Stripped', 'flying_jib':'Flying Jib', 'racing_rig':'Racing Rig',
        'closed_rowlocks':'Closed Rowlocks', 'spoons':'Spoons',
        'steam_engine':'Steam Engine', 'magical':'Magical Propulsion',
        'musket_rest':'Musket Rest', 'ram':'Ram',
    }
    _VESSEL_WPN_NAMES = {
        'ballista_small':'Ballista (Small)', 'ballista_medium':'Ballista (Medium)',
        'cannon_medium':'Cannon (Medium)',   'catapult_small':'Catapult (Small)',
        'catapult_medium':'Catapult (Medium)','catapult_large':'Catapult (Large)',
        'mortar':'Mortar',                   'swivel_gun':'Swivel Gun',
    }
    _VESSEL_WPN_STATS = {
        'ballista_small':('100','×12'), 'ballista_medium':('50','×10'),
        'cannon_medium':('75','×10'),   'catapult_small':('50','×10'),
        'catapult_medium':('75','×12'), 'catapult_large':('100','×14'),
        'mortar':('100','+10'),         'swivel_gun':('50','+9'),
    }

    # ── Pre-compute enc ───────────────────────────────────────────────────────
    stowed_trappings = [t for t in data.get("trappings", [])
                        if t.get("stowed") and t.get("name", "").strip()]
    extra_cargo      = [c for c in (vehicle.get("cargo") or []) if c.get("name", "").strip()]
    vessel_upgrades  = [u for u in (vehicle.get("vesselUpgrades") or []) if u.get("key")]
    vessel_weapons   = [w for w in (vehicle.get("vesselWeapons")  or []) if w.get("key")]
    enc_empty    = float(vehicle.get("encEmpty") or 0)
    enc_upgrades = sum(float(u.get("enc") or 0) for u in vessel_upgrades)
    enc_upgrades += sum(float(w.get("enc") or 0) for w in vessel_weapons)
    enc_stowed   = sum(float(t.get("enc") or 0) for t in stowed_trappings)
    enc_cargo    = sum(float(c.get("enc") or 0) for c in extra_cargo)
    enc_total    = enc_empty + enc_upgrades + enc_stowed + enc_cargo
    capacity     = float(vehicle.get("capacity") or 0)
    cap_remain   = capacity - (enc_stowed + enc_cargo)

    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=(W, H))

    def hline(cy, x1=LM, x2=RM, lw=0.7):
        c.setStrokeColor(BORDER); c.setLineWidth(lw)
        c.line(x1, cy, x2, cy)

    def section_bar(cy, title):
        c.setFillColor(HDR_BG)
        c.rect(LM, cy - BAR_H, CW, BAR_H, fill=1, stroke=0)
        c.setFillColor(HDR_FG); c.setFont("Times-Bold", 8)
        c.drawString(LM + 5, cy - BAR_H + 4, title.upper())
        return cy - BAR_H

    def labeled_field(label, value, x, cy, w, bold_val=False, val_sz=9.5):
        c.setFillColor(GOLD); c.setFont("Times-Bold", 6.5)
        c.drawString(x, cy - LBL_H + 2, label)
        box_bot = cy - LBL_H - BOX_H
        c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.rect(x, box_bot, w, BOX_H, fill=1, stroke=1)
        c.setFillColor(INK)
        c.setFont("Times-Bold" if bold_val else "Times-Roman", val_sz)
        c.drawString(x + 4, box_bot + 4.5, str(value or ""))

    cy = 716.0   # same as mount page — clear of top decorative border

    # ── Title ─────────────────────────────────────────────────────────────────
    veh_label = (vehicle.get("customName") or vehicle.get("type") or "Vehicle").strip()
    if vehicle.get("customName") and vehicle.get("type"):
        veh_label = f"{vehicle['customName']} ({vehicle['type']})"
    c.setFillColor(INK); c.setFont("Times-Bold", 22)
    c.drawCentredString(W / 2, cy - 22, veh_label)
    cy -= 32
    hline(cy, lw=1.4)
    cy -= 12

    # ── Stats ────────────────────────────────────────────────────────────────
    cy = section_bar(cy, "Statistics")
    cy -= GAP
    fw2 = CW / 2 - 6
    def g(v): return f"{v:g}" if isinstance(v, float) and v != int(v) else str(int(v)) if isinstance(v, (int, float)) else str(v or "")
    # Row 1: Type | Motive Power
    labeled_field("Type",         vehicle.get("type","") or "",         LM,          cy, fw2)
    labeled_field("Motive Power", vehicle.get("motivepower","") or "",  LM+CW/2+6,  cy, fw2)
    cy -= FIELD_TOTAL + GAP
    # Row 2: Toughness | Wounds
    labeled_field("Toughness", str(vehicle.get("toughness","") or ""), LM,          cy, fw2)
    labeled_field("Wounds",    str(vehicle.get("wounds","")    or ""), LM+CW/2+6,  cy, fw2)
    cy -= FIELD_TOTAL + GAP
    # Row 3: Move | Length (only if present)
    move_val   = str(vehicle.get("move","")   or "")
    length_val = str(vehicle.get("length","") or "")
    if move_val or length_val:
        labeled_field("Move",         move_val,   LM,          cy, fw2)
        labeled_field("Length (ft)",  length_val, LM+CW/2+6,  cy, fw2)
        cy -= FIELD_TOTAL + GAP
    # Row 4: Passengers (if present)
    if vehicle.get("passengers"):
        labeled_field("Passengers", str(vehicle["passengers"]), LM, cy, fw2)
        cy -= FIELD_TOTAL + GAP

    # ── Draught Animals ──────────────────────────────────────────────────────
    draught_names = vehicle.get("draughtMountNames") or []
    if draught_names:
        cy = section_bar(cy, "Draught Animals")
        cy -= GAP
        c.setFillColor(INK); c.setFont("Times-Roman", 9)
        for dn in draught_names:
            cy -= 12
            c.drawString(LM + 8, cy, "• " + dn)
        cy -= GAP

    # ── Vessel Modifications & Weapons ───────────────────────────────────────
    if vessel_upgrades or vessel_weapons:
        cy = section_bar(cy, "Vessel Modifications")
        cy -= GAP
        # columns: Name | Enc | Cost(GC)
        col_name = CW - 120
        col_enc  = 50
        col_cost = 68
        # sub-header
        c.setFillColor(SUB_BG)
        c.rect(LM,                           cy - 13, col_name,  13, fill=1, stroke=0)
        c.rect(LM + col_name + 2,            cy - 13, col_enc,   13, fill=1, stroke=0)
        c.rect(LM + col_name + col_enc + 4,  cy - 13, col_cost,  13, fill=1, stroke=0)
        c.setFillColor(HDR_FG); c.setFont("Times-Bold", 8)
        c.drawString(LM + 4,                       cy - 10, "MODIFICATION")
        c.drawCentredString(LM + col_name + 2 + col_enc / 2,         cy - 10, "ENC")
        c.drawCentredString(LM + col_name + col_enc + 4 + col_cost/2, cy - 10, "COST (GC)")
        cy -= 13
        for u in vessel_upgrades:
            name = _VESSEL_UPG_NAMES.get(u.get("key",""), u.get("key","").replace("_"," ").title())
            qty  = int(u.get("qty") or 1)
            if qty > 1:
                name = f"{name} ×{qty}"
            enc_v = u.get("enc","")
            c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.35)
            c.rect(LM,                           cy - ROW_H, col_name,  ROW_H, fill=1, stroke=1)
            c.rect(LM + col_name + 2,            cy - ROW_H, col_enc,   ROW_H, fill=1, stroke=1)
            c.rect(LM + col_name + col_enc + 4,  cy - ROW_H, col_cost,  ROW_H, fill=1, stroke=1)
            c.setFillColor(INK); c.setFont("Times-Roman", 9)
            c.drawString(LM + 6, cy - ROW_H + 4.5, name)
            c.drawCentredString(LM + col_name + 2 + col_enc / 2,
                                cy - ROW_H + 4.5, str(enc_v) if enc_v not in (None, "") else "")
            cy -= ROW_H
        # Weapons sub-section
        if vessel_weapons:
            # mini sub-header for weapons — narrower columns (Name | Rng | Dmg | Enc | Cost | Con.)
            col_rng  = 34; col_dmg = 34; col_e2 = 40; col_c2 = 50; col_con = 24
            col_nm2  = CW - col_rng - col_dmg - col_e2 - col_c2 - col_con - 10
            cy -= 4
            c.setFillColor(SUB_BG)
            x0 = LM
            for (lbl, w2) in [("WEAPON",col_nm2),("RNG",col_rng),("DMG",col_dmg),
                               ("ENC",col_e2),("COST",col_c2),("CON.",col_con)]:
                c.rect(x0, cy - 13, w2, 13, fill=1, stroke=0)
                c.setFillColor(HDR_FG); c.setFont("Times-Bold", 8)
                c.drawCentredString(x0 + w2/2, cy - 10, lbl)
                c.setFillColor(SUB_BG)
                x0 += w2 + 2
            cy -= 13
            for w in vessel_weapons:
                key  = w.get("key","")
                name = _VESSEL_WPN_NAMES.get(key, key.replace("_"," ").title())
                rng, dmg = _VESSEL_WPN_STATS.get(key, ("",""))
                enc_v    = w.get("enc","")
                con      = "✓" if w.get("concealed") else ""
                if w.get("concealed"):
                    name += " (con.)"
                c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.35)
                x0 = LM
                for (val, w2) in [(name,col_nm2),(rng,col_rng),(dmg,col_dmg),
                                   (str(enc_v) if enc_v not in (None,"") else "",col_e2),
                                   ("",col_c2),(con,col_con)]:
                    c.rect(x0, cy - ROW_H, w2, ROW_H, fill=1, stroke=1)
                    c.setFillColor(INK); c.setFont("Times-Roman", 9)
                    c.drawCentredString(x0 + w2/2, cy - ROW_H + 4.5, val)
                    x0 += w2 + 2
                cy -= ROW_H
        cy -= GAP

    # ── Stowed Player Items ───────────────────────────────────────────────────
    if stowed_trappings:
        cy = section_bar(cy, "Stowed Items (Player Trappings)")
        cy -= GAP
        name_w = CW - 68
        # Sub-header
        c.setFillColor(SUB_BG)
        c.rect(LM, cy - 13, name_w, 13, fill=1, stroke=0)
        c.rect(LM + name_w + 4, cy - 13, 64, 13, fill=1, stroke=0)
        c.setFillColor(HDR_FG); c.setFont("Times-Bold", 8)
        c.drawString(LM + 4, cy - 10, "ITEM")
        c.drawCentredString(LM + name_w + 4 + 32, cy - 10, "ENC")
        cy -= 13
        for t in stowed_trappings:
            c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.35)
            c.rect(LM,              cy - ROW_H, name_w, ROW_H, fill=1, stroke=1)
            c.rect(LM + name_w + 4, cy - ROW_H, 64,    ROW_H, fill=1, stroke=1)
            c.setFillColor(GOLD); c.setLineWidth(0)
            c.circle(LM + 7, cy - ROW_H / 2, 3, fill=1, stroke=0)
            c.setFillColor(INK); c.setFont("Times-Roman", 9)
            c.drawString(LM + 14, cy - ROW_H + 4.5, t.get("name",""))
            ev = t.get("enc")
            c.drawCentredString(LM + name_w + 4 + 32, cy - ROW_H + 4.5, str(ev) if ev not in (None,"") else "")
            cy -= ROW_H
        cy -= GAP

    # ── Additional Cargo ──────────────────────────────────────────────────────
    if extra_cargo:
        cy = section_bar(cy, "Additional Cargo")
        cy -= GAP
        name_w = CW - 68
        # Sub-header
        c.setFillColor(SUB_BG)
        c.rect(LM, cy - 13, name_w, 13, fill=1, stroke=0)
        c.rect(LM + name_w + 4, cy - 13, 64, 13, fill=1, stroke=0)
        c.setFillColor(HDR_FG); c.setFont("Times-Bold", 8)
        c.drawString(LM + 4, cy - 10, "ITEM")
        c.drawCentredString(LM + name_w + 4 + 32, cy - 10, "ENC")
        cy -= 13
        for item in extra_cargo:
            c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.35)
            c.rect(LM,              cy - ROW_H, name_w, ROW_H, fill=1, stroke=1)
            c.rect(LM + name_w + 4, cy - ROW_H, 64,    ROW_H, fill=1, stroke=1)
            c.setFillColor(INK); c.setFont("Times-Roman", 9)
            c.drawString(LM + 8,  cy - ROW_H + 4.5, item.get("name",""))
            ev = item.get("enc")
            c.drawCentredString(LM + name_w + 4 + 32, cy - ROW_H + 4.5, str(ev) if ev not in (None,"") else "")
            cy -= ROW_H
        cy -= GAP

    # ── Encumbrance ───────────────────────────────────────────────────────────
    cy = section_bar(cy, "Encumbrance")
    cy -= GAP
    labeled_field("Empty Vehicle Enc.", g(enc_empty),    LM,          cy, fw2)
    labeled_field("Cargo Capacity",     g(capacity),     LM+CW/2+6,  cy, fw2)
    cy -= FIELD_TOTAL + GAP
    labeled_field("Modifications Enc.", g(enc_upgrades), LM,          cy, fw2)
    labeled_field("Stowed Items Enc.",  g(enc_stowed),   LM+CW/2+6,  cy, fw2)
    cy -= FIELD_TOTAL + GAP
    labeled_field("Additional Cargo Enc.", g(enc_cargo), LM,          cy, fw2)
    labeled_field("Remaining Capacity", g(cap_remain),   LM+CW/2+6,  cy, fw2)
    cy -= FIELD_TOTAL + GAP
    labeled_field("Total Enc.",         g(enc_total),    LM,          cy, fw2, bold_val=True)
    cy -= FIELD_TOTAL + GAP

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = (vehicle.get("notes") or "").strip()
    if notes:
        cy = section_bar(cy, "Notes")
        cy -= 5
        notes_h  = max(50, cy - 46)
        notes_bot = cy - notes_h
        c.setFillColor(FIELD_BG); c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.rect(LM, notes_bot, CW, notes_h, fill=1, stroke=1)
        c.setFillColor(INK); c.setFont("Times-Roman", 9.5)
        for nl in simpleSplit(notes, "Times-Roman", 9.5, CW - 10):
            if cy - 13 < notes_bot + 4: break
            cy -= 13
            c.drawString(LM + 5, cy, nl)

    c.save()
    buf.seek(0)
    overlay_bytes = buf.read()

    blank_reader2  = PdfReader(BLANK_PDF)
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
    writer2        = PdfWriter()
    pg             = blank_reader2.pages[0]
    pg.merge_page(overlay_reader.pages[0])
    writer2.add_page(pg)
    out = io.BytesIO()
    writer2.write(out)
    out.seek(0)
    return out.read()


def fill_pdf(data):
    from pypdf import PdfReader, PdfWriter
    if not PDF_TEMPLATE:
        raise FileNotFoundError("PDF template not found. Place the fillable character sheet PDF in the same folder as this program.")

    # ── Overflow detection ────────────────────────────────────────────────────
    armour          = data.get("armour", [])
    named_armour    = [a for a in armour if a.get("name", "").strip()]
    arm_rows_needed = _count_arm_rows(named_armour)
    use_armor_page  = arm_rows_needed > 5 and bool(ARMOR_PAGE_TEMPLATE)

    talents         = data.get("talents", [])
    named_talents   = [t for t in talents if t.get("name", "").strip()]
    overflow_talents = len(named_talents) > MAIN_TALENT_CAPACITY and bool(TALENT_PAGE_TEMPLATE)

    trappings        = data.get("trappings", [])
    named_trappings  = [t for t in trappings if t.get("name", "").strip()]
    overflow_trappings = len(named_trappings) > MAIN_TRAP_CAPACITY and bool(TALENT_PAGE_TEMPLATE)

    use_talent_page = overflow_talents or overflow_trappings

    spells              = data.get("spells", [])
    named_spells        = [s for s in spells if s.get("name", "").strip()]
    spell_rows_needed   = _count_spell_rows(named_spells)
    overflow_spells     = spell_rows_needed > MAIN_SPELL_CAPACITY and bool(EXTRA_SPELLS_TEMPLATE)

    _log(f"Export: {len(named_armour)} armour ({arm_rows_needed} rows), "
         f"{len(named_talents)} talents, {len(named_trappings)} trappings, "
         f"{len(named_spells)} spells ({spell_rows_needed} rows) | "
         f"armor_page={use_armor_page}, talent_page={use_talent_page}, "
         f"spell_page={overflow_spells} | "
         f"overflow_tal={overflow_talents}, overflow_trap={overflow_trappings}, "
         f"overflow_sp={overflow_spells}")

    reader = PdfReader(PDF_TEMPLATE)
    writer = PdfWriter(clone_from=reader)
    _patch_field_properties(writer)
    fv = build_field_values(data)

    # ── Armour overflow: clear rows 1-5, put redirect in row 1 ───────────────
    if use_armor_page:
        arm_fields = [
            ("NameRow1_2", "LocationsRow1", "EncRow1", "APRow1", "QualitiesRow1"),
            ("NameRow2",   "LocationsRow2", "EncRow2", "APRow2", "QualitiesRow2"),
            ("NameRow3",   "LocationsRow3", "EncRow3", "APRow3", "QualitiesRow3"),
            ("NameRow4",   "LocationsRow4", "EncRow4", "APRow4", "QualitiesRow4"),
            ("NameRow5",   "LocationsRow5", "EncRow5", "APRow5", "QualitiesRow5"),
        ]
        for nf, lf, ef, af2, qf in arm_fields:
            fv[(nf, 2)] = ""; fv[(lf, 2)] = ""; fv[(ef, 2)] = ""
            fv[(af2, 2)] = ""; fv[(qf, 2)] = ""
        fv[("NameRow1_2", 2)] = "See Armour page"

    # ── Talent overflow: clear multiline talent fields, put redirect ──────────
    if overflow_talents:
        fv[("Talent NameRow1", 1)] = "See Talents document"
        fv[("Times takenRow1", 1)] = ""
        fv[("DescriptionRow1", 1)] = ""

    # ── Trapping overflow: clear multiline trapping fields, put redirect ──────
    if overflow_trappings:
        fv[("NameRow1_3", 2)] = "See Trappings document"
        fv[("EncRow1_2",  2)] = ""

    # ── Spell overflow: clear main-sheet spell rows, put redirect in row 1 ────
    if overflow_spells:
        _sp_fields_main = [
            ("NameRow1_5","TNRow1","RangeRow1","TargetRow1","DurationRow1","EffectRow1"),
            ("NameRow2_3","TNRow2","RangeRow2","TargetRow2","DurationRow2","EffectRow2"),
            ("NameRow3_3","TNRow3","RangeRow3","TargetRow3","DurationRow3","EffectRow3"),
            ("NameRow4_3","TNRow4","RangeRow4","TargetRow4","DurationRow4","EffectRow4"),
            ("NameRow5_3","TNRow5","RangeRow5","TargetRow5","DurationRow5","EffectRow5"),
            ("NameRow6_2","TNRow6","RangeRow6","TargetRow6","DurationRow6","EffectRow6"),
            ("NameRow7_2","TNRow7","RangeRow7","TargetRow7","DurationRow7","EffectRow7"),
            ("NameRow8",  "TNRow8","RangeRow8","TargetRow8","DurationRow8","EffectRow8"),
        ]
        for nf, tnf, rf, tgf, df, ef in _sp_fields_main:
            fv[(nf, 2)] = ""; fv[(tnf, 2)] = ""; fv[(rf,  2)] = ""
            fv[(tgf, 2)] = ""; fv[(df, 2)] = ""; fv[(ef,  2)] = ""
        fv[("NameRow1_5", 2)] = "See extra Spells and Prayers page"

    by_page = {}
    for (fid, pg), val in fv.items():
        by_page.setdefault(pg, {})[fid] = val
    for page_num, field_values in by_page.items():
        writer.update_page_form_field_values(
            writer.pages[page_num - 1], field_values, auto_regenerate=True
        )
    writer.set_need_appearances_writer(True)

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    main_bytes = buf.read()

    # ── Build extra pages ─────────────────────────────────────────────────────
    extra_pages = []

    if use_armor_page:
        try:
            armor_buf = fill_armor_page(data)
            _log(f"fill_armor_page returned {len(armor_buf) if armor_buf else 'None'} bytes")
            if armor_buf:
                extra_pages.append(armor_buf)
            else:
                _log("WARNING: fill_armor_page returned None — armour page not appended.")
        except Exception as e:
            _log(f"ERROR filling armour page: {e}")
            import traceback as _tb
            _log(_tb.format_exc())

    if use_talent_page:
        try:
            talent_buf = fill_talent_page(
                data,
                fill_talents=overflow_talents,
                fill_trappings=overflow_trappings,
            )
            _log(f"fill_talent_page returned {len(talent_buf) if talent_buf else 'None'} bytes")
            if talent_buf:
                extra_pages.append(talent_buf)
            else:
                _log("WARNING: fill_talent_page returned None — talent page not appended.")
        except Exception as e:
            _log(f"ERROR filling talent page: {e}")
            import traceback as _tb
            _log(_tb.format_exc())

    if overflow_spells:
        try:
            spell_buf = fill_spell_page(data)
            _log(f"fill_spell_page returned {len(spell_buf) if spell_buf else 'None'} bytes")
            if spell_buf:
                extra_pages.append(spell_buf)
            else:
                _log("WARNING: fill_spell_page returned None — spell page not appended.")
        except Exception as e:
            _log(f"ERROR filling spell page: {e}")
            import traceback as _tb
            _log(_tb.format_exc())

    # ── Mount pages (one per mount with content) ──────────────────────────────
    if BLANK_PDF:
        all_mounts = data.get("mounts") or []
        if not all_mounts and data.get("mount"):
            all_mounts = [data["mount"]]  # legacy fallback
        all_trappings = (data.get("trappings", []) +
                         data.get("weapons", []) +
                         data.get("armour", []))
        for m_idx, m_data in enumerate(all_mounts):
            if not m_data:
                continue
            try:
                # Build packed items for this specific mount from packedTrapNames
                packed_names = set(m_data.get("packedTrapNames") or [])
                if packed_names:
                    per_mount_trappings = [
                        dict(t, packed=True) if t.get("name","").strip() in packed_names else dict(t, packed=False)
                        for t in all_trappings
                    ]
                else:
                    per_mount_trappings = [dict(t, packed=False) for t in all_trappings]
                mount_page_data = dict(data, mount=m_data, trappings=per_mount_trappings)
                mount_buf = fill_mount_page(mount_page_data)
                if mount_buf:
                    extra_pages.append(mount_buf)
                    _log(f"fill_mount_page[{m_idx}] returned {len(mount_buf)} bytes")
                else:
                    _log(f"fill_mount_page[{m_idx}]: no mount data — page skipped")
            except Exception as e:
                _log(f"ERROR filling mount page[{m_idx}]: {e}")
                import traceback as _tb
                _log(_tb.format_exc())

    # ── Vehicle pages (one per vehicle with content) ──────────────────────────
    if BLANK_PDF:
        all_vehicles  = data.get("vehicles") or []
        all_veh_items = (data.get("trappings", []) +
                         data.get("weapons", []) +
                         data.get("armour", []))
        for v_idx, v_data in enumerate(all_vehicles):
            if not v_data:
                continue
            try:
                # Mark stowed items for this vehicle from stowedTrapNames
                stowed_names = set(v_data.get("stowedTrapNames") or [])
                per_veh_trappings = [
                    dict(t, stowed=True)  if stowed_names and t.get("name","").strip() in stowed_names
                    else dict(t, stowed=False)
                    for t in all_veh_items
                ]
                veh_page_data = dict(data, vehicle=v_data, trappings=per_veh_trappings)
                veh_buf = fill_vehicle_page(veh_page_data)
                if veh_buf:
                    extra_pages.append(veh_buf)
                    _log(f"fill_vehicle_page[{v_idx}] returned {len(veh_buf)} bytes")
                else:
                    _log(f"fill_vehicle_page[{v_idx}]: no vehicle data — page skipped")
            except Exception as e:
                _log(f"ERROR filling vehicle page[{v_idx}]: {e}")
                import traceback as _tb
                _log(_tb.format_exc())

    # ── Companion pages (one per companion with content) ──────────────────────
    if BLANK_PDF:
        all_companions = data.get("companions") or []
        for comp_idx, comp_data in enumerate(all_companions):
            if not comp_data:
                continue
            try:
                comp_buf = fill_companion_page(comp_data)
                if comp_buf:
                    extra_pages.append(comp_buf)
                    _log(f"fill_companion_page[{comp_idx}] returned {len(comp_buf)} bytes")
                else:
                    _log(f"fill_companion_page[{comp_idx}]: no companion data — page skipped")
            except Exception as e:
                _log(f"ERROR filling companion page[{comp_idx}]: {e}")
                import traceback as _tb
                _log(_tb.format_exc())

    if extra_pages:
        combined = PdfWriter()
        combined.append(io.BytesIO(main_bytes))
        for page_bytes in extra_pages:
            combined.append(io.BytesIO(page_bytes))
        out = io.BytesIO()
        combined.write(out)
        out.seek(0)
        result = out.read()
        _log(f"Merge done. Final size={len(result)} bytes")
        return result

    return main_bytes


# ── Companion trait descriptions (base name → one-line effect) ───────────────
_TRAIT_DESC = {
    'Amphibious':        'Can breathe and move underwater without penalty.',
    'Bestial':           'Cannot speak; no social skills except Intimidate; uses WP instead of resolve for fear tests.',
    'Camouflage':        'Natural colouration; may hide in {x} environments without penalty.',
    'Corruption':        'Presence causes Corruption ({x}) tests for nearby creatures.',
    'Dark Vision':       'Can see normally in total darkness.',
    'Disease':           'Wounds may transmit {x}; target must pass End. test or contract disease.',
    'Disturbing':        'Causes Psychology test at difficulty {x} for those who witness it.',
    'Fear':              'Causes Fear ({x}); opponents must pass a WP test or become Frightened.',
    'Frenzy':            'May enter Frenzy voluntarily; while Frenzied gains +10 WS, +10 S, ignores first Critical.',
    'Fly':               'Airborne Move = {x}; ignores ground terrain and obstacles.',
    'Hardy':             'Add TB to Wounds total once (already applied to Wounds stat).',
    'Hungry':            'Must eat after each encounter or gain a level of Fatigue.',
    'Immunity':          'Immune to {x}; automatically pass all relevant tests.',
    'Infected':          'Attacks may inflict Festering Wounds; target risks infection.',
    'Insubstantial':     'Cannot be harmed by non-magical weapons or abilities.',
    'Keen Senses':       'Perception tests using {x}: +10 bonus; not affected by blindness for that sense.',
    'Lifesense':         'Detects living creatures within WP yards regardless of lighting or concealment.',
    'Magic':             'Natural attacks count as magical for purposes of overcoming resistances.',
    'Mimicry':           'Can replicate voices or sounds heard before; Fellowship test to succeed.',
    'Night Vision':      'Sees clearly up to 20 yards in dim light; sees outlines up to 10 yards in total darkness.',
    'Pack':              'Gains +{x} to WS when {x} or more pack members are engaging the same target.',
    'Painless':          'Ignores first Critical effect; never Stunned or knocked Prone from Critical hits.',
    'Regenerate':        'Heals 1 Wound per round while alive; limbs regrow given time.',
    'Skittering':        '+5 Ag; ranged attackers suffer −10; moves through difficult terrain without penalty.',
    'Skittish':          'Must pass a WP test when startled (loud noise, fire, sudden movement) or it will bolt; −10 to Animal Training tests.',
    'Spiteful':          'When knocked out or killed, may immediately make one free attack.',
    'Stride':            'Closing distance counts as a charge; no Move penalty for long distances.',
    'Stupid':            'Must pass a WP test each round or become Stunned and act randomly.',
    'Sure Footing':      'Unaffected by difficult terrain; never required to test Ag for rough ground.',
    'Swarm':             'Occupies multiple squares; damage is split equally among all models in the swarm.',
    'Territorial':       'Attacks creatures that enter its territory; −10 WP when forced to retreat.',
    'Tracker':           'Has the Track skill; can follow scent trails up to 24 hours old; ignores −10 penalties for poor tracking conditions.',
    'Trained (Combat)':  'Trained warbeast; may perform combat manoeuvres and will not flee in battle.',
    'Trained (Draught)': 'Trained to pull carts and loads; no penalty for harness or draught work.',
    'Trained (Scarred)': 'Will not flee from combat; immune to Fear caused by battle.',
    'Venom':             'Wounds impose Venom ({x}) condition; target must pass a T test or suffer D10 Wounds.',
    'Weapon':            'Natural weapon inflicts SB+{x} damage; counts as a hand weapon.',
    'Web':               'Can Restrain a target at range; target needs a Str test at difficulty {x} to break free.',
}

_SIZE_MODIFIERS = {
    'Tiny':      'Wounds = SB only. Attackers: −20 to hit; target +20 to Dodge. Enc capacity ×¼.',
    'Little':    'Wounds = SB+TB. Attackers: −10 to hit; target +10 to Dodge. Enc capacity ×½.',
    'Average':   'Wounds = SB+TB+WPB. Standard combat and encumbrance rules.',
    'Large':     'Wounds = SB+2×TB+WPB. Attackers: +10 to hit; target −10 to Dodge. Enc capacity ×2.',
    'Enormous':  'Wounds = SB+3×TB+WPB. Attackers: +20 to hit; target −20 to Dodge. Enc ×4. Counts as Intimidating (2).',
    'Monstrous': 'Wounds = SB+4×TB+WPB. Attackers: +30 to hit; target −30 to Dodge. Enc ×8. Counts as Frightening (2).',
}

def _parse_trait_entry(s):
    """'Keen Senses (Smell)' → ('Keen Senses', 'Smell').  'Bestial' → ('Bestial', '')."""
    m = re.match(r'^(.*?)\s*\(([^)]*)\)\s*$', s.strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else (s.strip(), '')

def _get_trait_desc(raw):
    """Return one-line description for a raw trait string like 'Pack (10)'."""
    base, param = _parse_trait_entry(raw)
    desc = _TRAIT_DESC.get(base, '')
    if not desc:
        # fuzzy: check if any key starts with base (e.g. 'Trained' matches 'Trained (Combat)')
        for k, v in _TRAIT_DESC.items():
            if k.lower().startswith(base.lower()) or base.lower().startswith(k.lower()):
                desc = v; break
    if not desc:
        return ''
    if param:
        desc = desc.replace('{x}', param)
    else:
        desc = re.sub(r'\s*\(\{x\}\)', '', desc).replace('{x}', '?')
    return desc


def fill_companion_page(comp):
    """Generate companion sheet pages using reportlab over blank.pdf.
    Automatically creates additional pages when content overflows one page.
    comp is a single companion dict from the companions list.
    Returns bytes (possibly multi-page PDF) or None if no content / prerequisites missing."""
    if not comp:
        return None
    has_content = (comp.get("name") or comp.get("role") or
                   (comp.get("skills") and any(s.get("name","").strip() for s in comp["skills"])) or
                   (comp.get("talents") and any(t.get("name","").strip() for t in comp["talents"])) or
                   comp.get("traits") or comp.get("notes"))
    if not has_content:
        return None
    if not BLANK_PDF:
        _log("blank.pdf not found — companion page skipped")
        return None
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.colors import Color
        from reportlab.lib.utils import simpleSplit
    except ImportError:
        _log("reportlab not available — companion page skipped")
        return None
    from pypdf import PdfReader, PdfWriter

    W, H  = 609.6, 765.36
    LM    = 50.0;  RM = 560.0;  CW = RM - LM
    BAR_H = 14;  LBL_H = 10;  BOX_H = 16;  GAP = 9;  ROW_H = 15
    FIELD_TOTAL = LBL_H + BOX_H
    CY_START = 716.0
    CY_MIN   = 65.0      # bottom margin — flush to new page when cy falls below this

    INK      = Color(0.08, 0.06, 0.02)
    HDR_BG   = Color(0.13, 0.10, 0.05)
    HDR_FG   = Color(0.93, 0.85, 0.55)
    FIELD_BG = Color(0.97, 0.94, 0.88)
    BORDER   = Color(0.40, 0.27, 0.06)
    GOLD     = Color(0.72, 0.52, 0.03)
    SUB_BG   = Color(0.22, 0.17, 0.07)

    # Build title string once (used in both first-page header and "continued" headers)
    name_str = (comp.get("name") or "").strip()
    role_str = (comp.get("role") or "").strip()
    title_str = name_str
    if name_str and role_str:
        title_str = f"{name_str} — {role_str}"
    elif role_str:
        title_str = role_str
    if not title_str:
        title_str = "Companion"

    # Mutable canvas/page state — rebound by _flush_page via nonlocal
    writer = PdfWriter()
    buf = io.BytesIO()
    cv  = rl_canvas.Canvas(buf, pagesize=(W, H))
    cy  = CY_START

    # ── Page management ───────────────────────────────────────────────────────
    def _flush_page():
        """Save current canvas as a new PDF page, then start a fresh canvas."""
        nonlocal cv, cy, buf
        cv.save()
        buf.seek(0);  ov = buf.read()
        br   = PdfReader(BLANK_PDF)
        ordr = PdfReader(io.BytesIO(ov))
        page = br.pages[0]
        page.merge_page(ordr.pages[0])
        writer.add_page(page)
        # Fresh canvas for the next page
        buf = io.BytesIO()
        cv  = rl_canvas.Canvas(buf, pagesize=(W, H))
        cy  = CY_START
        # Draw a compact "continued" header
        cv.setFillColor(INK);  cv.setFont("Times-Bold", 14)
        cv.drawCentredString(W / 2, cy - 18, f"{title_str} — continued")
        cy -= 28
        cv.setStrokeColor(BORDER);  cv.setLineWidth(1.4)
        cv.line(LM, cy, RM, cy)
        cy -= 12

    def _ensure(h):
        """If h points won't fit above CY_MIN, flush the current page first."""
        if cy - h < CY_MIN:
            _flush_page()

    # ── Drawing helpers (all capture cv by closure; cy passed explicitly) ─────
    def hline(y, x1=LM, x2=RM, lw=0.7):
        cv.setStrokeColor(BORDER);  cv.setLineWidth(lw);  cv.line(x1, y, x2, y)

    def section_bar(y, title):
        cv.setFillColor(HDR_BG);  cv.rect(LM, y - BAR_H, CW, BAR_H, fill=1, stroke=0)
        cv.setFillColor(HDR_FG);  cv.setFont("Times-Bold", 8)
        cv.drawString(LM + 5, y - BAR_H + 4, title.upper())
        return y - BAR_H

    def labeled_field(label, value, x, y, w, bold_val=False, val_sz=9.5):
        cv.setFillColor(GOLD);  cv.setFont("Times-Bold", 6.5)
        cv.drawString(x, y - LBL_H + 2, label)
        box_bot = y - LBL_H - BOX_H
        cv.setFillColor(FIELD_BG);  cv.setStrokeColor(BORDER);  cv.setLineWidth(0.4)
        cv.rect(x, box_bot, w, BOX_H, fill=1, stroke=1)
        cv.setFillColor(INK);  cv.setFont("Times-Bold" if bold_val else "Times-Roman", val_sz)
        cv.drawString(x + 4, box_bot + 4.5, str(value or ""))

    def stat_cell(lbl, val, x, y, w):
        cv.setFillColor(GOLD);  cv.setFont("Times-Bold", 6.5)
        cv.drawCentredString(x + w/2, y - LBL_H + 2, lbl)
        box_bot = y - LBL_H - BOX_H
        cv.setFillColor(FIELD_BG);  cv.setStrokeColor(BORDER);  cv.setLineWidth(0.4)
        cv.rect(x, box_bot, w, BOX_H, fill=1, stroke=1)
        cv.setFillColor(INK);  cv.setFont("Times-Bold", 9.5)
        cv.drawCentredString(x + w/2, box_bot + 4.5, str(val or ""))

    # ── Title (first page only) ───────────────────────────────────────────────
    cv.setFillColor(INK);  cv.setFont("Times-Bold", 22)
    cv.drawCentredString(W / 2, cy - 22, title_str)
    cy -= 32;  hline(cy, lw=1.4);  cy -= 12

    # ── Identity ──────────────────────────────────────────────────────────────
    _ensure(BAR_H + 7 + FIELD_TOTAL + GAP + 4)
    cy = section_bar(cy, "Identity")
    cy -= 7
    fw = CW / 4 - 4
    labeled_field("Name",         comp.get("name",     ""), LM,            cy, fw)
    labeled_field("Category",     comp.get("category", ""), LM + fw + 4,   cy, fw)
    labeled_field("Species/Role", comp.get("role",     ""), LM + 2*(fw+4), cy, fw)
    labeled_field("Loyalty",      comp.get("loyalty",  ""), LM + 3*(fw+4), cy, fw)
    cy -= FIELD_TOTAL + GAP + 4;  hline(cy);  cy -= GAP

    # ── Characteristics ───────────────────────────────────────────────────────
    _ensure(BAR_H + 7 + FIELD_TOTAL + 8 + FIELD_TOTAL + 4 + 10 + GAP * 2)
    cy = section_bar(cy, "Characteristics")
    cy -= 7
    stats = [("M",   comp.get("m","")),   ("WS",  comp.get("ws","")),
             ("BS",  comp.get("bs","")),  ("S",   comp.get("s","")),
             ("T",   comp.get("t","")),   ("I",   comp.get("i","")),
             ("Ag",  comp.get("ag","")),  ("Dex", comp.get("dex","")),
             ("Int", comp.get("int","")), ("WP",  comp.get("wp","")),
             ("Fel", comp.get("fel",""))]
    cell_w = CW / len(stats)
    for idx, (lbl, val) in enumerate(stats):
        stat_cell(lbl, val, LM + idx * cell_w, cy, cell_w - 1.5)
    cy -= FIELD_TOTAL + 8
    labeled_field("Size",          comp.get("size",  ""), LM,       cy, 88)
    labeled_field("Wounds (Max)",  comp.get("wmax",  ""), LM + 96,  cy, 88, bold_val=True)
    labeled_field("Wounds (Cur.)", comp.get("wcur",  ""), LM + 192, cy, 88, bold_val=True)
    labeled_field("Armour Points", str(comp.get("ap", "0") or "0"), LM + 288, cy, 80, bold_val=True)
    cy -= FIELD_TOTAL + 4
    size_key  = (comp.get("size") or "").strip()
    size_note = _SIZE_MODIFIERS.get(size_key, "")
    if size_note:
        cv.setFillColor(GOLD);  cv.setFont("Times-BoldItalic", 7)
        cv.drawString(LM, cy - 8, f"Size ({size_key}): ")
        cv.setFillColor(INK);  cv.setFont("Times-Italic", 7)
        cv.drawString(LM + cv.stringWidth(f"Size ({size_key}): ", "Times-BoldItalic", 7), cy - 8, size_note)
        cy -= 10
    cy -= GAP;  hline(cy);  cy -= GAP

    # ── Skills ────────────────────────────────────────────────────────────────
    skills = [s for s in (comp.get("skills") or []) if s.get("name","").strip()]
    if skills:
        col_sk_name = CW - 70;  col_sk_val = 68

        def _skills_subheader():
            nonlocal cy
            cv.setFillColor(SUB_BG)
            cv.rect(LM,                    cy - 12, col_sk_name, 12, fill=1, stroke=0)
            cv.rect(LM + col_sk_name + 2,  cy - 12, col_sk_val,  12, fill=1, stroke=0)
            cv.setFillColor(HDR_FG);  cv.setFont("Times-Bold", 7.5)
            cv.drawString(LM + 4,                                      cy - 9, "SKILL")
            cv.drawCentredString(LM + col_sk_name + 2 + col_sk_val/2,  cy - 9, "VALUE")
            cy -= 12

        _ensure(BAR_H + 4 + 12 + ROW_H)
        cy = section_bar(cy, "Skills");  cy -= 4
        _skills_subheader()
        for sk in skills:
            if cy - ROW_H < CY_MIN:
                _flush_page()
                cy = section_bar(cy, "Skills (continued)");  cy -= 4
                _skills_subheader()
            cv.setFillColor(FIELD_BG);  cv.setStrokeColor(BORDER);  cv.setLineWidth(0.35)
            cv.rect(LM,                   cy - ROW_H, col_sk_name, ROW_H, fill=1, stroke=1)
            cv.rect(LM + col_sk_name + 2, cy - ROW_H, col_sk_val,  ROW_H, fill=1, stroke=1)
            cv.setFillColor(INK);  cv.setFont("Times-Roman", 9)
            cv.drawString(LM + 6,                                      cy - ROW_H + 4.5, sk.get("name",""))
            cv.drawCentredString(LM + col_sk_name + 2 + col_sk_val/2,  cy - ROW_H + 4.5, str(sk.get("value","")))
            cy -= ROW_H
        cy -= GAP;  hline(cy);  cy -= GAP

    # ── Talents ───────────────────────────────────────────────────────────────
    talents = [t for t in (comp.get("talents") or []) if t.get("name","").strip()]
    if talents:
        col_tn = 130;  col_ti = 42;  col_td = CW - col_tn - col_ti - 4

        def _talents_subheader():
            nonlocal cy
            cv.setFillColor(SUB_BG)
            cv.rect(LM,                       cy - 12, col_tn, 12, fill=1, stroke=0)
            cv.rect(LM + col_tn + 2,          cy - 12, col_ti, 12, fill=1, stroke=0)
            cv.rect(LM + col_tn + col_ti + 4, cy - 12, col_td, 12, fill=1, stroke=0)
            cv.setFillColor(HDR_FG);  cv.setFont("Times-Bold", 7.5)
            cv.drawString(LM + 4,                              cy - 9, "TALENT")
            cv.drawCentredString(LM + col_tn + 2 + col_ti/2,  cy - 9, "TIMES")
            cv.drawString(LM + col_tn + col_ti + 8,           cy - 9, "DESCRIPTION / EFFECT")
            cy -= 12

        _ensure(BAR_H + 4 + 12 + ROW_H)
        cy = section_bar(cy, "Talents");  cy -= 4
        _talents_subheader()
        for tal in talents:
            desc_txt   = str(tal.get("desc",""))
            desc_lines = simpleSplit(desc_txt, "Times-Roman", 8.5, col_td - 8)
            row_h = max(ROW_H, len(desc_lines) * 10 + 5)
            if cy - row_h < CY_MIN:
                _flush_page()
                cy = section_bar(cy, "Talents (continued)");  cy -= 4
                _talents_subheader()
            cv.setFillColor(FIELD_BG);  cv.setStrokeColor(BORDER);  cv.setLineWidth(0.35)
            cv.rect(LM,                       cy - row_h, col_tn, row_h, fill=1, stroke=1)
            cv.rect(LM + col_tn + 2,          cy - row_h, col_ti, row_h, fill=1, stroke=1)
            cv.rect(LM + col_tn + col_ti + 4, cy - row_h, col_td, row_h, fill=1, stroke=1)
            cv.setFillColor(INK);  cv.setFont("Times-Roman", 9)
            cv.drawString(LM + 6,                              cy - row_h/2 - 4, tal.get("name",""))
            cv.drawCentredString(LM + col_tn + 2 + col_ti/2,  cy - row_h/2 - 4, str(tal.get("times","1")))
            cv.setFont("Times-Roman", 8.5)
            ly = cy - 10
            for ln in desc_lines:
                cv.drawString(LM + col_tn + col_ti + 8, ly, ln);  ly -= 10
            cy -= row_h
        cy -= GAP;  hline(cy);  cy -= GAP

    # ── Traits ────────────────────────────────────────────────────────────────
    traits_txt = (comp.get("traits") or "").strip()
    if traits_txt:
        raw_traits = [t.strip() for t in re.split(r',\s*(?![^(]*\))', traits_txt) if t.strip()]
        col_tr_name = 140;  col_tr_desc = CW - col_tr_name - 2

        def _traits_subheader():
            nonlocal cy
            cv.setFillColor(SUB_BG)
            cv.rect(LM,                   cy - 12, col_tr_name, 12, fill=1, stroke=0)
            cv.rect(LM + col_tr_name + 2, cy - 12, col_tr_desc, 12, fill=1, stroke=0)
            cv.setFillColor(HDR_FG);  cv.setFont("Times-Bold", 7.5)
            cv.drawString(LM + 4,              cy - 9, "TRAIT")
            cv.drawString(LM + col_tr_name + 6, cy - 9, "EFFECT")
            cy -= 12

        _ensure(BAR_H + 4 + 12 + ROW_H)
        cy = section_bar(cy, "Traits");  cy -= 4
        _traits_subheader()
        for raw in raw_traits:
            desc       = _get_trait_desc(raw)
            desc_lines = simpleSplit(desc, "Times-Italic", 8.2, col_tr_desc - 8) if desc else []
            row_h = max(ROW_H, len(desc_lines) * 9 + 5)
            if cy - row_h < CY_MIN:
                _flush_page()
                cy = section_bar(cy, "Traits (continued)");  cy -= 4
                _traits_subheader()
            cv.setFillColor(FIELD_BG);  cv.setStrokeColor(BORDER);  cv.setLineWidth(0.35)
            cv.rect(LM,                   cy - row_h, col_tr_name, row_h, fill=1, stroke=1)
            cv.rect(LM + col_tr_name + 2, cy - row_h, col_tr_desc, row_h, fill=1, stroke=1)
            cv.setFillColor(INK);  cv.setFont("Times-Bold", 8.8)
            cv.drawString(LM + 5, cy - row_h/2 - 4, raw)
            cv.setFont("Times-Italic", 8.2)
            ly = cy - 9
            for ln in desc_lines:
                cv.drawString(LM + col_tr_name + 6, ly, ln);  ly -= 9
            cy -= row_h
        cy -= GAP;  hline(cy);  cy -= GAP

    # ── Equipment ─────────────────────────────────────────────────────────────
    equipment = [e for e in (comp.get("equipment") or []) if e.get("name","").strip()]
    if equipment:
        col_eq = CW - 60;  col_enc = 58

        def _equipment_subheader():
            nonlocal cy
            cv.setFillColor(SUB_BG)
            cv.rect(LM,              cy - 12, col_eq,  12, fill=1, stroke=0)
            cv.rect(LM + col_eq + 2, cy - 12, col_enc, 12, fill=1, stroke=0)
            cv.setFillColor(HDR_FG);  cv.setFont("Times-Bold", 7.5)
            cv.drawString(LM + 4,                              cy - 9, "ITEM")
            cv.drawCentredString(LM + col_eq + 2 + col_enc/2,  cy - 9, "ENC")
            cy -= 12

        _ensure(BAR_H + 4 + 12 + ROW_H)
        cy = section_bar(cy, "Equipment");  cy -= 4
        _equipment_subheader()
        for eq in equipment:
            if cy - ROW_H < CY_MIN:
                _flush_page()
                cy = section_bar(cy, "Equipment (continued)");  cy -= 4
                _equipment_subheader()
            cv.setFillColor(FIELD_BG);  cv.setStrokeColor(BORDER);  cv.setLineWidth(0.35)
            cv.rect(LM,              cy - ROW_H, col_eq,  ROW_H, fill=1, stroke=1)
            cv.rect(LM + col_eq + 2, cy - ROW_H, col_enc, ROW_H, fill=1, stroke=1)
            cv.setFillColor(INK);  cv.setFont("Times-Roman", 9)
            cv.drawString(LM + 6,                              cy - ROW_H + 4.5, eq.get("name",""))
            cv.drawCentredString(LM + col_eq + 2 + col_enc/2,  cy - ROW_H + 4.5, str(eq.get("enc","")))
            cy -= ROW_H
        cy -= GAP;  hline(cy);  cy -= GAP

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes_txt = (comp.get("notes") or "").strip()
    if notes_txt:
        n_lines = simpleSplit(notes_txt, "Times-Roman", 9.5, CW - 10)
        line_h  = 12
        _ensure(BAR_H + 4 + line_h)
        cy = section_bar(cy, "Notes");  cy -= 4
        i = 0
        while i < len(n_lines):
            # How many lines fit on the remaining page?
            lines_fit = max(1, int((cy - CY_MIN) / line_h))
            chunk     = n_lines[i:i + lines_fit]
            chunk_h   = len(chunk) * line_h
            cv.setFillColor(FIELD_BG);  cv.setStrokeColor(BORDER);  cv.setLineWidth(0.4)
            cv.rect(LM, cy - chunk_h, CW, chunk_h, fill=1, stroke=1)
            cv.setFillColor(INK);  cv.setFont("Times-Roman", 9.5)
            ly = cy - 10
            for ln in chunk:
                cv.drawString(LM + 5, ly, ln);  ly -= line_h
            cy -= chunk_h
            i += len(chunk)
            if i < len(n_lines):
                _flush_page()
                cy = section_bar(cy, "Notes (continued)");  cy -= 4

    # ── Flush final page and assemble output ──────────────────────────────────
    cv.save()
    buf.seek(0);  ov = buf.read()
    blank_reader   = PdfReader(BLANK_PDF)
    overlay_reader = PdfReader(io.BytesIO(ov))
    page = blank_reader.pages[0]
    page.merge_page(overlay_reader.pages[0])
    writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()


# ── Native file-open dialog (runs in handler thread, returns path or "") ───────
def _pick_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        initial = SAVES_DIR if os.path.isdir(SAVES_DIR) else EXE_DIR
        path = filedialog.askopenfilename(
            title="Load Character",
            initialdir=initial,
            filetypes=[("Character saves", "*.json"), ("All files", "*.*")],
        )
        root.destroy()
        return path or ""
    except Exception:
        return ""

# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Quiet access log

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(HTML_FILE, "rb") as fh:
                    self._send(200, "text/html; charset=utf-8", fh.read())
            except FileNotFoundError:
                self._send(404, "text/plain", "Character sheet HTML not found.")
        elif path == "/api/ping":
            _last_ping[0] = time.time()
            self._send(200, "application/json", '{"ok":true}')
        elif path == "/status":
            status = {
                "app": APP_NAME,
                "version": APP_VERSION,
                "pdf_template": os.path.basename(PDF_TEMPLATE) if PDF_TEMPLATE else None,
                "pdf_found": PDF_TEMPLATE is not None,
                "armor_page_template": os.path.basename(ARMOR_PAGE_TEMPLATE) if ARMOR_PAGE_TEMPLATE else None,
                "armor_page_found": ARMOR_PAGE_TEMPLATE is not None,
            }
            self._send(200, "application/json", json.dumps(status))
        elif path == "/api/browse":
            file_path = _pick_file()
            if not file_path:
                self._send(200, "application/json", json.dumps({"cancelled": True}))
                return
            try:
                with open(file_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self._send(200, "application/json", json.dumps({"cancelled": False, "data": data}))
            except Exception:
                err = traceback.format_exc()
                self._send(500, "text/plain", err)
        elif path == "/api/saves":
            # Return list of saves sorted newest-first
            saves = []
            if os.path.isdir(SAVES_DIR):
                for fname in os.listdir(SAVES_DIR):
                    if fname.lower().endswith(".json"):
                        fpath = os.path.join(SAVES_DIR, fname)
                        saves.append({
                            "filename": fname,
                            "modified": os.path.getmtime(fpath),
                        })
            saves.sort(key=lambda x: x["modified"], reverse=True)
            self._send(200, "application/json", json.dumps(saves))
        elif path == "/api/load":
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            fname = qs.get("file", [None])[0]
            if not fname:
                self._send(400, "text/plain", "Missing file parameter")
                return
            # Sanitise: strip any path components
            fname = os.path.basename(fname)
            fpath = os.path.join(SAVES_DIR, fname)
            if not os.path.isfile(fpath):
                self._send(404, "text/plain", "Save not found")
                return
            with open(fpath, "rb") as fh:
                self._send(200, "application/json", fh.read())
        else:
            self._send(404, "text/plain", "Not found")

    def do_POST(self):
        if self.path == "/export":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                pdf_bytes = fill_pdf(data)
                char_name = re.sub(r"[^\w\-]", "_", data.get("name", "character") or "character")
                filename = f"{char_name}_WFRP4.pdf"
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", len(pdf_bytes))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(pdf_bytes)
                print(f"  ✓ Exported: {filename}")
            except Exception:
                err = traceback.format_exc()
                print(f"\n  ✗ Export error:\n{err}")
                self._send(500, "text/plain", err)
        elif self.path == "/api/delete":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                fname = os.path.basename(payload.get("filename", ""))
                fpath = os.path.join(SAVES_DIR, fname)
                if fname and os.path.isfile(fpath):
                    os.remove(fpath)
                    print(f"  ✓ Deleted save: {fname}")
                    self._send(200, "application/json", json.dumps({"ok": True}))
                else:
                    self._send(404, "text/plain", "Save not found")
            except Exception:
                self._send(500, "text/plain", traceback.format_exc())
        elif self.path == "/api/save":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                char_data = payload.get("data", {})
                char_name = re.sub(r"[^\w\-]", "_", char_data.get("name", "character") or "character")
                filename = f"{char_name}_WFRP4.json"
                fpath = os.path.join(SAVES_DIR, filename)
                with open(fpath, "w", encoding="utf-8") as fh:
                    json.dump(char_data, fh, ensure_ascii=False, indent=2)
                print(f"  ✓ Saved: {filename}")
                self._send(200, "application/json", json.dumps({"ok": True, "filename": filename}))
            except Exception:
                err = traceback.format_exc()
                print(f"\n  ✗ Save error:\n{err}")
                self._send(500, "text/plain", err)
        else:
            self._send(404, "text/plain", "Not found")


# ── Port helpers ───────────────────────────────────────────────────────────────
def find_free_port(start=5000, attempts=20):
    for p in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", p))
                return p
            except OSError:
                continue
    return None


def wait_for_server(port, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# ── Banner ─────────────────────────────────────────────────────────────────────
BANNER = r"""
  ██╗    ██╗███████╗██████╗ ██████╗      ██╗  ██╗███████╗
  ██║    ██║██╔════╝██╔══██╗██╔══██╗     ██║  ██║██╔════╝
  ██║ █╗ ██║█████╗  ██████╔╝██████╔╝     ███████║███████╗
  ██║███╗██║██╔══╝  ██╔══██╗██╔═══╝      ╚════██║╚════██║
  ╚███╔███╔╝██║     ██║  ██║██║               ██║███████║
   ╚══╝╚══╝ ╚═╝     ╚═╝  ╚═╝╚═╝               ╚═╝╚══════╝
       WARHAMMER FANTASY ROLEPLAY 4e — Character Sheet
"""


# ── Watchdog ───────────────────────────────────────────────────────────────────
def _watchdog(server):
    """Shut down automatically when the browser tab is closed.

    Waits PING_GRACE seconds for the browser to load and start pinging,
    then shuts down if no ping is received within PING_TIMEOUT seconds.
    """
    time.sleep(PING_GRACE)
    _last_ping[0] = time.time()   # reset clock after grace period
    while True:
        time.sleep(PING_INTERVAL)
        if time.time() - _last_ping[0] > PING_TIMEOUT:
            print("\n\n  Browser tab closed. Shutting down... Goodbye!")
            server.shutdown()
            os._exit(0)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    # Check dependencies first
    missing = check_dependencies()
    if missing:
        print("\n" + "="*60)
        print("  MISSING DEPENDENCIES")
        print("="*60)
        print(f"\n  The following Python packages are required:\n")
        for pkg in missing:
            print(f"    • {pkg}")
        print(f"\n  Install them by running:")
        print(f"\n    pip install {' '.join(missing)}")
        print("\n" + "="*60)
        input("\n  Press Enter to exit...")
        sys.exit(1)

    # Print banner
    print(BANNER)
    print("="*60)
    print(f"  Version {APP_VERSION}")
    print("="*60)

    if PDF_TEMPLATE:
        print(f"\n  ✓ PDF template:        {os.path.basename(PDF_TEMPLATE)}")
    else:
        print("\n  ⚠  PDF template not found.")
        print("     Place 'WFRP4_Fillable_Character_Sheet_Autofill.pdf'")
        print("     in the same folder as this program.")
        print("     Export to PDF will be unavailable until it is found.")

    if EXTRA_SPELLS_TEMPLATE:
        print(f"  ✓ Extra spells page:   {os.path.basename(EXTRA_SPELLS_TEMPLATE)}")

    # Create saves folder next to the EXE if it doesn't exist yet
    if not os.path.isdir(SAVES_DIR):
        os.makedirs(SAVES_DIR, exist_ok=True)
        print(f"\n  ✓ Created saves folder: {SAVES_DIR}")

    # Find a free port
    port = find_free_port(PORT)
    if port is None:
        print("\n  ✗ Could not find a free port. Please close other applications and try again.")
        input("\n  Press Enter to exit...")
        sys.exit(1)

    url = f"http://localhost:{port}"

    # Start server in background thread
    server = HTTPServer(("localhost", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Watchdog: shut down when browser tab closes
    wd = threading.Thread(target=_watchdog, args=(server,), daemon=True)
    wd.start()

    # Wait for it to be ready
    if not wait_for_server(port):
        print("\n  ✗ Server failed to start.")
        sys.exit(1)

    print(f"\n  ✓ Server running at:  {url}")
    print(f"\n  Opening browser...")
    webbrowser.open(url)

    print(f"\n  ─────────────────────────────────────────────────────")
    print(f"  The app is now open in your browser.")
    print(f"  Keep this window open while using the character sheet.")
    print(f"  Press Ctrl+C here to stop the app.")
    print(f"  ─────────────────────────────────────────────────────\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  Shutting down... Goodbye!")
        server.shutdown()


if __name__ == "__main__":
    main()
