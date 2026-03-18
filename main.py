#!/usr/bin/env python3
"""
Dota2 Invoker Voice Control — Pure KWS Architecture
- Realtime microphone keyword spotting via sherpa-onnx (no ASR/STT fallback)
- Chinese skill name detection → ZXCV key sequence simulation
- 350ms per-keyword debounce
- pynput keyboard simulation for Invoker combos
"""

from __future__ import annotations

import os
import queue
import random
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

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


# ──────────────────── Config ────────────────────────────────
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 512  # ~32ms per block at 16kHz

# Debounce: same keyword suppressed within this window
DEBOUNCE_MS = 350

# Key timing
ELEM_DELAY_MIN = 0.030
ELEM_DELAY_MAX = 0.050
INVOKE_DELAY = 0.050
CAST_DELAY_MIN = 0.080
CAST_DELAY_MAX = 0.100


# ──────────────────── Skill definitions ─────────────────────
@dataclass
class Skill:
    name: str
    keys: str  # element combo: Z=Quas, X=Wex, C=Exort


# Keyword → Skill mapping (KWS detects these exact keywords)
# Key sequence: element keys → V (invoke) → D (cast)
DEFAULT_SKILLS: Dict[str, Skill] = {
    "天火": Skill("天火", "CCC"),   # Sun Strike:      CCC + V + D
    "陨石": Skill("陨石", "CCX"),   # Chaos Meteor:     CCX + V + D
    "吹风": Skill("吹风", "ZXX"),   # Tornado:          ZXX + V + D
    "磁暴": Skill("磁暴", "XXX"),   # EMP:              XXX + V + D
    "隐身": Skill("隐身", "ZZX"),   # Ghost Walk:       ZZX + V + D
    "冰墙": Skill("冰墙", "ZZC"),   # Ice Wall:         ZZC + V + D
    "推波": Skill("推波", "ZXC"),   # Deafening Blast:  ZXC + V + D
}


def load_skills_from_yaml() -> Dict[str, Skill]:
    """Load skills from skills.yaml. Falls back to DEFAULT_SKILLS on any error."""
    yaml_path = Path(os.environ.get("DOTA_SKILLS_FILE", "skills.yaml"))
    if not yaml_path.exists():
        print(f"[CFG] skills file not found: {yaml_path}, using defaults")
        return dict(DEFAULT_SKILLS)

    try:
        import yaml  # type: ignore
    except Exception:
        print("[CFG] PyYAML not installed, using default skills")
        return dict(DEFAULT_SKILLS)

    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        skills_section = data.get("skills", {})
        loaded: Dict[str, Skill] = {}

        for keyword, conf in skills_section.items():
            combo = str(conf.get("combo", "")).upper().strip()
            if len(combo) != 3 or any(ch not in {"Z", "X", "C"} for ch in combo):
                raise ValueError(f"Invalid combo for '{keyword}': {combo}")
            loaded[str(keyword)] = Skill(name=str(keyword), keys=combo)

        if not loaded:
            raise ValueError("No skills loaded from YAML")

        print(f"[CFG] loaded {len(loaded)} skills from {yaml_path}")
        return loaded
    except Exception as e:
        print(f"[CFG] failed to parse {yaml_path}: {e}; using defaults")
        return dict(DEFAULT_SKILLS)


SKILLS: Dict[str, Skill] = load_skills_from_yaml()

# QWER → ZXCV keybind mapping
KEYMAP = {
    "Z": "z",  # Quas
    "X": "x",  # Wex
    "C": "c",  # Exort
    "V": "v",  # Invoke
    "D": "d",  # Cast
}


def format_key_sequence(skill: Skill) -> str:
    """Human-readable key sequence for a skill."""
    elems = " ".join(KEYMAP[k] for k in skill.keys)
    return f"{elems} {KEYMAP['V']} {KEYMAP['D']}"


# ──────────────────── Debouncer ─────────────────────────────
class Debouncer:
    """Suppress repeated triggers of the same keyword within DEBOUNCE_MS."""

    def __init__(self, window_ms: int = DEBOUNCE_MS):
        self._window = window_ms / 1000.0
        self._last: Dict[str, float] = {}

    def should_trigger(self, keyword: str) -> bool:
        now = time.monotonic()
        if keyword not in self._last:
            self._last[keyword] = now
            return True

        last = self._last[keyword]
        if now - last < self._window:
            return False
        self._last[keyword] = now
        return True


# ──────────────────── Keyboard caster ───────────────────────
class InvokerCaster:
    def __init__(self, keyboard=None):
        self.kbd = keyboard or KeyboardController()

    def _tap(self, key: str):
        self.kbd.press(key)
        self.kbd.release(key)

    def cast_skill(self, skill: Skill) -> List[str]:
        """Execute skill key sequence. Returns list of keys pressed."""
        keys_pressed = []

        # Element keys
        for i, k in enumerate(skill.keys):
            mapped = KEYMAP[k]
            self._tap(mapped)
            keys_pressed.append(mapped)
            if i < len(skill.keys) - 1:
                time.sleep(random.uniform(ELEM_DELAY_MIN, ELEM_DELAY_MAX))

        # Invoke
        time.sleep(INVOKE_DELAY)
        self._tap(KEYMAP["V"])
        keys_pressed.append(KEYMAP["V"])

        # Cast
        time.sleep(random.uniform(CAST_DELAY_MIN, CAST_DELAY_MAX))
        self._tap(KEYMAP["D"])
        keys_pressed.append(KEYMAP["D"])

        return keys_pressed


# ──────────────────── KWS Engine (sherpa-onnx) ──────────────
class KeywordSpotter:
    """
    Keyword spotter using sherpa-onnx streaming KWS.

    Requires model files. Set env DOTA_KWS_MODEL_DIR or pass model_dir.
    Download a Chinese KWS model from:
      https://github.com/k2-fsa/sherpa-onnx/releases
    Expected files in model_dir:
      encoder-epoch-*.onnx, decoder-epoch-*.onnx, joiner-epoch-*.onnx, tokens.txt
    """

    def __init__(self, model_dir: Optional[str] = None):
        try:
            import sherpa_onnx  # noqa: F811
            self._sherpa = sherpa_onnx
        except ImportError:
            raise RuntimeError(
                "sherpa-onnx not installed. Install: pip install sherpa-onnx\n"
                "Then download a Chinese KWS model — see README.md"
            )

        model_dir = model_dir or os.environ.get("DOTA_KWS_MODEL_DIR", "./kws_model")
        if not os.path.isdir(model_dir):
            raise FileNotFoundError(
                f"KWS model directory not found: {model_dir}\n"
                f"Set DOTA_KWS_MODEL_DIR or place models in ./kws_model"
            )

        self._keywords = list(SKILLS.keys())
        self._kws, self._stream = self._init_kws(model_dir)
        print(f"[KWS] loaded model from {model_dir}, keywords: {self._keywords}")

    def _find_model_file(self, model_dir: str, pattern: str) -> str:
        """Find first file matching pattern in model_dir."""
        import glob
        matches = glob.glob(os.path.join(model_dir, pattern))
        if not matches:
            raise FileNotFoundError(f"No file matching '{pattern}' in {model_dir}")
        return matches[0]

    def _init_kws(self, model_dir: str):
        # Write keywords file
        kw_path = os.path.join(model_dir, "_keywords_generated.txt")
        with open(kw_path, "w", encoding="utf-8") as f:
            for kw in self._keywords:
                # sherpa-onnx keyword format: keyword /threshold
                f.write(f"{kw}\n")

        # Find model files (naming varies by model release)
        encoder = self._find_model_file(model_dir, "encoder*.onnx")
        decoder = self._find_model_file(model_dir, "decoder*.onnx")
        joiner = self._find_model_file(model_dir, "joiner*.onnx")
        tokens = os.path.join(model_dir, "tokens.txt")

        if not os.path.isfile(tokens):
            raise FileNotFoundError(f"tokens.txt not found in {model_dir}")

        kws = self._sherpa.KeywordSpotter(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            keywords_file=kw_path,
            num_threads=2,
            provider="cpu",
        )
        stream = kws.create_stream(keywords="\n".join(self._keywords))
        return kws, stream

    def accept_waveform(self, samples: np.ndarray):
        """Feed audio samples (float32, 16kHz mono)."""
        self._stream.accept_waveform(SAMPLE_RATE, samples.astype(np.float32))

    def get_keyword(self) -> Optional[str]:
        """Decode and check for keyword detection. Returns keyword or None."""
        while self._kws.is_ready(self._stream):
            self._kws.decode_stream(self._stream)

        result = self._kws.get_result(self._stream)
        keyword = result.strip() if isinstance(result, str) else ""
        if not keyword:
            return None
        # Normalize: extract just the keyword name
        for kw in self._keywords:
            if kw in keyword:
                return kw
        return None


# ──────────────────── Main application ──────────────────────
class VoiceInvoker:
    def __init__(self, kws: Optional[KeywordSpotter] = None, caster: Optional[InvokerCaster] = None):
        self.kws = kws  # lazily init in run() if None
        self.caster = caster or InvokerCaster()
        self.debouncer = Debouncer(DEBOUNCE_MS)
        self.audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=512)
        self.running = True

    def _audio_callback(self, indata, frames, time_info, status):
        mono = np.copy(indata[:, 0])
        try:
            self.audio_q.put_nowait(mono)
        except queue.Full:
            pass  # drop under pressure

    def _on_keyword(self, keyword: str):
        """Handle a detected keyword: debounce → log → cast."""
        t_start = time.monotonic()

        if not self.debouncer.should_trigger(keyword):
            print(f"[KWS] '{keyword}' debounced (within {DEBOUNCE_MS}ms)")
            return

        skill = SKILLS.get(keyword)
        if skill is None:
            print(f"[KWS] '{keyword}' has no skill mapping, ignored")
            return

        seq = format_key_sequence(skill)
        keys = self.caster.cast_skill(skill)
        elapsed_ms = (time.monotonic() - t_start) * 1000

        print(
            f"[KWS] keyword='{keyword}' | skill={skill.name} | "
            f"keys=[{', '.join(keys)}] | seq='{seq}' | "
            f"cast_time={elapsed_ms:.1f}ms"
        )

    def run(self):
        print("=" * 64)
        print("Dota2 Invoker Voice — Pure KWS Mode")
        print(f"关键词: {', '.join(SKILLS.keys())}")
        print(f"去抖动: {DEBOUNCE_MS}ms | 改键: QWER→ZXCV")
        print("按 Ctrl+C 退出")
        print("=" * 64)

        if self.kws is None:
            self.kws = KeywordSpotter()

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=self._audio_callback,
        ):
            while self.running:
                try:
                    block = self.audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue

                self.kws.accept_waveform(block)
                keyword = self.kws.get_keyword()
                if keyword:
                    self._on_keyword(keyword)

    def stop(self):
        self.running = False


# ──────────────────── Deprecated ASR code ───────────────────
# [DEPRECATED] The following classes are from the old ASR-based architecture.
# They are kept for reference only and are NOT used in the KWS pipeline.
# Do not instantiate or call these classes.

class _DeprecatedSenseVoiceClient:  # pragma: no cover
    """DEPRECATED: ASR client removed from active pipeline. Use KeywordSpotter instead."""

    def __init__(self, url: str = "http://localhost:8771/transcribe", timeout: int = 15):
        raise NotImplementedError("ASR pipeline is deprecated. Use KWS (KeywordSpotter) instead.")


class _DeprecatedSkillMatcher:  # pragma: no cover
    """DEPRECATED: Fuzzy matcher removed from active pipeline. KWS provides direct keyword detection."""

    def __init__(self):
        raise NotImplementedError("Fuzzy matcher is deprecated. KWS provides direct keyword detection.")


# ──────────────────── Entry point ───────────────────────────
def main():
    app = VoiceInvoker()

    def _stop(*_):
        app.stop()

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
