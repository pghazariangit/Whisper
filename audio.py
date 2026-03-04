import sounddevice as sd
import numpy as np
import scipy.signal

import typing
import threading
import queue
import time

# Whisper expects strictly 16kHz, mono, float32 audio
TARGET_SAMPLE_RATE: int = 16000
CHANNELS: int = 1

def capture_audio(stop_event: threading.Event) -> typing.Optional[np.ndarray]:
    """
    Captures audio from the current default Windows Microphone into memory at its 
    native sample rate, and resamples it to 16kHz for Whisper.
    """
    audio_q = queue.Queue()

    try:
        # 1. Query the default input device to find its native sample rate
        device_info = sd.query_devices(kind='input')
        native_rate = int(device_info['default_samplerate'])
        print(f"Captured native device rate: {native_rate}Hz")

        def callback(indata, frames, time_info, status):
            if status:
                print("Audio capture status:", status)
            audio_q.put(indata.copy())

        # 2. Capture exactly what the microphone expects natively
        with sd.InputStream(
            samplerate=native_rate,
            channels=None,
            dtype='float32',
            callback=callback
        ):
            print("Microphone Active (Native Rate)...")
            start_time = time.time()
            max_duration = 30.0
            
            while not stop_event.is_set():
                if time.time() - start_time > max_duration:
                    print(f"WARNING: Maximum recording duration ({max_duration}s) reached. Stopping automatically.")
                    stop_event.set()
                    break
                stop_event.wait(0.05)
            
            # Post-roll delay
            print("Hotkey released. Capturing 0.3s post-roll trailing silence...")
            time.sleep(0.3)
            
    except Exception as e:
        print(f"Failed to open microphone: {e}")
        return None

    print("Microphone Closed.")
    
    audio_buffer = []
    while not audio_q.empty():
        audio_buffer.append(audio_q.get())

    if not audio_buffer:
        return None
        
    # Combine the chunks
    audio_data = np.concatenate(audio_buffer)
    if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
        audio_data = np.mean(audio_data, axis=1)
    audio_data = audio_data.flatten()

    # 3. Resample the audio offline to Whisper's exact requirements
    if native_rate != TARGET_SAMPLE_RATE:
        print("Resampling audio to 16kHz...")
        number_of_samples = round(len(audio_data) * float(TARGET_SAMPLE_RATE) / native_rate)
        audio_data = scipy.signal.resample(audio_data, number_of_samples).astype(np.float32)

    max_amp = np.max(np.abs(audio_data))
    print(f"Max audio amplitude: {max_amp:.4f}")
    
    if max_amp < 0.005:
        print("WARNING: Audio input is extremely quiet or muted!")
        
    if max_amp > 0:
        # Normalize to dynamically boost the signal
        # Limits maximum volume to 1.0 so Whisper hears it clearly
        audio_data = audio_data / max_amp

    return audio_data