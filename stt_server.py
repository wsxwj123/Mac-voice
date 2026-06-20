"""
SenseVoice STT HTTP 服务（精简版，给本地语音输入法用）
========================================================
端点：
  GET  /health           → {ok, model_loaded}
  POST /transcribe_file   {path}  → {text, emotion, events, language, duration_sec, latency_ms}

运行：
  python stt_server.py
  # 或 uvicorn stt_server:app --host 127.0.0.1 --port 7788

首次启动会自动从 ModelScope 下载 SenseVoice-Small（~1GB），存到 ./models。
"""
import os
import re
import time
import asyncio
import logging
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager

ROOT = Path(__file__).parent
MODEL_CACHE = ROOT / "models"
MODEL_CACHE.mkdir(exist_ok=True)
os.environ["MODELSCOPE_CACHE"] = str(MODEL_CACHE)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("stt")

EMOTION_TAGS = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED"}
EVENT_TAGS = {"BGM", "Speech", "Applause", "Laughter", "Cry"}
LANG_TAGS = {"zh", "en", "ja", "ko", "yue", "auto", "nospeech"}
TAG_RE = re.compile(r"<\|([^|]+)\|>")


def parse_sensevoice_output(raw: str, duration: float) -> dict[str, Any]:
    tags = TAG_RE.findall(raw)
    text = TAG_RE.sub("", raw).strip()
    emotion, events, language = "UNKNOWN", [], "unknown"
    for t in tags:
        if t in EMOTION_TAGS:
            emotion = t
        elif t in EVENT_TAGS:
            events.append(t)
        elif t in LANG_TAGS:
            language = t
    if duration < 1.5:
        emotion = "UNKNOWN"
    return {"text": text, "emotion": emotion, "events": events, "language": language}


_model = None
_model_lock = asyncio.Lock()


async def get_model():
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is not None:
            return _model
        log.info("加载 SenseVoice-Small 模型…")
        t0 = time.time()
        loop = asyncio.get_event_loop()
        from funasr import AutoModel

        _model = await loop.run_in_executor(None, lambda: AutoModel(
            model="iic/SenseVoiceSmall", trust_remote_code=False,
            disable_update=True, device="cpu",
        ))
        log.info(f"✓ 模型加载完成 {time.time() - t0:.1f}s")
        return _model


async def transcribe_file(audio_path: str) -> dict[str, Any]:
    if not os.path.exists(audio_path):
        raise FileNotFoundError(audio_path)
    import soundfile as sf
    try:
        info = sf.info(audio_path)
        duration = info.frames / info.samplerate
    except Exception:
        duration = 0.0

    model = await get_model()
    t0 = time.time()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: model.generate(
        input=audio_path, cache={}, language="auto", use_itn=True, batch_size_s=60,
    ))
    latency = int((time.time() - t0) * 1000)
    raw = result[0]["text"] if result else ""
    parsed = parse_sensevoice_output(raw, duration)
    parsed["duration_sec"] = round(duration, 2)
    parsed["latency_ms"] = latency
    log.info(f"STT: {duration:.1f}s → {len(parsed['text'])}字, "
             f"情绪={parsed['emotion']}, {latency}ms")
    return parsed


from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(get_model())  # 启动预热
    yield


app = FastAPI(lifespan=lifespan)


class TranscribeReq(BaseModel):
    path: str


@app.get("/health")
async def health():
    return {"ok": True, "model_loaded": _model is not None}


@app.post("/transcribe_file")
async def api_transcribe_file(req: TranscribeReq):
    try:
        return await transcribe_file(req.path)
    except Exception as e:
        log.exception("transcribe_file 失败")
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7788, log_level="warning")
