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

## 开机自启（可选）

`launchd/` 下有两个 plist 模板。替换占位符后安装：

```bash
# 把 __PROJECT_DIR__ 换成本仓库绝对路径，__PYTHON__ 换成 .venv/bin/python 绝对路径
cp launchd/*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.macvoice.stt.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.macvoice.ime.plist
```

> **注意**：launchd 启动的是 python 二进制，macOS 的麦克风/辅助功能权限按可执行文件授予，需要给那个 python 单独授权。无 .app 包的后台 python 在麦克风权限上可能受 TCC 限制——若授不上，仍用终端手动运行。

## 已知限制

- 仅 macOS（依赖 CoreGraphics 注入 + AppKit 浮窗）
- SenseVoice 不支持流式，松手后整段识别（非边说边出字）
- 文本光标精确定位不可靠，声波浮窗固定在屏幕底部居中

## License

MIT
