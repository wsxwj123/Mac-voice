"""左 Ctrl 多击检测自检：双击=原文，三击=整理，组合键不误触发。
跑: python test_hotkey.py"""
import voice_ime as v

calls = []
v.start_recording = lambda polish=False: calls.append(polish)
v.stop_recording = lambda: None


class FakeTimer:  # 不真跑定时器，测计数与模式判定
    def __init__(self, *a, **k):
        pass
    def start(self):
        pass
    def cancel(self):
        pass


v.threading.Timer = FakeTimer

CTRL = v.POLISH_KEY
OTHER = v.keyboard.KeyCode.from_char("c")


def _reset():
    calls.clear()
    v._tap_count = 0
    v._last_tap = 0.0
    v._other_since_ctrl = False
    v._ctrl_down = False
    v._ctrl_recording = False
    v._hold_timer = None


# 双击 → count 2 → 按住触发原文
_reset()
v.on_press(CTRL); v.on_press(CTRL)
assert v._tap_count == 2, v._tap_count
v._hold_fire(2)
assert calls == [False], f"双击应为原文, got {calls}"

# 三击 → count 3 → 按住触发整理
_reset()
v.on_press(CTRL); v.on_press(CTRL); v.on_press(CTRL)
assert v._tap_count == 3, v._tap_count
v._hold_fire(3)
assert calls == [True], f"三击应为整理, got {calls}"

# 单击按住 → count 1 → 不触发
_reset()
v.on_press(CTRL)
v._hold_fire(1)
assert calls == [], f"单击不应触发, got {calls}"

# ⌃C 组合键（中间按了 c）→ 计数重置，不误触发
_reset()
v.on_press(CTRL); v.on_press(OTHER); v.on_press(CTRL)
assert v._tap_count == 1, f"组合键应重置计数, got {v._tap_count}"
v._hold_fire(1)
assert calls == [], f"组合键不应触发, got {calls}"

print("✓ 多击检测测试通过")
