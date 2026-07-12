"""
流式识别 WebSocket 端点（2-pass: sherpa-onnx 草稿+断句 → SenseVoice 定稿）
==========================================================================
挂载: app.include_router(stream_asr.router)，并 set_offline_model_getter()
     注入宿主已加载的 SenseVoice AutoModel（定稿用）。

引擎说明: 原计划用 FunASR paraformer-zh-streaming，实测 M4 Pro CPU 上
600ms chunk 需 ~830ms（RTF>1 不可用）；换 sherpa-onnx streaming zipformer
（14M int8，100ms 块解码 ~1.3ms，RTF≈0.01），且自带 endpoint 检测，免独立 VAD。
草稿仅供浮窗展示（小模型），定稿由 SenseVoice 保证准确率。

协议:
  C→S  二进制帧: PCM float32 mono 16kHz（任意长度）
       文本帧:  {"type":"end"}
  S→C  {"type":"draft","text":...}   当前句实时草稿（全量替换语义）
       {"type":"final","text":...}   一句定稿（SenseVoice，含标点）
       {"type":"done"}
"""
import os
import json
import time
import asyncio
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("stream-asr")
router = APIRouter()

SR = 16000
END_SILENCE_SEC = int(os.environ.get("STREAM_END_SILENCE_MS", "800")) / 1000.0
MAX_SEGMENT_SEC = 30                    # 单句超长强制定稿
MIN_SEGMENT_SEC = 0.25                  # 碎段丢弃

STREAM_MODEL = "sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23"


def _model_dir() -> Path:
    if os.environ.get("STREAM_MODEL_DIR"):
        return Path(os.environ["STREAM_MODEL_DIR"])
    cache = Path(os.environ.get("MODELSCOPE_CACHE",
                                Path(__file__).parent / "models"))
    return cache / STREAM_MODEL


_executor = ThreadPoolExecutor(max_workers=2)  # ponytail: 单用户输入法，2 线程够
_lock = threading.Lock()
_recognizer = None
_get_offline = None                     # 宿主注入: () -> AutoModel(SenseVoice)


def set_offline_model_getter(fn):
    global _get_offline
    _get_offline = fn


def _load_recognizer():
    global _recognizer
    with _lock:
        if _recognizer is not None:
            return
        import sherpa_onnx
        d = _model_dir()
        if not d.exists():
            raise RuntimeError(
                f"流式模型缺失: {d}\n"
                f"下载: https://github.com/k2-fsa/sherpa-onnx/releases/"
                f"download/asr-models/{STREAM_MODEL}.tar.bz2 解压到该目录")
        t0 = time.time()
        _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(d / "tokens.txt"),
            encoder=str(d / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(d / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(d / "joiner-epoch-99-avg-1.int8.onnx"),
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,   # 无文字时长静音
            rule2_min_trailing_silence=END_SILENCE_SEC,  # 有文字后的停顿=句子结束
            rule3_min_utterance_length=300,
            provider="cpu", num_threads=2,
        )
        log.info(f"✓ 流式 zipformer 加载 {time.time() - t0:.1f}s ({d.name})")


def _sensevoice_text(audio: np.ndarray) -> str:
    """段音频 → SenseVoice 定稿文本（同步，线程池内调用）"""
    import re
    model = _get_offline()
    res = model.generate(input=audio, fs=SR, cache={}, language="auto",
                         use_itn=True, batch_size_s=60)
    raw = res[0]["text"] if res else ""
    return re.sub(r"<\|[^|]+\|>", "", raw).strip()


@router.websocket("/stream")
async def stream_endpoint(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(_executor, _load_recognizer)
    except Exception as e:
        log.error(str(e))
        await ws.send_json({"type": "error", "text": str(e)})
        await ws.close()
        return

    rec = _recognizer
    s = rec.create_stream()
    seg = [np.zeros(0, dtype=np.float32)]   # 当前句累计音频
    last_draft = [""]
    log.info("流式会话开始")

    async def finalize():
        audio = seg[0]
        seg[0] = np.zeros(0, dtype=np.float32)
        last_draft[0] = ""
        if len(audio) < SR * MIN_SEGMENT_SEC:
            return
        if float(np.sqrt(np.mean(audio ** 2))) < 3e-4:
            return  # 近静音段跳过（SenseVoice 对静音会幻觉出 "Yeah." 等）
        t0 = time.time()
        text = await loop.run_in_executor(_executor, _sensevoice_text, audio)
        if text:
            log.info(f"  final({len(audio)/SR:.1f}s→"
                     f"{int((time.time()-t0)*1000)}ms): {text}")
            await ws.send_json({"type": "final", "text": text})

    async def feed(block: np.ndarray):
        seg[0] = np.concatenate([seg[0], block])
        s.accept_waveform(SR, block)
        while rec.is_ready(s):
            rec.decode_stream(s)          # ~1-5ms，可在事件循环内跑
        draft = rec.get_result(s)
        if draft and draft != last_draft[0]:
            last_draft[0] = draft
            await ws.send_json({"type": "draft", "text": draft})
        if rec.is_endpoint(s) or len(seg[0]) > SR * MAX_SEGMENT_SEC:
            rec.reset(s)
            await finalize()

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await feed(np.frombuffer(msg["bytes"], dtype=np.float32))
            elif msg.get("text"):
                if json.loads(msg["text"]).get("type") == "end":
                    await finalize()
                    await ws.send_json({"type": "done"})
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception(f"流式会话异常: {e}")
    finally:
        log.info("流式会话结束")
