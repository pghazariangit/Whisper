import os
import sys
import ctypes
import threading
import queue
import time
import winsound
import json
import pyperclip

# Prevent duplicate instances immediately on boot
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_mutex = kernel32.CreateMutexW(None, False, "WhisperDictationGlobalMutex")
if kernel32.GetLastError() == 183: # ERROR_ALREADY_EXISTS
    print("FATAL: Another instance of Whisper Dictation is already running!")
    sys.exit(1)

user32 = ctypes.WinDLL('user32', use_last_error=True)

import pystray
from pynput import keyboard as pynput_keyboard
from PIL import Image, ImageDraw

import audio
import injector
import ui

try:
    from faster_whisper import WhisperModel
    from google import genai
except ImportError:
    print("FATAL: faster-whisper not found. Is the virtual environment active?")
    sys.exit(1)

# ==========================================
# CONFIGURATION
# ==========================================
MODEL_SIZE = "tiny.en" 
COMPUTE_TYPE = "int8"

class WhisperApp:
    def __init__(self):
        # API Check
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        if not self.gemini_api_key:
            print("WARNING: GEMINI_API_KEY not found in environment variables. Gemini cleanup will be skipped.")

        # Config
        self.config_path = "config.json"
        self.config = {
            "mode": "push_to_talk",
            "hotkey": "ctrl+alt+space"
        }
        self.load_config()

        # State Control
        self.state_lock = threading.RLock()
        self.app_state = "IDLE"  
        self.is_recording = False
        self.abort_flag = False
        self.target_hwnd = None
        self.current_keys = set()
        self.hotkey_was_down = False
        
        # Threading Primitives
        self.stop_recording_event = threading.Event()
        self.transcription_queue = queue.Queue()
        
        # UI Components
        self.tray_icon = None
        self.overlay = ui.OverlayUI()

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                    self.config.update(data)
            except Exception as e:
                print(f"Failed to load config: {e}")

    def save_config(self):
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def create_tray_image(self, color):
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        fill_color = (255, 255, 255) if color != "white" else (128, 128, 128)
        if color == "red":
            fill_color = (255, 50, 50)
        elif color == "yellow":
            fill_color = (255, 200, 50)
            
        # Draw a simple stylized microphone
        # Capsule head
        draw.ellipse((22, 10, 42, 30), fill=fill_color)
        draw.rectangle((22, 20, 42, 40), fill=fill_color)
        draw.ellipse((22, 30, 42, 50), fill=fill_color)
        
        # Stand
        draw.rectangle((30, 50, 34, 58), fill=fill_color)
        
        # Base
        draw.rectangle((20, 56, 44, 60), fill=fill_color)
        
        return image

    def update_tray_title(self):
        if not self.tray_icon: return
        hk = self.config['hotkey']
        if self.app_state == "IDLE":
            self.tray_icon.title = f"Whisper Dictation (Idle)\nHotkey: {hk}"
        elif self.app_state == "RECORDING":
            self.tray_icon.title = "Whisper Dictation (Listening...)"
        elif self.app_state == "PROCESSING":
            self.tray_icon.title = "Whisper Dictation (Transcribing...)"

    def update_ui_state(self, new_state):
        """Updates the tray icon visually. MUST be called inside a lock."""
        if not self.tray_icon: return
            
        if new_state == "IDLE":
            self.tray_icon.icon = self.create_tray_image("gray")
            self.update_tray_title()
            self.overlay.hide()
        elif new_state == "RECORDING":
            self.tray_icon.icon = self.create_tray_image("red")
            self.update_tray_title()
            self.overlay.show()
        elif new_state == "PROCESSING":
            self.tray_icon.icon = self.create_tray_image("yellow")
            self.update_tray_title()
            self.overlay.hide()

    def transcriber_worker(self):
        print(f"Loading '{MODEL_SIZE}' into CPU...")
        try:
            model = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)
            print("Model loaded on CPU! Ready.")
            winsound.Beep(1000, 200) 
        except Exception as e:
            print(f"CPU load failed: {e}")
            winsound.Beep(500, 200)
            return

        while True:
            audio_array = self.transcription_queue.get()
            if audio_array is None: # Graceful exit pill
                break
                
            print("Transcribing...")
            
            with self.state_lock:
                self.app_state = "PROCESSING"
                self.update_ui_state(self.app_state)
                
            try:
                segments, _ = model.transcribe(
                    audio_array, 
                    beam_size=1,
                    vad_filter=False
                )
                
                raw_text = "".join(segment.text.lstrip() + " " for segment in segments).strip()
                
                if not raw_text:
                    print("No text transcribed. Audio may have been too quiet or too short.")
                else:
                    print(f"[Transcribed {len(raw_text)} characters]")
                    
                    final_text = raw_text
                    if self.gemini_api_key:
                        print("Sending to Gemini for spelling & grammar cleanup...")
                        try:
                            client = genai.Client(api_key=self.gemini_api_key)
                            response = client.models.generate_content(
                                model='gemini-3.0-flash',
                                contents=f"Fix homophones/grammar without filler: {raw_text}",
                            )
                            final_text = response.text.strip()
                        except Exception as e:
                            print(f"Gemini API Error (fallback to raw text): {e}")
                    
                    current_hwnd = user32.GetForegroundWindow()
                    if current_hwnd == self.target_hwnd:
                        print("Waiting 0.4s to ensure physical keys are fully released...")
                        time.sleep(0.4)
                        injector.type_unicode(final_text + " ")
                    else:
                        print("WARNING: Foreground window changed! Injection aborted.")
                        print("Fallback active: Text copied to Windows Clipboard.")
                        pyperclip.copy(final_text)
                        winsound.MessageBeep(winsound.MB_ICONHAND)

                winsound.Beep(800, 150)
                
            except Exception as e:
                print(f"Transcription error: {e}")
                winsound.MessageBeep(winsound.MB_ICONHAND)
                
            finally:
                with self.state_lock:
                    self.app_state = "IDLE"
                    self.update_ui_state(self.app_state)
                self.transcription_queue.task_done()

    def capture_thread(self):
        audio_data = audio.capture_audio(self.stop_recording_event)
        
        with self.state_lock:
            if self.abort_flag:
                print("Abort flag detected. Dumping audio.")
                self.abort_flag = False
                self.app_state = "IDLE"
                self.update_ui_state(self.app_state)
                winsound.Beep(300, 200)
                return

        if audio_data is not None and len(audio_data) > 0:
            print(f"Buffered {len(audio_data)} samples.")
            with self.state_lock:
                self.app_state = "PROCESSING"
                self.update_ui_state(self.app_state)
            self.transcription_queue.put(audio_data)
        else:
            with self.state_lock:
                self.app_state = "IDLE"
                self.update_ui_state(self.app_state)

    def start_recording(self):
        with self.state_lock:
            if self.app_state == "PROCESSING":
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                return
                
            if self.app_state == "IDLE" and not self.is_recording:
                self.is_recording = True
                self.app_state = "RECORDING"
                self.update_ui_state(self.app_state)
                
                self.target_hwnd = user32.GetForegroundWindow()
                self.stop_recording_event.clear()
                self.abort_flag = False
                winsound.Beep(600, 100)
                
                t = threading.Thread(target=self.capture_thread, daemon=True)
                t.start()

    def check_hotkey_match(self):
        hk = self.config["hotkey"]
        has_ctrl = any(k in self.current_keys for k in [pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l, pynput_keyboard.Key.ctrl_r])
        has_alt = any(k in self.current_keys for k in [pynput_keyboard.Key.alt, pynput_keyboard.Key.alt_l, pynput_keyboard.Key.alt_r])
        has_shift = any(k in self.current_keys for k in [pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l, pynput_keyboard.Key.shift_r])
        has_space = pynput_keyboard.Key.space in self.current_keys
        has_f12 = pynput_keyboard.Key.f12 in self.current_keys

        if hk == "ctrl+alt+space" and has_ctrl and has_alt and has_space: return True
        if hk == "alt+space" and has_alt and has_space and not has_ctrl: return True # strict
        if hk == "ctrl+space" and has_ctrl and has_space and not has_alt: return True # strict
        if hk == "shift+space" and has_shift and has_space: return True
        if hk == "f12" and has_f12: return True
        return False

    def on_press(self, key):
        with self.state_lock:
            if key == pynput_keyboard.Key.esc and self.app_state == "RECORDING":
                print("--- ESC PRESSED. ABORTING ---")
                self.abort_flag = True
                self.stop_recording_event.set()
                return

            self.current_keys.add(key)
            
            is_match = self.check_hotkey_match()
            if is_match:
                if not self.hotkey_was_down:
                    self.hotkey_was_down = True
                    print(f"DEBUG: Hotkey matched ({self.config['mode']})!")
                    
                    if self.config["mode"] == "push_to_talk":
                        if self.app_state == "IDLE":
                            self.start_recording()
                            
                    elif self.config["mode"] == "toggle":
                        if self.app_state == "IDLE":
                            self.start_recording()
                        elif self.app_state == "RECORDING":
                            self.is_recording = False
                            self.stop_recording_event.set()
                            self.current_keys.clear()
            else:
                self.hotkey_was_down = False

    def on_release(self, key):
        with self.state_lock:
            try:
                self.current_keys.remove(key)
            except KeyError:
                pass
                
            if self.is_recording and self.config["mode"] == "push_to_talk":
                # In push-to-talk, stop the moment the hotkey ceases to be satisfied
                if not self.check_hotkey_match():
                    self.is_recording = False
                    self.stop_recording_event.set()
                    self.current_keys.clear() 

    # Menu Callbacks
    def _set_mode(self, mode_name):
        def handler(icon, item):
            self.config["mode"] = mode_name
            self.save_config()
        return handler

    def _set_hotkey(self, hotkey_name):
        def handler(icon, item):
            self.config["hotkey"] = hotkey_name
            self.save_config()
            self.update_tray_title()
        return handler

    def _is_mode(self, mode_name):
        return lambda item: self.config.get("mode", "push_to_talk") == mode_name

    def _is_hotkey(self, hotkey_name):
        return lambda item: self.config.get("hotkey", "ctrl+alt+space") == hotkey_name

    def on_quit(self, icon, item):
        print("Shutting down cleanly...")
        self.transcription_queue.put(None) 
        icon.stop()
        os._exit(0)

    def run(self):
        print("--- Booting Local Whisper ---", flush=True)
        
        self.overlay.start_in_thread()
        threading.Thread(target=self.transcriber_worker, daemon=True).start()
        
        listener = pynput_keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        listener.start()

        self.tray_icon = pystray.Icon("WhisperDictation", self.create_tray_image("gray"))
        
        # Build tray menu
        menu = pystray.Menu(
            pystray.MenuItem("Mode", pystray.Menu(
                pystray.MenuItem("Push-to-Talk", self._set_mode("push_to_talk"), checked=self._is_mode("push_to_talk"), radio=True),
                pystray.MenuItem("Toggle", self._set_mode("toggle"), checked=self._is_mode("toggle"), radio=True),
            )),
            pystray.MenuItem("Hotkey", pystray.Menu(
                pystray.MenuItem("Ctrl+Alt+Space", self._set_hotkey("ctrl+alt+space"), checked=self._is_hotkey("ctrl+alt+space"), radio=True),
                pystray.MenuItem("Alt+Space", self._set_hotkey("alt+space"), checked=self._is_hotkey("alt+space"), radio=True),
                pystray.MenuItem("Ctrl+Space", self._set_hotkey("ctrl+space"), checked=self._is_hotkey("ctrl+space"), radio=True),
                pystray.MenuItem("Shift+Space", self._set_hotkey("shift+space"), checked=self._is_hotkey("shift+space"), radio=True),
                pystray.MenuItem("F12", self._set_hotkey("f12"), checked=self._is_hotkey("f12"), radio=True),
            )),
            pystray.MenuItem("Quit", self.on_quit)
        )
        self.tray_icon.menu = menu
        
        with self.state_lock:
            self.update_ui_state("IDLE")
        
        print("Ready. Config loaded.", flush=True)
        self.tray_icon.run()

if __name__ == "__main__":
    app = WhisperApp()
    app.run()