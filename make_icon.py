"""生成 app 图标 PNG（蓝紫渐变圆角 + 白色声波竖条）。
跑: python make_icon.py out.png   然后用 sips/iconutil 转 .icns（见 build_app.sh）。"""
import sys
from AppKit import (
    NSBitmapImageRep, NSGraphicsContext, NSColor, NSBezierPath, NSGradient,
    NSDeviceRGBColorSpace, NSMakeRect,
)

S = 1024
rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, S, S, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
)
ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(ctx)

# 圆角渐变背景（macOS 图标风格圆角）
radius = S * 0.225
bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
    NSMakeRect(0, 0, S, S), radius, radius
)
grad = NSGradient.alloc().initWithStartingColor_endingColor_(
    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.29, 0.56, 0.98, 1.0),
    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.52, 0.30, 0.92, 1.0),
)
grad.drawInBezierPath_angle_(bg, -90.0)

# 白色对称声波竖条
NSColor.whiteColor().set()
heights = [0.28, 0.52, 0.78, 1.0, 0.78, 0.52, 0.28]
n = len(heights)
bw = S * 0.058
gap = S * 0.048
total = n * bw + (n - 1) * gap
x0 = (S - total) / 2.0
mid_y = S / 2.0
max_h = S * 0.44
for i, h in enumerate(heights):
    bh = max_h * h
    x = x0 + i * (bw + gap)
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, mid_y - bh / 2, bw, bh), bw / 2, bw / 2
    ).fill()

NSGraphicsContext.restoreGraphicsState()
png = rep.representationUsingType_properties_(4, {})  # 4 = PNG
png.writeToFile_atomically_(sys.argv[1], True)
print("wrote", sys.argv[1])
