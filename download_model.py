"""预下载 SenseVoice-Small 模型到 ./models。
装好依赖后先跑这个，确认模型能下载成功，避免第一次录音时才发现下载失败。
跑: python download_model.py
"""
import os
import time
from pathlib import Path

ROOT = Path(__file__).parent
MODEL_CACHE = ROOT / "models"
MODEL_CACHE.mkdir(exist_ok=True)
os.environ["MODELSCOPE_CACHE"] = str(MODEL_CACHE)  # 与 stt_server.py 一致

print("下载 SenseVoice-Small（约 1GB，来源 ModelScope）…")
print("国外网络可能较慢，请耐心等待。")
t0 = time.time()
from funasr import AutoModel

AutoModel(model="iic/SenseVoiceSmall", trust_remote_code=False,
          disable_update=True, device="cpu")
print(f"✓ 模型就绪，存于 {MODEL_CACHE}（{time.time() - t0:.0f}s）")
print("现在可以启动 stt_server.py 了。")
