import ctypes
from ctypes import wintypes
import time

user32 = ctypes.WinDLL('user32', use_last_error=True)

# --- C Struct definitions for SendInput ---

INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_UNICODE     = 0x0004
KEYEVENTF_SCANCODE    = 0x0008

class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx",          wintypes.LONG),
                ("dy",          wintypes.LONG),
                ("mouseData",   wintypes.DWORD),
                ("dwFlags",     wintypes.DWORD),
                ("time",        wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p))

class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk",         wintypes.WORD),
                ("wScan",       wintypes.WORD),
                ("dwFlags",     wintypes.DWORD),
                ("time",        wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p))

    def __init__(self, *args, **kwds):
        super(KEYBDINPUT, self).__init__(*args, **kwds)
        
        if not self.dwFlags & KEYEVENTF_UNICODE:
            self.wScan = user32.MapVirtualKeyExW(self.wVk, 0, 0)

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg",    wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD))

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT),
                    ("mi", MOUSEINPUT),
                    ("hi", HARDWAREINPUT))
    _anonymous_ = ("_input",)
    _fields_ = (("type",   wintypes.DWORD),
                ("_input", _INPUT))

# --- Public Functions ---

def _send_input(inputs):
    """Internal wrapper for user32.SendInput"""
    nInputs = len(inputs)
    LPINPUT = INPUT * nInputs
    pInputs = LPINPUT(*inputs)
    cbSize = ctypes.sizeof(INPUT)
    return user32.SendInput(nInputs, pInputs, cbSize)

def wait_for_modifiers_release():
    """
    Blocks until the user has physically lifted their fingers off the Ctrl, Alt, and Shift keys.
    This prevents injected text from accidentally triggering Windows menus or shortcuts.
    """
    VK_SHIFT = 0x10
    VK_CONTROL = 0x11
    VK_MENU = 0x12 # Alt

    while True:
        # GetAsyncKeyState returns a 16-bit value. If the most significant bit is set (0x8000), the key is down.
        alt_down = user32.GetAsyncKeyState(VK_MENU) & 0x8000
        ctrl_down = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
        shift_down = user32.GetAsyncKeyState(VK_SHIFT) & 0x8000
        
        if not (alt_down or ctrl_down or shift_down):
            break
        time.sleep(0.05)

def type_unicode(text: str):
    """
    Simulates typing a unicode string directly into the active window buffer
    using the low-level Windows SendInput API.
    
    This is vastly superior to the `keyboard` module because:
    1. It correctly handles unicode characters (even emojis).
    2. It is blisteringly fast (nearly instant for pages of text).
    3. It avoids polluting the Windows Win+V clipboard history.
    """
    if not text:
        return
        
    # Crucial safeguard: wait for user to lift fingers off hotkey
    wait_for_modifiers_release()
        
    inputs = []
    for c in text:
        # Each character requires a KEY_DOWN and a KEY_UP event
        
        # KEY_DOWN
        inp_down = INPUT(type=INPUT_KEYBOARD,
                         ki=KEYBDINPUT(wVk=0,
                                       wScan=ord(c),
                                       dwFlags=KEYEVENTF_UNICODE,
                                       time=0,
                                       dwExtraInfo=None))
        inputs.append(inp_down)
        
        # KEY_UP
        inp_up = INPUT(type=INPUT_KEYBOARD,
                       ki=KEYBDINPUT(wVk=0,
                                     wScan=ord(c),
                                     dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                                     time=0,
                                     dwExtraInfo=None))
        inputs.append(inp_up)

    # Dispatch the batch of keystrokes to Windows
    _send_input(inputs)

if __name__ == "__main__":
    # Internal test: Wait 3 seconds, then dump a test string
    print("Testing injection. Click into a text window within 3 seconds...")
    time.sleep(3)
    type_unicode("Hello from the low-level Windows SendInput API! 🚀")