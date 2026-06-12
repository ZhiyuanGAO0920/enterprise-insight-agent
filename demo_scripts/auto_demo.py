#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enterprise Insight Agent V4 - Automated Demo Script v3
======================================================
Resolution: 2560x1600 (confirmed by user screenshots)
All coordinates measured from actual UI screenshots.
Uses F11 fullscreen mode to eliminate browser chrome offset.

Author: Wukong
"""

import os
import sys
import time
import webbrowser

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = r"D:\GaoZhiyuan\下载\WorkBuddy下载\Demo视频素材-V4"
LOGIN_URL = "http://localhost:8002"

# Coordinates measured from 2560x1600 screenshots
# All coordinates assume browser is in F11 FULLSCREEN mode
# === HOW TO CALIBRATE ===
#   1. Open browser to localhost:8002, login, go to analysis page
#   2. Press F11 to fullscreen
#   3. Run: python -c "import pyautogui; print(pyautogui.position())"
#   4. Move mouse to target element, click, see coordinates in terminal
#   5. Update values below
C = {
    # --- LOGIN PAGE ---
    # Login card centered on screen, inputs stacked vertically
    "login_tab_start":   True,       # Use Tab navigation (reliable)
    # If Tab fails, fall back to these coordinates:
    "login_username_click": (1280, 660),
    "login_password_click": (1280, 745),
    "login_button_click":   (1280, 825),

    # --- ANALYSIS PAGE ---
    # Left sidebar "New Session" button (top-left area)
    "sidebar_new_session": (100, 130),
    # Bottom-center question input box (the most critical coordinate)
    # CALIBRATE THIS: open analysis page, move mouse to center of input box, print coords
    "question_input":      (1280, 1550),
    # Send/submit button (usually right of input box)
    "send_button":         (1390, 1550),

    # --- DASHBOARD PAGE (optional step) ---
    "quick_report_card":   (1100, 800),   # May need calibration
}

# ============================================================
# HELPERS
# ============================================================
def wait(seconds, reason=""):
    if reason:
        print(f"    ... wait {seconds}s ({reason})")
    else:
        print(f"    ... wait {seconds}s")
    time.sleep(seconds)

def click(x, y, desc=""):
    print(f"    -> CLICK ({x},{y}) {desc}")
    pyautogui.click(x, y)

def type_text(text, interval=0.03):
    print(f"    -> TYPE: {text[:60]}{'...' if len(text)>60 else ''}")
    pyautogui.typewrite(text, interval=interval)

def press(key):
    print(f"    -> PRESS {key}")
    pyautogui.press(key)

def hotkey(*keys):
    print(f"    -> HOTKEY {'+'.join(keys)}")
    pyautogui.hotkey(*keys)

def open_url(url):
    print(f"\n    -> OPEN {url}")
    webbrowser.open(url)

def fullscreen_toggle():
    print("    -> F11 toggle fullscreen")
    pyautogui.press('f11')
    time.sleep(0.5)

def scroll_down(amount=5, pos=None):
    if pos is None:
        pos = (1280, 800)
    pyautogui.moveTo(pos[0], pos[1])
    print(f"    -> SCROLL down {amount}")
    pyautogui.scroll(-amount)

def close_tab():
    print("    -> CLOSE tab (Ctrl+W)")
    hotkey('ctrl', 'w')
    time.sleep(0.5)

def try_click(x, y, desc="", fallback_tab_count=0):
    """Try clicking at coordinate, with optional Tab fallback."""
    click(x, y, desc)
    time.sleep(0.5)

# ============================================================
# DEMO STEPS
# ============================================================

def step_01_intro():
    print("\n[1/10] INTRO - Show intro animation")
    intro = os.path.join(ASSETS_DIR, "intro.html")
    open_url(f"file:///{intro.replace(os.sep, '/')}")
    wait(3, "page load")
    fullscreen_toggle()
    wait(6, "intro display")
    fullscreen_toggle()
    wait(1)
    close_tab()

def step_02_open_login():
    print("\n[2/10] OPEN - Product login page")
    open_url(LOGIN_URL)
    wait(4, "page load")
    fullscreen_toggle()
    wait(1, "enter fullscreen")

def step_03_login():
    print("\n[3/10] LOGIN - Auto login as admin")

    # Pure keyboard navigation - no coordinate dependency
    press('tab')              # focus username input
    wait(0.3, "focus username")
    type_text("admin")
    wait(0.2)

    press('tab')              # focus password input
    wait(0.3, "focus password")
    type_text("admin123")
    wait(0.2)

    press('enter')            # submit login form
    wait(6, "login redirect + dashboard load")

def step_04_new_session():
    print("\n[4/10] NEW SESSION - Open new analysis session")
    # Click the "New Session" button in left sidebar
    # If that fails, fall back to Ctrl+K (keyboard shortcut for new chat)
    click(*C["sidebar_new_session"], desc="sidebar 'New Session' button")
    wait(3, "new session page load")
    # If sidebar button didn't work, try Ctrl+K (common new-chat shortcut)
    # hotkey('ctrl', 'k')  # uncomment if needed

def step_05_question_top3():
    print("\n[5/10] QUESTION 1: Top 3 stores by sales")

    click(*C["question_input"], desc="question input box")
    wait(0.5, "focus")
    type_text("上个月销售额最高的三家门店")
    wait(0.3)

    press('enter')
    wait(3, "response start")

    show_progress_demo(duration=10)

    print("    -> Scrolling results...")
    scroll_down(6, (1280, 700))
    wait(3)
    scroll_down(6, (1280, 700))
    wait(3)

def step_06_question_east_china():
    print("\n[6/10] QUESTION 2: East China sales drop analysis [CORE]")

    click(*C["question_input"], desc="question input box")
    wait(0.5, "focus")
    type_text("最近30天华东区销售为什么下降了？分析具体原因并给出改进建议")
    wait(0.3)

    press('enter')
    wait(3, "response start")

    show_progress_demo(duration=14)

    print("    -> Scrolling detailed report (CORE)...")
    scroll_down(6, (1280, 650))
    wait(4, "report header / conclusion")
    scroll_down(6, (1280, 650))
    wait(4, "data tables / charts")
    scroll_down(6, (1280, 650))
    wait(4, "SQL trace / recommendations")

def step_07_question_comprehensive():
    print("\n[7/10] QUESTION 3: Comprehensive weekly analysis")

    click(*C["question_input"], desc="question input box")
    wait(0.5, "focus")
    type_text("分析最近一周的整体经营情况，涵盖销售、会员、库存")
    wait(0.3)

    press('enter')
    wait(3, "response start")

    show_progress_demo(duration=10)

    scroll_down(5, (1280, 650))
    wait(3)

def step_08_v4_features():
    print("\n[8/10] V4 FEATURES - Dashboard quick report")

    # Navigate to Dashboard via URL (faster & more reliable than clicking)
    open_url(LOGIN_URL)
    wait(4, "dashboard load")
    fullscreen_toggle()
    wait(1, "enter fullscreen")

    # Click quick report card
    click(*C["quick_report_card"], desc="'Overall Business Report' card")
    wait(5, "report generation")

    press('esc')
    wait(1)

def step_09_architecture():
    print("\n[9/10] ARCHITECTURE - System architecture diagram")
    arch = os.path.join(ASSETS_DIR, "architecture.svg")
    open_url(f"file:///{arch.replace(os.sep, '/')}")
    wait(3, "page load")
    fullscreen_toggle()
    wait(14, "architecture display")
    fullscreen_toggle()
    wait(1)
    close_tab()

def step_10_ending():
    print("\n[10/10] ENDING - Final card")
    ending = os.path.join(ASSETS_DIR, "ending.html")
    open_url(f"file:///{ending.replace(os.sep, '/')}")
    wait(3, "page load")
    fullscreen_toggle()
    wait(8, "ending display")
    fullscreen_toggle()

def show_progress_demo(duration=10):
    print(f"\n  >> PROGRESS DEMO ({duration}s) <<")
    progress = os.path.join(ASSETS_DIR, "progress_demo.html")
    open_url(f"file:///{progress.replace(os.sep, '/')}")
    wait(2, "progress page load")
    fullscreen_toggle()
    wait(duration, "progress animation")
    fullscreen_toggle()
    wait(0.5)
    close_tab()
    wait(1, "return to product page")
    fullscreen_toggle()
    wait(0.5)

# ============================================================
# MAIN
# ============================================================
def main():
    global pyautogui
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.2

    sw, sh = pyautogui.size()
    print(f"\n[INFO] Screen: {sw}x{sh}")
    if sw != 2560 or sh != 1600:
        print(f"[WARN] Script tuned for 2560x1600. Your screen is {sw}x{sh}.")
        print("       Coordinates may be wrong. Aborting for safety.")
        print("       Please adjust C dict in script or change resolution.")
        input("\nPress Enter to exit...")
        return

    print("""
==================================================
  EIA V4 - AUTO DEMO v3
  Resolution: 2560x1600 (measured from screenshots)
==================================================

  BEFORE running:
  1. Services running (localhost:8002 accessible)
  2. Open EV Recorder -> START RECORDING
  3. Come back here and press Enter

  SAFETY: Move mouse to ANY corner = EMERGENCY STOP

  Duration: ~6-7 minutes
==================================================""")
    input(">> Press Enter when EV recorder is running...\n")

    try:
        step_01_intro()
        step_02_open_login()
        step_03_login()
        step_04_new_session()
        step_05_question_top3()
        step_06_question_east_china()
        step_07_question_comprehensive()
        step_08_v4_features()
        step_09_architecture()
        step_10_ending()

        print("""
==================================================
  DONE! Demo complete.
==================================================

  1. STOP EV recorder now
  2. Import video to CapCut / Jianying
  3. Add subtitles.srt
  4. Add BGM & transitions, export 1080p

==================================================""")
        input("Press Enter to exit...")

    except KeyboardInterrupt:
        print("\n\n[ABORTED] User interrupted.")
    except Exception as e:
        print(f"\n\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
