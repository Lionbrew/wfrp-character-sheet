╔══════════════════════════════════════════════════════════════════╗
║        WFRP4e CHARACTER SHEET — Installation & Usage Guide       ║
╚══════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 • Python 3.8 or newer — https://www.python.org/downloads/
   (Windows: tick "Add Python to PATH" during installation)

 • The pypdf package — installed automatically on first launch

 • The fillable character sheet PDF: 
   "WFRP4_Fillable_Character_Sheet_Autofill.pdf"
   (must be in the same folder as this program for PDF export)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 HOW TO START
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 Windows:
   Double-click:  "WFRP Character Sheet.bat"

 macOS:
   Right-click "WFRP Character Sheet.command" → Open
   (First time only — macOS may ask you to confirm opening it)

 Linux:
   bash "WFRP Character Sheet.command"
   — or —
   python3 wfrp_app.py

 The app opens automatically in your default web browser.
 Keep the terminal/console window open while using the app.
 Close it (or press Ctrl+C) to stop.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 USING THE CHARACTER SHEET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 ┌─ Page 1 — Identity & Skills ──────────────────────────────────┐
 │                                                                │
 │  • Fill in name, species, career — career dropdown auto-fills  │
 │    the Class field and level options.                          │
 │                                                                │
 │  • Characteristics: enter Initial and Advances — Current is   │
 │    calculated automatically.                                   │
 │                                                                │
 │  • Basic Skills: enter Advances — totals calculate from your   │
 │    characteristics automatically.                              │
 │                                                                │
 │  • Grouped & Advanced Skills: start typing a skill name for    │
 │    autocomplete suggestions from the rulebook.                 │
 │                                                                │
 │  • Talents: start typing a talent name for suggestions.        │
 │    Selecting one auto-fills the Description field.             │
 │                                                                │
 └────────────────────────────────────────────────────────────────┘

 ┌─ Page 2 — Combat & Equipment ─────────────────────────────────┐
 │                                                                │
 │  • Wounds are calculated automatically from characteristics.   │
 │                                                                │
 │  • Armour: start typing an armour name for suggestions.        │
 │    Selecting one auto-fills Locations, Enc, AP, and Qualities  │
 │    AND updates the Armour Points hit location diagram.         │
 │                                                                │
 │  • Weapons: start typing for autocomplete — fills Group, Enc,  │
 │    Range/Reach, Damage, and Qualities.                         │
 │                                                                │
 │  • Trappings: start typing for common item suggestions.        │
 │                                                                │
 └────────────────────────────────────────────────────────────────┘

 ┌─ Buttons ──────────────────────────────────────────────────────┐
 │                                                                │
 │  ⚔ New        — Clear everything and start a new character    │
 │  ↓ Save       — Download your character as a .json file        │
 │  ↑ Load       — Load a previously saved .json file             │
 │  ⚜ Export PDF — Fill the official WFRP sheet with your data   │
 │                  and download it as a PDF                      │
 │                                                                │
 └────────────────────────────────────────────────────────────────┘


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 FOLDER CONTENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  wfrp_app.py                          — Main application
  wfrp4e_character_sheet.html          — The character sheet UI
  WFRP Character Sheet.bat             — Windows launcher
  WFRP Character Sheet.command         — macOS / Linux launcher
  WFRP4_Fillable_Character_Sheet_...   — PDF template for export
  README.txt                           — This file


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 TROUBLESHOOTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 "Python is not installed"
   → Download and install Python from https://www.python.org/
   → Windows: tick "Add Python to PATH" during installation

 "Failed to install pypdf"
   → Open a terminal/command prompt and run:  pip install pypdf
   → If that fails, try:  pip install pypdf --user

 "PDF template not found"
   → Make sure "WFRP4_Fillable_Character_Sheet_Autofill.pdf"
     is in the same folder as wfrp_app.py

 Browser does not open automatically
   → Manually open:  http://localhost:5000

 Port 5000 already in use
   → The app will automatically try the next available port
   → Check the console window for the correct URL

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
