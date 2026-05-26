"""
doll-ai - AI Talking Doll App
Gemini Live API + I2S Mic (INMP441) + I2S Amp (MAX98357A)
Target: elementary school children
"""

import asyncio
import os
import signal
import sys
import time
from datetime import datetime
import numpy as np
import sounddevice as sd
from google import genai
from google.genai import types

# --- Config -----------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL   = "gemini-2.5-flash-native-audio-latest"

MIC_RATE      = 16000   # INMP441 input sample rate
SPK_RATE      = 24000   # MAX98357A output sample rate (matches Gemini output)
CHANNELS      = 1
CHUNK_MS      = 100     # Audio chunk length in ms
CHUNK_SIZE    = int(MIC_RATE * CHUNK_MS / 1000)
SPEAKER_VOL   = 0.4     # Speaker volume (0.0-1.0, lower if distorted)
MIC_GAIN      = 8.0     # Mic amplification (INMP441 output is very quiet)

# Conversation log directory
LOG_DIR       = "/home/pi/doll-ai/logs"

# I2S device (None = default from asound.conf)
INPUT_DEVICE  = None
OUTPUT_DEVICE = None

# --- Character prompt (for elementary school kids) --------------------
SYSTEM_PROMPT = """
あなたは「こうぺんちゃん」という名前のペンギンです。
南極からやってきた、おしゃべりが大好きなペンギンで、小学生の友達として毎日会話を楽しみます。

【キャラクター】
- 南極生まれの元気なペンギン。好奇心旺盛で、子供の話を聞くのが大好き
- 「ぺんぺん！」が口ぐせ
- 子供と対等な友達として話す。先生ではなく、一緒に楽しむ仲間

【話し方のルール】
- ひらがなとかんたんな漢字だけ使う（小学生が読めるレベル）
- 一度に話す文章は1〜2文まで。短くテンポよく
- 語尾は「だよ」「だね」「だぺん」など親しみやすく
- 子供の話に乗っかって、会話のキャッチボールを続ける
- 子供が話したことに共感・反応してから、自分の一言を添える

【会話のスタイル】
- 子供が話したことをまず受け止める（「そうなんだ！」「それおもしろいね！」）
- 質問するときは一度に1つだけ。あれこれ聞かない
- 子供の話題についていく。こちらから話題を変えない
- 楽しい・うれしい・びっくりなど、感情をリアクションで表現する
- 沈黙が続いたら「ねえねえ、さいきんどんなことしてるの？」など軽く話しかける

【やってはいけないこと】
- 勉強やクイズを出さない（求められたら答えてOK）
- 長い説明・情報の羅列はしない
- こわい話や暗い話はしない
- 個人情報（名前・住所・学校名）は聞かない
- 一方的に話し続けない
"""
# ----------------------------------------------------------------------


class ConversationLogger:
    """Log conversation transcriptions to a text file"""
    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(LOG_DIR, f"chat_{timestamp}.txt")
        self.f = open(self.path, "a", encoding="utf-8")
        self.f.write(f"=== Session started: {datetime.now()} ===\n")
        self.f.flush()
        print(f"[LOG] Saving to {self.path}")

    def log(self, role, text):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {role}: {text}\n"
        self.f.write(line)
        self.f.flush()
        print(f"[LOG] {role}: {text[:60]}")

    def close(self):
        self.f.write(f"=== Session ended: {datetime.now()} ===\n")
        self.f.close()


async def run_session(client: genai.Client):
    """Run one Gemini Live session"""
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_PROMPT)]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Leda"
                )
            )
        ),
    )

    mic_stream = None
    spk_stream = None
    logger = ConversationLogger()

    # Mic mute flag: True while Gemini is speaking (prevent echo feedback)
    mic_muted = False

    print("Connecting to Gemini...")
    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            print("Connected! Speak to the doll.")

            # Request initial greeting
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text="こんにちは！南極からきたペンギンのこうぺんちゃんとして自己紹介をして、今日は何を一緒に勉強したいか聞いてね。")]
                ),
                turn_complete=True,
            )

            audio_out_queue: asyncio.Queue[bytes] = asyncio.Queue()
            loop = asyncio.get_event_loop()
            session_active = True

            # -- Mic -> Gemini (send audio) ----------------------------
            async def send_audio():
                nonlocal mic_stream
                mic_queue: asyncio.Queue[bytes] = asyncio.Queue()
                mic_count = [0]

                def mic_callback(indata, frames, time_info, status):
                    if status:
                        print(f"Mic warning: {status}", file=sys.stderr)
                    # INMP441 outputs 32-bit; convert to 16-bit and amplify
                    samples = np.frombuffer(bytes(indata), dtype=np.int32)
                    boosted = (samples >> 16).astype(np.float32) * MIC_GAIN
                    pcm16 = np.clip(boosted, -32768, 32767).astype(np.int16)
                    mic_count[0] += 1
                    if mic_count[0] % 100 == 1:
                        peak = np.max(np.abs(pcm16))
                        mute_str = " [MUTED]" if mic_muted else ""
                        print(f"[MIC] peak={peak}{mute_str}")
                    loop.call_soon_threadsafe(mic_queue.put_nowait, pcm16.tobytes())

                mic_stream = sd.InputStream(
                    samplerate=MIC_RATE,
                    channels=CHANNELS,
                    dtype="int32",
                    blocksize=CHUNK_SIZE,
                    device=INPUT_DEVICE,
                    callback=mic_callback,
                )
                mic_stream.start()
                try:
                    while session_active:
                        try:
                            data = await asyncio.wait_for(mic_queue.get(), timeout=0.5)
                            if mic_muted:
                                # Send silence instead of mic audio while Gemini speaks
                                data = b'\x00' * len(data)
                            await session.send_realtime_input(
                                audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={MIC_RATE}")
                            )
                        except asyncio.TimeoutError:
                            continue
                finally:
                    mic_stream.stop()
                    mic_stream.close()
                    mic_stream = None

            # -- Gemini -> receive audio -------------------------------
            recv_count = [0]
            async def receive_audio():
                nonlocal session_active, mic_muted
                try:
                    while session_active:
                        async for response in session.receive():
                            if not session_active:
                                break

                            # Log transcriptions
                            if hasattr(response, 'server_content') and response.server_content:
                                sc = response.server_content
                                # Log input transcription (what user said)
                                if hasattr(sc, 'input_transcription') and sc.input_transcription:
                                    logger.log("USER", sc.input_transcription)
                                # Log output transcription (what Gemini said)
                                if hasattr(sc, 'output_transcription') and sc.output_transcription:
                                    logger.log("KOUPEN", sc.output_transcription)
                                # Check turn_complete to unmute mic
                                if hasattr(sc, 'turn_complete') and sc.turn_complete:
                                    mic_muted = False
                                    print("[STATE] Gemini done speaking, mic ON")
                                # Check interrupted
                                if hasattr(sc, 'interrupted') and sc.interrupted:
                                    mic_muted = False
                                    print("[STATE] Interrupted, mic ON")

                            if response.data:
                                # Mute mic while playing Gemini's audio
                                if not mic_muted:
                                    mic_muted = True
                                    print("[STATE] Gemini speaking, mic MUTED")
                                recv_count[0] += 1
                                if recv_count[0] % 50 == 1:
                                    print(f"[RECV] chunks={recv_count[0]}")
                                await audio_out_queue.put(response.data)

                except Exception as e:
                    print(f"[RECV] Session ended: {e}")
                finally:
                    session_active = False

            # -- Speaker playback --------------------------------------
            async def play_audio():
                nonlocal spk_stream
                spk_stream = sd.OutputStream(
                    samplerate=SPK_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    device=OUTPUT_DEVICE,
                )
                spk_stream.start()
                try:
                    while session_active:
                        try:
                            data = await asyncio.wait_for(audio_out_queue.get(), timeout=0.5)
                            samples = np.frombuffer(data, dtype=np.int16)
                            samples = (samples.astype(np.float32) * SPEAKER_VOL).astype(np.int16)
                            spk_stream.write(samples)
                        except asyncio.TimeoutError:
                            continue
                finally:
                    spk_stream.stop()
                    spk_stream.close()
                    spk_stream = None

            # Run all tasks
            tasks = [
                asyncio.create_task(send_audio()),
                asyncio.create_task(receive_audio()),
                asyncio.create_task(play_audio()),
            ]
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                pass

    finally:
        # Ensure streams are closed even on unexpected errors
        if mic_stream is not None:
            mic_stream.stop()
            mic_stream.close()
        if spk_stream is not None:
            spk_stream.stop()
            spk_stream.close()
        logger.close()


async def main():
    if not API_KEY:
        print("Error: GEMINI_API_KEY is not set")
        print("  export GEMINI_API_KEY='your-api-key'")
        sys.exit(1)

    client = genai.Client(
        api_key=API_KEY,
        http_options={"api_version": "v1beta"}
    )

    print("Starting doll-ai... (Ctrl+C to stop)")
    while True:
        try:
            await run_session(client)
        except Exception as e:
            print(f"Error: {e}")
            print("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    # Ctrl+C handler: force exit immediately
    signal.signal(signal.SIGINT, lambda *_: (print("\nStopped."), os._exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (print("\nStopped."), os._exit(0)))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
