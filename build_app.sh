#!/bin/bash
# 生成 Mac-voice.app（壳 app，调用本机 venv 跑 voice_ime.py）
# 用法: ./build_app.sh [python路径]   默认 ./.venv/bin/python
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${1:-$PROJECT_DIR/.venv/bin/python}"
APP="$PROJECT_DIR/Mac-voice.app"

if [ ! -x "$PYTHON" ]; then
  echo "找不到 python: $PYTHON" >&2
  echo "用法: ./build_app.sh /绝对路径/python" >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Mac-voice</string>
  <key>CFBundleDisplayName</key><string>Mac-voice</string>
  <key>CFBundleIdentifier</key><string>io.macvoice.ime</string>
  <key>CFBundleExecutable</key><string>Mac-voice</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSMicrophoneUsageDescription</key><string>Mac-voice 需要使用麦克风进行语音识别。</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Mac-voice" <<LAUNCHER
#!/bin/bash
cd "$PROJECT_DIR" || exit 1
mkdir -p logs
export PYTHONUNBUFFERED=1
exec "$PYTHON" voice_ime.py >> logs/app.log 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/Mac-voice"

# 图标（若 AppIcon.icns 存在）
if [ -f "$PROJECT_DIR/AppIcon.icns" ]; then
  mkdir -p "$APP/Contents/Resources"
  cp "$PROJECT_DIR/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
fi

echo "✓ 生成 $APP"
echo "  双击运行，或 open '$APP'"
echo "  首次需在 系统设置→隐私与安全性 给它授权 辅助功能 + 麦克风"
