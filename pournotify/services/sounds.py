from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from ..config import app_data_dir

BUILT_IN_SOUNDS = ("None", "Default", "Bell", "Glass", "Chime", "Pop",
                   "Ding", "Success", "Warning", "Error")
PROFILES = {
    "Default": (660, 0.20), "Bell": (880, 0.35), "Glass": (1200, 0.18),
    "Chime": (523, 0.45), "Pop": (350, 0.10), "Ding": (990, 0.16),
    "Success": (784, 0.32), "Warning": (440, 0.40), "Error": (220, 0.50),
}


class SoundManager:
    def __init__(self, root: Path | None = None):
        self.root = root or app_data_dir() / "sounds"
        self.root.mkdir(parents=True, exist_ok=True)
        self.output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.output)

    def import_file(self, source: Path) -> Path:
        if source.suffix.lower() not in {".wav", ".mp3", ".ogg"}:
            raise ValueError("Only wav, mp3, and ogg audio files are supported.")
        destination = self.root / source.name
        shutil.copy2(source, destination)
        return destination

    def play(self, name: str, volume: int, custom_sounds: dict[str, str] | None = None) -> None:
        if name == "None":
            return
        path = Path((custom_sounds or {}).get(name, "")) if name not in BUILT_IN_SOUNDS else self._tone(name)
        if not path.is_file():
            return
        self.output.setVolume(max(0, min(volume, 100)) / 100)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()

    def _tone(self, name: str) -> Path:
        path = self.root / f"builtin-{name.lower()}.wav"
        if path.exists():
            return path
        frequency, duration = PROFILES.get(name, PROFILES["Default"])
        sample_rate = 22050
        frames = bytearray()
        for index in range(int(sample_rate * duration)):
            envelope = 1 - index / (sample_rate * duration)
            sample = int(10000 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, sample_rate, len(frames) // 2, "NONE", "not compressed"))
            audio.writeframes(frames)
        return path
