"""双击左 Control 检测的最小自检：确保组合键(⌃C/⌃V)不会误触发整理。
跑: python test_hotkey.py"""
import voice_ime as v

calls = []
v.start_recording = lambda polish=False: calls.append(polish)
v.stop_recording = lambda: None

CTRL = v.POLISH_KEY
OTHER = v.keyboard.KeyCode.from_char("c")


def _reset():
    calls.clear()
    v._last_ctrl_press = 0.0
    v._other_since_ctrl = False
    v._ctrl_recording = False


# 双击 Control（中间无其他键）→ 触发整理录音
_reset()
v.on_press(CTRL)
v.on_press(CTRL)
assert calls == [True], f"双击应触发整理, got {calls}"

# ⌃C 组合键（中间按了 c）→ 不触发
_reset()
v.on_press(CTRL)
v.on_press(OTHER)
v.on_press(CTRL)
assert calls == [], f"组合键不应触发, got {calls}"

# 单击 Control → 不触发
_reset()
v.on_press(CTRL)
assert calls == [], f"单击不应触发, got {calls}"

print("✓ 双击检测测试通过")
