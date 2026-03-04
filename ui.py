import tkinter as tk
import threading
import queue
import time

class OverlayUI:
    def __init__(self):
        self.root = None
        self.cmd_queue = queue.Queue()
        self.is_running = False

    def _setup_window(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True) # Remove windows borders/titlebar
        self.root.attributes("-topmost", True) # Always on top
        self.root.attributes("-disabled", True) # Prevent focus stealing
        self.root.attributes("-toolwindow", True) # Keep off taskbar
        
        # Transparent background trick: Anything colored 'magenta' becomes fully transparent
        transparent_color = "magenta"
        self.root.attributes("-transparentcolor", transparent_color)
        self.root.config(bg=transparent_color)
        
        # Center near the bottom
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w, h = 300, 60
        x = (screen_w // 2) - (w // 2)
        y = screen_h - 150
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # The badge frame (A semi-transparent looking block can't be done 
        # flawlessly in native Tkinter without win32api, so we use a solid 
        # dark theme rounded look instead)
        self.frame = tk.Frame(self.root, bg="#2D2D2D", padx=15, pady=10)
        self.frame.pack(expand=True)

        self.label = tk.Label(
            self.frame, 
            text="🔴 Listening...", 
            font=("Segoe UI", 16, "bold"),
            fg="#FFFFFF", 
            bg="#2D2D2D"
        )
        self.label.pack()
        
        self.root.attributes("-alpha", 0.0) # Start transparently hidden instead of withdrawn

        self._check_queue()
        self.is_running = True
        self.root.mainloop()

    def _check_queue(self):
        try:
            while True:
                cmd = self.cmd_queue.get_nowait()
                if cmd == "SHOW":
                    self.root.attributes("-alpha", 1.0)
                elif cmd == "HIDE":
                    self.root.attributes("-alpha", 0.0)
                elif cmd == "QUIT":
                    self.root.quit()
        except queue.Empty:
            pass
        self.root.after(50, self._check_queue) # Polling at 20fps

    def start_in_thread(self):
        """Spins up the Tkinter mainloop in a separate daemon thread."""
        t = threading.Thread(target=self._setup_window, daemon=True)
        t.start()
        
    def show(self):
        self.cmd_queue.put("SHOW")
        
    def hide(self):
        self.cmd_queue.put("HIDE")
        
    def stop(self):
        self.cmd_queue.put("QUIT")

if __name__ == "__main__":
    print("Testing overlay standalone...")
    test_overlay = OverlayUI()
    test_overlay.start_in_thread()
    time.sleep(1) # wait for boot
    
    print("Showing overlay block...")
    test_overlay.show()
    time.sleep(3)
    
    print("Hiding overlay block... Test complete.")
    test_overlay.hide()
    time.sleep(1)