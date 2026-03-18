#!/usr/bin/env python3
"""
Dota2 Invoker Voice Control
- Realtime microphone listening with simple energy VAD
- SenseVoice STT via http://localhost:8771/transcribe
- Fuzzy matching Chinese skill names
- pynput keyboard simulation for Invoker combos (Karl keybinds)
"""

from __future__ import annotations

import io
import queue
import random
import signal
import sys
import threading
import time
import wave
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

try:
    import sounddevice as sd
except Exception as e:  # pragma: no cover
    print(f"[FATAL] sounddevice not available: {e}")
    sys.exit(1)

try:
    from pynput.keyboard import Controller as KeyboardController
except Exception as e:  # pragma: no cover
    print(f"[FATAL] pynput not available: {e}")
    sys.exit(1)

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except Exception:
    HAS_RAPIDFUZZ = False

import difflib


# ---------------- Config ----------------
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_MS = 30
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_MS / 1000)

STT_URL = "http://localhost:8771/transcribe"
STT_TIMEOUT = 15

# VAD tuning (energy-based)
NOISE_EMA_ALPHA = 0.92
START_MULTIPLIER = 2.6
END_MULTIPLIER = 1.7
MIN_SPEECH_SEC = 0.28
END_SILENCE_SEC = 0.55
PRE_ROLL_SEC = 0.30
MAX_UTTERANCE_SEC = 4.0

# Key timing
ELEM_DELAY_MIN = 0.030
ELEM_DELAY_MAX = 0.050
INVOKE_DELAY = 0.050
CAST_DELAY_MIN = 0.080
CAST_DELAY_MAX = 0.100


@dataclass
class Skill:
    name: str
    keys: str
    aliases: Tuple[str, ...]


SKILLS: Dict[str, Skill] = {
    "天火": Skill("天火", "CCC", ("天火", "添火", "天活", "天货", "天祸", "日炎")),
    "陨石": Skill("陨石", "CCX", ("陨石", "陨时", "陨实", "云石", "运势")),
    "吹风": Skill("吹风", "ZXX", ("吹风", "吹封", "垂风", "飓风", "龙卷风")),
    "磁暴": Skill("磁暴", "XXX", ("磁暴", "词包", "自爆", "磁爆", "电磁爆")),
    "隐身": Skill("隐身", "ZZX", ("隐身", "隐生", "隐神", "鬼步", "鬼步走")),
    "冰墙": Skill("冰墙", "ZZC", ("冰墙", "冰墙术", "兵强", "冰抢")),
    "推波": Skill("推波", "ZXC", ("推波", "推播", "退播", "冲击波", "超声波")),
    "火人": Skill("火人", "ZCC", ("火人", "活人", "伙人", "火灵", "熔炉精灵")),
}

# QWER -> ZXCV, invoke=V, cast=D
KEYMAP = {
    "Z": "z",  # Quas
    "X": "x",  # Wex
    "C": "c",  # Exort
    "V": "v",  # Invoke
    "D": "d",  # Cast
}


class SenseVoiceClient:
    def __init__(self, url: str = STT_URL, timeout: int = STT_TIMEOUT):
        self.url = url
        self.timeout = timeout

    def health(self) -> bool:
        try:
            r = requests.get("http://localhost:8771/health", timeout=3)
            if r.ok:
                print(f"[ASR] health: {r.json()}")
                return True
        except Exception as e:
            print(f"[ASR] health check failed: {e}")
        return False

    def transcribe_wav(self, wav_bytes: bytes, lang: str = "zh") -> str:
        files = {"audio": ("utterance.wav", wav_bytes, "audio/wav")}
        params = {"lang": lang}
        r = requests.post(self.url, files=files, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return (data.get("text") or "").strip()


class InvokerCaster:
    def __init__(self):
        self.kbd = KeyboardController()

    def _tap(self, key: str):
        self.kbd.press(key)
        self.kbd.release(key)

    def cast_skill(self, skill: Skill):
        print(f"[CAST] {skill.name} => {skill.keys} -> V -> D")

        for i, k in enumerate(skill.keys):
            self._tap(KEYMAP[k])
            if i < len(skill.keys) - 1:
                time.sleep(random.uniform(ELEM_DELAY_MIN, ELEM_DELAY_MAX))

        time.sleep(INVOKE_DELAY)
        self._tap(KEYMAP["V"])
        time.sleep(random.uniform(CAST_DELAY_MIN, CAST_DELAY_MAX))
        self._tap(KEYMAP["D"])


class SkillMatcher:
    def __init__(self):
        self._candidates: List[Tuple[str, str]] = []
        for canonical, skill in SKILLS.items():
            self._candidates.append((canonical, canonical))
            for a in skill.aliases:
                self._candidates.append((a, canonical))

    @staticmethod
    def _clean(text: str) -> str:
        t = text.strip()
        for ch in "，。！？,.!?:;；、 ":
            t = t.replace(ch, "")
        return t

    def match(self, text: str) -> Tuple[Optional[Skill], float, str]:
        cleaned = self._clean(text)
        if not cleaned:
            return None, 0.0, ""

        # exact contain first
        for canonical, skill in SKILLS.items():
            if canonical in cleaned:
                return skill, 1.0, canonical
            for a in skill.aliases:
                if a in cleaned:
                    return skill, 0.96, a

        # fuzzy
        best_score = 0.0
        best_skill = None
        best_hit = ""

        for alias, canonical in self._candidates:
            score = 0.0
            if HAS_RAPIDFUZZ:
                score = fuzz.ratio(cleaned, alias) / 100.0
            else:
                score = difflib.SequenceMatcher(None, cleaned, alias).ratio()

            # also compare in small windows for longer recognized text
            if len(cleaned) > 3 and len(alias) <= len(cleaned):
                for i in range(0, len(cleaned) - len(alias) + 1):
                    seg = cleaned[i : i + len(alias)]
                    if HAS_RAPIDFUZZ:
                        s2 = fuzz.ratio(seg, alias) / 100.0
                    else:
                        s2 = difflib.SequenceMatcher(None, seg, alias).ratio()
                    if s2 > score:
                        score = s2

            if score > best_score:
                best_score = score
                best_skill = SKILLS[canonical]
                best_hit = alias

        # conservative threshold to reduce false trigger
        if best_score >= 0.78:
            return best_skill, best_score, best_hit
        return None, best_score, best_hit


class VoiceInvoker:
    def __init__(self):
        self.client = SenseVoiceClient()
        self.matcher = SkillMatcher()
        self.caster = InvokerCaster()

        self.audio_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=256)
        self.running = threading.Event()
        self.running.set()

        self.noise_floor = 0.006
        self.in_speech = False
        self.speech_frames: List[np.ndarray] = []
        self.pre_roll: List[np.ndarray] = []
        self.silence_blocks = 0
        self.speech_started_at = 0.0

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass
        mono = np.copy(indata[:, 0])
        try:
            self.audio_q.put_nowait(mono)
        except queue.Full:
            # drop block under pressure
            pass

    @staticmethod
    def _rms(x: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(x)) + 1e-12))

    def _to_wav_bytes(self, frames: List[np.ndarray]) -> bytes:
        pcm = np.concatenate(frames)
        pcm = np.clip(pcm, -1.0, 1.0)
        pcm16 = (pcm * 32767.0).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm16.tobytes())
        return buf.getvalue()

    def _handle_utterance(self, frames: List[np.ndarray]):
        duration = len(np.concatenate(frames)) / SAMPLE_RATE
        if duration < MIN_SPEECH_SEC:
            return

        wav_bytes = self._to_wav_bytes(frames)
        try:
            text = self.client.transcribe_wav(wav_bytes, lang="zh")
        except Exception as e:
            print(f"[ASR] request failed: {e}")
            return

        if not text:
            print("[ASR] (empty)")
            return

        skill, score, hit = self.matcher.match(text)
        if skill is None:
            print(f"[ASR] '{text}' -> no match (best={score:.2f}, hit='{hit}')")
            return

        print(f"[ASR] '{text}' -> {skill.name} (score={score:.2f}, via='{hit}')")
        self.caster.cast_skill(skill)

    def run(self):
        print("=" * 64)
        print("Dota2 Invoker Voice Control")
        print("监听中... 说技能名: 天火/陨石/吹风/磁暴/隐身/冰墙/推波/火人")
        print("按 Ctrl+C 退出")
        print("=" * 64)

        if not self.client.health():
            print("[WARN] SenseVoice health check failed. Will keep trying on requests.")

        pre_roll_blocks = max(1, int(PRE_ROLL_SEC * 1000 / BLOCK_MS))
        end_sil_blocks = max(1, int(END_SILENCE_SEC * 1000 / BLOCK_MS))

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=self._audio_callback,
        ):
            while self.running.is_set():
                try:
                    block = self.audio_q.get(timeout=0.2)
                except queue.Empty:
                    continue

                rms = self._rms(block)

                if not self.in_speech:
                    self.noise_floor = NOISE_EMA_ALPHA * self.noise_floor + (1 - NOISE_EMA_ALPHA) * min(rms, 0.03)

                start_th = max(0.008, self.noise_floor * START_MULTIPLIER)
                end_th = max(0.006, self.noise_floor * END_MULTIPLIER)

                # maintain pre-roll
                self.pre_roll.append(block)
                if len(self.pre_roll) > pre_roll_blocks:
                    self.pre_roll.pop(0)

                now = time.time()
                if not self.in_speech:
                    if rms >= start_th:
                        self.in_speech = True
                        self.speech_started_at = now
                        self.silence_blocks = 0
                        self.speech_frames = list(self.pre_roll)
                        self.speech_frames.append(block)
                    continue

                # in speech
                self.speech_frames.append(block)
                if rms < end_th:
                    self.silence_blocks += 1
                else:
                    self.silence_blocks = 0

                speech_sec = len(np.concatenate(self.speech_frames)) / SAMPLE_RATE
                timeout_hit = speech_sec >= MAX_UTTERANCE_SEC
                end_hit = self.silence_blocks >= end_sil_blocks

                if end_hit or timeout_hit:
                    frames = self.speech_frames
                    self.in_speech = False
                    self.speech_frames = []
                    self.silence_blocks = 0

                    self._handle_utterance(frames)


def main():
    app = VoiceInvoker()

    def _stop(*_):
        app.running.clear()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[EXIT] bye")


if __name__ == "__main__":
    main()
