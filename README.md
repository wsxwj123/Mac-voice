# Mac-voice

本地、隐私优先的 macOS 语音输入法。按住热键说话，松手把识别文字注入当前光标处。

- **STT**: [SenseVoice-Small](https://github.com/FunAudioLLM/SenseVoice)（本地 CPU 推理，中文 CER ~3%，支持中英日韩粤 + 情绪/事件识别）
- **交互**: push-to-talk（按住右 Option 说话 → 松手 → 注入），录音时屏幕底部显示实时声波
- **注入**: 剪贴板 + 模拟 ⌘V，兼容所有 App，注入后恢复原剪贴板
- 全程本地，不联网，无云 API

## 架构

```
按住右 Option ─▶ 麦克风采集 ─▶ 临时 wav ─▶ HTTP POST ─▶ stt_server (SenseVoice)
                                                              │
            注入光标处 ◀─ 剪贴板+⌘V ◀────── 识别文字 ◀────────┘
```

两个进程：`stt_server.py`（常驻 STT 服务，127.0.0.1:7788）+ `voice_ime.py`（输入法客户端）。

## 安装

需要 Python 3.10+ 和 [ffmpeg](https://ffmpeg.org/)（`brew install ffmpeg portaudio`）。

```bash
git clone https://github.com/wsxwj123/Mac-voice.git
cd Mac-voice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 运行

```bash
# 终端 1：STT 服务（首次会下载 ~1GB 模型到 ./models）
python stt_server.py

# 终端 2：输入法
python voice_ime.py
```

点进任意输入框，**按住右 Option 说话，松手**，文字注入光标处。

### 权限（macOS）

首次运行会请求两项权限，必须授予：

- **辅助功能**（系统设置→隐私与安全性→辅助功能）：全局热键 + 模拟 ⌘V 注入
- **麦克风**

> 终端手动运行时，权限授予运行它的终端 App。

### 选麦克风

默认跟随系统默认输入设备（系统设置→声音→**输入**）。要锁定某个设备：

```bash
VOICE_IME_DEVICE='AirPods' python voice_ime.py   # 名字片段匹配
```

### 调试开关

| 环境变量 | 作用 |
|---|---|
| `NO_INJECT=1` | 只识别打印，不注入 |
| `NO_OVERLAY=1` | 不显示声波浮窗 |
| `VOICE_IME_DEVICE` | 指定输入设备（名字片段或索引） |
| `VOICE_IME_HOTKEY` | 热键，默认 `right_option`。没有右 Option 的键盘可改：`right_cmd` / `right_ctrl` / `right_shift` / `left_option` / `caps_lock` |

## 打包成 .app（推荐）

把客户端包成一个 `.app`，权限按 bundle 归属（比裸 python 更稳），可双击启动、设为登录项。STT 服务仍单独跑。

```bash
./build_app.sh            # 默认用 ./.venv/bin/python
# 或指定: ./build_app.sh /绝对路径/python
open Mac-voice.app        # 启动
```

这是个**壳 app**：bundle 里只放 Info.plist + 启动器，调用本机 venv 跑 `voice_ime.py`，不打包 Python 依赖（依赖留在 venv）。所以换机器需重新 `build_app.sh`。

首次运行去 系统设置→隐私与安全性 给 **Mac-voice** 授权 辅助功能 + 麦克风。

### 开机自启

把 `Mac-voice.app` 拖进 系统设置→通用→登录项，或：

```bash
osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Mac-voice.app", hidden:true}'
```

STT 服务用 `launchd/io.macvoice.stt.plist` 模板自启（替换占位符后 `launchctl bootstrap gui/$(id -u) ...`）。

> 备选：`launchd/io.macvoice.ime.plist` 也能直接跑 python，但 launchd 的裸 python 在麦克风权限（TCC）上可能授不上，所以推荐 .app。

## 已知限制

- 仅 macOS（依赖 CoreGraphics 注入 + AppKit 浮窗）
- SenseVoice 不支持流式，松手后整段识别（非边说边出字）
- 文本光标精确定位不可靠，声波浮窗固定在屏幕底部居中

## License

MIT
