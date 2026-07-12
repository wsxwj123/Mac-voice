"""流式 /stream WebSocket 全流程测试。
用 sherpa 模型自带的真人语音 wav（macOS `say` 合成音小模型认不出，已实测）。
按 100ms 块发送 → 断言收到 draft 和 final。

跑: python test_stream.py   （首次跑会加载模型，约 1 分钟）
"""
import json
import os
from pathlib import Path

import numpy as np
import soundfile as sf
from starlette.testclient import TestClient

SR = 16000
CHUNK = 1600  # 100ms

import stream_asr

wav = stream_asr._model_dir() / "test_wavs" / "0.wav"
assert wav.exists(), f"缺测试音频 {wav}"
audio, sr = sf.read(wav, dtype="float32")
assert sr == SR
audio = np.concatenate([audio, np.zeros(SR, dtype=np.float32)])
print(f"测试语音 {len(audio)/SR:.1f}s")

from stt_server import app

drafts, finals = [], []
with TestClient(app) as client:
    with client.websocket_connect("/stream") as ws:
        for i in range(0, len(audio), CHUNK):
            ws.send_bytes(audio[i:i + CHUNK].tobytes())
        ws.send_text(json.dumps({"type": "end"}))
        while True:
            ev = ws.receive_json()
            if ev["type"] == "draft":
                drafts.append(ev["text"])
            elif ev["type"] == "final":
                finals.append(ev["text"])
                print("final:", ev["text"])
            elif ev["type"] == "done":
                break
            elif ev["type"] == "error":
                raise AssertionError(ev["text"])

print(f"\ndrafts={len(drafts)} 条, finals={len(finals)} 句")
assert drafts, "没收到任何 draft"
assert finals, "没收到任何 final"
assert any("一" <= c <= "鿿" for c in "".join(finals)), \
    f"定稿无中文: {finals}"
print("✓ 流式全流程测试通过")
