"""
本地语音输入法 — push-to-talk
================================================
按住热键(默认右 Option)说话 → 松手 → SenseVoice 识别 → 注入光标处。
录音时屏幕底部居中显示浮动指示器(麦克风 + 音量波形)。

运行：
    python voice_ime.py

环境变量：
    VOICE_IME_DEVICE   指定输入设备(名字片段或索引)，默认系统默认
    NO_INJECT=1        只识别不注入(调试)
    NO_OVERLAY=1       不显示浮窗(调试)

前置：STT 服务(stt_server.py)在 127.0.0.1:7788；已获 辅助功能 + 麦克风 权限。
"""
import os
import sys
import json
import time
import tempfile
import threading
import urllib.request
from collections import deque
from pathlib import Path

import objc
import numpy as np
import soundfile as sf
import sounddevice as sd
from pynput import keyboard

from AppKit import (
    NSApplication, NSPanel, NSColor, NSView, NSScreen, NSBezierPath,
    NSPasteboard, NSPasteboardTypeString,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered, NSFloatingWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSApplicationActivationPolicyAccessory,
)
from Quartz import (
    CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap,
    CGEventSetFlags, kCGEventFlagMaskCommand,
)
from ApplicationServices import (
    AXIsProcessTrusted, AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)
from Foundation import NSTimer, NSMakeRect, NSObject
from PyObjCTools import AppHelper

# ---------- 配置 ----------
STT_URL = "http://127.0.0.1:7788/transcribe_file"
HEALTH_URL = "http://127.0.0.1:7788/health"
SAMPLE_RATE = 16000          # SenseVoice 要求 16kHz
HOTKEY = keyboard.Key.alt_r  # 右 Option，按住录音
MIN_DURATION = 0.3           # 短于此忽略（防误触）
DEVICE = os.environ.get("VOICE_IME_DEVICE") or None
NO_INJECT = os.environ.get("NO_INJECT") == "1"
NO_OVERLAY = os.environ.get("NO_OVERLAY") == "1"

# ---------- 共享状态 ----------
_recording = False
_frames: list[np.ndarray] = []
_lock = threading.Lock()
_stream: "sd.InputStream | None" = None
_last_rms = 0.0              # 最近音量，浮窗波形用
_state = "hidden"           # hidden | recording | thinking


# ---------- 文字注入（剪贴板 + CGEvent 模拟 Cmd+V） ----------
def _get_clipboard():
    return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)


def _set_clipboard(s: str):
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(s, NSPasteboardTypeString)


def _paste_cmd_v():
    V = 9  # kVK_ANSI_V
    down = CGEventCreateKeyboardEvent(None, V, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    up = CGEventCreateKeyboardEvent(None, V, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


def inject_text(text: str):
    old = _get_clipboard()
    _set_clipboard(text)
    time.sleep(0.05)
    _paste_cmd_v()
    time.sleep(0.15)
    if old is not None:
        _set_clipboard(old)


# ---------- 浮动指示器（语音备忘录式实时声波） ----------
N_BARS = 26      # 竖条数
BAR_W = 3.0      # 条宽
BAR_GAP = 2.0    # 条间距
PAD_X = 12.0     # 左右内边距
PAD_Y = 7.0      # 上下内边距


class WaveView(NSView):
    """对称竖条声波，从中线上下延伸，随音量滚动。"""

    def initWithFrame_(self, frame):
        self = objc.super(WaveView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.levels = [0.0] * N_BARS
        return self

    @objc.python_method
    def push(self, lv):
        self.levels = self.levels[1:] + [max(0.0, min(1.0, lv))]
        self.setNeedsDisplay_(True)

    @objc.python_method
    def reset(self):
        self.levels = [0.0] * N_BARS
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        w = rect.size.width
        h = rect.size.height
        # 圆角半透明深色背景胶囊
        bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, h / 2.0, h / 2.0
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.78).set()
        bg.fill()
        # 声波竖条
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.95).set()
        mid_y = h / 2.0
        max_bar = h - 2 * PAD_Y
        for i, lv in enumerate(self.levels):
            bar_h = max(BAR_W, lv * max_bar)
            x = PAD_X + i * (BAR_W + BAR_GAP)
            r = NSMakeRect(x, mid_y - bar_h / 2.0, BAR_W, bar_h)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                r, BAR_W / 2.0, BAR_W / 2.0
            ).fill()


class Overlay:
    """屏幕底部居中、无焦点的细长声波浮窗。"""

    def __init__(self):
        w = 2 * PAD_X + N_BARS * (BAR_W + BAR_GAP) - BAR_GAP
        h = 44.0
        screen = NSScreen.mainScreen().frame()
        x = (screen.size.width - w) / 2
        y = 16  # 贴屏幕最底部
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False,
        )
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setHasShadow_(False)
        self.panel.setBecomesKeyOnlyIfNeeded_(True)
        self.panel.setFloatingPanel_(True)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
        )
        self.view = WaveView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self.panel.setContentView_(self.view)

        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.05, True, lambda t: self._tick()
        )

    def _tick(self):
        if _state == "recording":
            # sqrt 映射放大小音量，振幅更明显
            self.view.push(min(1.0, (_last_rms ** 0.5) * 3.8))

    def show(self):
        self.view.reset()
        self.panel.orderFrontRegardless()  # 不 makeKey，不抢焦点

    def hide(self):
        self.panel.orderOut_(None)


_overlay: "Overlay | None" = None


def _ui(fn):
    """在主线程跑 UI 操作"""
    if _overlay is not None:
        AppHelper.callAfter(fn)


# ---------- 录音 ----------
def _audio_callback(indata, frames, time_info, status):
    global _last_rms
    if status:
        print(f"[音频] {status}", file=sys.stderr)
    with _lock:
        if _recording:
            _frames.append(indata.copy())
            _last_rms = float(np.sqrt(np.mean(indata ** 2)))


def start_recording():
    global _recording, _state
    with _lock:
        if _recording:
            return
        _frames.clear()
        _recording = True
    _state = "recording"
    print("🎙️  录音中…（松手结束）")
    _ui(lambda: _overlay.show())


def stop_recording():
    global _recording, _state
    with _lock:
        if not _recording:
            return
        _recording = False
        frames = list(_frames)
        _frames.clear()

    if not frames:
        _state = "hidden"
        _ui(lambda: _overlay.hide())
        return
    audio = np.concatenate(frames, axis=0).reshape(-1)
    duration = len(audio) / SAMPLE_RATE
    if duration < MIN_DURATION:
        print(f"（太短 {duration:.2f}s，忽略）")
        _state = "hidden"
        _ui(lambda: _overlay.hide())
        return

    print(f"⏳ 识别中… ({duration:.1f}s)")
    _state = "hidden"
    _ui(lambda: _overlay.hide())  # 松手即消失，识别在后台静默
    threading.Thread(target=_transcribe, args=(audio,), daemon=True).start()


def _transcribe(audio: np.ndarray):
    global _state
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio, SAMPLE_RATE)
        tmp_path = tmp.name
    try:
        t0 = time.time()
        payload = json.dumps({"path": tmp_path}).encode()
        req = urllib.request.Request(
            STT_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        ms = int((time.time() - t0) * 1000)
        text = result.get("text", "").strip()
        emo = result.get("emotion", "?")
        lang = result.get("language", "?")
        print(f"📝 「{text}」  [{lang} {emo} {ms}ms]")
        if text and not NO_INJECT:
            try:
                inject_text(text)
                print("   ↳ 已注入光标处\n")
            except Exception as e:
                print(f"   ↳ ❌ 注入失败: {e}\n", file=sys.stderr)
        else:
            print()
    except Exception as e:
        print(f"❌ 识别失败: {e}", file=sys.stderr)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        _state = "hidden"
        _ui(lambda: _overlay.hide())


# ---------- 热键 ----------
def on_press(key):
    try:
        if key == HOTKEY:
            start_recording()
    except Exception as e:
        print(f"❌ on_press 异常: {e}", file=sys.stderr)


def on_release(key):
    try:
        if key == HOTKEY:
            stop_recording()
    except Exception as e:
        print(f"❌ on_release 异常: {e}", file=sys.stderr)


# ---------- 启动 ----------
def check_service(retries=30, interval=2.0):
    """等待 STT 就绪（开机自启时本服务可能先于 STT 启动）"""
    for i in range(retries):
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:
                if json.loads(r.read()).get("ok"):
                    print("✓ STT 服务在线 (127.0.0.1:7788)")
                    return True
        except Exception:
            if i == 0:
                print("⏳ 等待 STT 服务就绪…")
        time.sleep(interval)
    print("❌ STT 服务超时未就绪", file=sys.stderr)
    return False


# 常见虚拟/聚合驱动名（仅用于提示，不改变设备选择）
VIRTUAL_HINTS = (
    "omi", "wemeet", "aggregate", "multi-output", "blackhole",
    "soundflower", "loopback", "zoom", "krisp", "background music",
)


def start_audio_stream():
    """跟随系统默认输入设备（VOICE_IME_DEVICE 可覆盖，支持名字片段）"""
    global _stream
    dev_info = sd.query_devices(DEVICE, kind="input")
    print(f"🎤 输入设备: {dev_info['name']}  (改设备: 设 VOICE_IME_DEVICE=名字片段)")
    if any(h in dev_info["name"].lower() for h in VIRTUAL_HINTS):
        print("⚠️  默认输入是虚拟驱动，可能录不到人声。", file=sys.stderr)
        print("   去 系统设置→声音→输入 选真实麦克风，或设 VOICE_IME_DEVICE 锁定。",
              file=sys.stderr)
    _stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32",
        device=DEVICE, callback=_audio_callback,
    )
    _stream.start()


def main():
    global _overlay
    print("=" * 48)
    print("  本地语音输入法 — push-to-talk")
    print("=" * 48)
    if not check_service():
        print("请先确认 STT 服务在运行。", file=sys.stderr)
        sys.exit(1)
    try:
        start_audio_stream()
    except Exception as e:
        print(f"❌ 麦克风启动失败: {e}", file=sys.stderr)
        print("  → 检查 系统设置→隐私与安全性→麦克风 是否授权；", file=sys.stderr)
        print("  → 或换设备：VOICE_IME_DEVICE='MacBook' 跑", file=sys.stderr)
        sys.exit(1)
    if not NO_INJECT and not AXIsProcessTrusted():
        print("⚠️  未获辅助功能权限 → 注入会失败，正在弹出授权框…", file=sys.stderr)
        print("   把弹框里的 Python 加入 系统设置→隐私与安全性→辅助功能。\n", file=sys.stderr)
        try:
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        except Exception:
            pass

    # NSApplication 主循环 + 后台 listener
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # 不在 Dock 显示
    if not NO_OVERLAY:
        _overlay = Overlay()
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    print("热键：按住【右 Option】说话，松手识别。Ctrl-C 退出。\n")
    try:
        AppHelper.runEventLoop()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        if _stream is not None:
            _stream.stop()
            _stream.close()
    print("\n已退出。")


if __name__ == "__main__":
    main()
