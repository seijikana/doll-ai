# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

**AI人形「こうぺんちゃん」** — Raspberry Pi Zero 2 W + Gemini Live API で動く子供向けリアルタイム音声会話人形。小学生の友達キャラクター「こうぺんちゃん（ペンギン）」として会話する。

## 開発・デプロイコマンド

### Windows PC → Raspberry Pi への転送

```powershell
# main.pyのみ
scp C:\Users\SEIJI\Documents\doll-ai\main.py pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/main.py

# 全ファイル
scp C:\Users\SEIJI\Documents\doll-ai\main.py C:\Users\SEIJI\Documents\doll-ai\setup.sh C:\Users\SEIJI\Documents\doll-ai\requirements.txt pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/
```

### Pi 上でのサービス操作（SSH経由）

```bash
sudo systemctl restart doll-ai   # 再起動
sudo systemctl status doll-ai    # 状態確認
journalctl -u doll-ai -f         # リアルタイムログ
```

### Pi 上で直接実行（デバッグ時）

```bash
# サービスを止めて手動実行
sudo systemctl stop doll-ai
sudo -u pi bash -c 'XDG_RUNTIME_DIR=/run/user/1000 GEMINI_API_KEY=... PYTHONUNBUFFERED=1 /home/pi/doll-ai/venv/bin/python /home/pi/doll-ai/main.py'
```

### 会話ログの取得（PC側）

```powershell
scp "pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/logs/*.txt" "C:\Users\SEIJI\Documents\doll-ai\logs\"
```

### 音声デバイス確認・テスト

```bash
aplay -l                                              # スピーカー確認（card 0 が出ればOK）
arecord -l                                            # マイク確認
speaker-test -D plughw:0,0 -t sine -f 440 -l 1       # スピーカーテスト
arecord -D plughw:0,0 -f S32_LE -r 16000 -c 1 -d 3 /tmp/test.wav  # 録音テスト
```

## アーキテクチャ

### 音声フロー

```
INMP441マイク(I2S) → sounddevice InputStream
    → PCM int32 → int16変換 + MIC_GAIN増幅
    → Gemini Live API (send_realtime_input, 16kHz)
    → 応答音声 (24kHz PCM)
    → sounddevice OutputStream → MAX98357Aアンプ(I2S) → スピーカー
```

### 3つの並列 asyncio タスク（`run_session`内）

| タスク | 役割 |
|---|---|
| `send_audio()` | マイク → Gemini へ音声を連続送信 |
| `receive_audio()` | Gemini からの応答受信・ログ記録・ミュート制御 |
| `play_audio()` | `audio_out_queue` からスピーカーへ再生 |

### エコー防止の仕組み

`mic_muted` フラグで制御。Gemini から音声データ（`response.data`）が届いたらマイクをミュート（無音データを送信）、`turn_complete` または `interrupted` を受信したら解除。

### デバイス設定

- `INPUT_DEVICE = 'doll_mic_raw'` — `/etc/asound.conf` で定義された plug→hw:0,0
- `OUTPUT_DEVICE = 'doll_spk_raw'` — 同上。PulseAudio のデフォルトデバイスを避けるため明示指定

`doll_mic`/`doll_spk`（softvol版）ではなく `doll_mic_raw`/`doll_spk_raw` を使うこと。softvol 経由だと PortAudio でフォーマット交渉に失敗する場合がある。

### トランスクリプションの扱い

`sc.input_transcription` と `sc.output_transcription` は文字列ではなく `Transcription` オブジェクト。`.text` プロパティで文字列を取得する。ログはリアルタイムで単語ごとに断片的に届く仕様（Gemini の streaming transcription）。

## 主要パラメータ（main.py）

| 定数 | 値 | 意味 |
|---|---|---|
| `MODEL` | `gemini-2.5-flash-native-audio-latest` | Gemini Live APIモデル |
| `MIC_GAIN` | `26.0` | INMP441は出力が弱いため増幅。peak 3000〜15000 が目安 |
| `SPEAKER_VOL` | `0.4` | 大きすぎるとビビり（歪み）が出る |
| `MIC_RATE` | `16000` Hz | マイクサンプリングレート |
| `SPK_RATE` | `24000` Hz | Gemini の音声出力に合わせる |

## 環境・インフラ

- **API キー**: Pi上の `/etc/doll-ai.env`（root のみ読み取り可）、systemd の `EnvironmentFile` で読み込む
- **ログ**: `/home/pi/doll-ai/logs/chat_YYYYMMDD_HHMMSS.txt` に自動保存
- **自動起動**: `ExecStartPre=/bin/sleep 8`（ネットワーク確立を待つため）
- **セッション再接続**: エラー時は5秒待って自動的に `run_session()` を再実行

## キャラクター設定変更時の注意

`SYSTEM_PROMPT` と `send_client_content`（初回挨拶）の両方を変更すること。初回挨拶のプロンプト文が毎回の会話の入り口を決める。勉強・クイズを強制する文言を入れると会話が一辺倒になる。

## WiFi設定変更

```bash
# Bookworm (NetworkManager)
sudo nmcli device wifi connect "SSID" password "パスワード"

# Bullseye 以前
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
```
