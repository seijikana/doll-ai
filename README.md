# AI人形「こうぺんちゃん」

Raspberry Pi Zero 2 W + Gemini Live API で動く子供向けAI会話人形

## ファイル構成

```
doll-ai/
├── main.py          # メインアプリ（Gemini Live + I2S音声入出力）
├── requirements.txt # Pythonパッケージ
├── setup.sh         # Piセットアップスクリプト
├── logs/            # 会話ログ（自動生成）
└── README.md
```

## Raspberry Piへの転送

WindowsからPiへファイルをコピー:
```
scp C:\Users\SEIJI\doll-ai\main.py pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/main.py
```

全ファイル転送:
```
scp C:\Users\SEIJI\doll-ai\main.py C:\Users\SEIJI\doll-ai\setup.sh C:\Users\SEIJI\doll-ai\requirements.txt pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/
```

## セットアップ

Pi上で実行:
```bash
bash /home/pi/doll-ai/setup.sh
```

## 手動テスト

```bash
source /home/pi/doll-ai/venv/bin/activate
python /home/pi/doll-ai/main.py
```

Ctrl+C で停止。

---

## ハードウェア

### 部品リスト

| 部品 | 型番 | 用途 |
|---|---|---|
| マイコン | Raspberry Pi Zero 2 W | メイン基板 |
| マイク | INMP441 | I2S MEMSマイク（32bit出力） |
| アンプ | MAX98357A | I2S D級アンプ |
| スピーカー | φ28mm 4Ω | 小型スピーカー |
| 電源 | モバイルバッテリー | USB-C給電 |

### I2S配線図

#### INMP441（マイク）→ Pi Zero 2 W

| INMP441 | → | Pi Zero 2 W | ピン番号 |
|---|---|---|---|
| VDD | → | 3.3V | Pin 1 |
| GND | → | GND | Pin 6 |
| SCK | → | GPIO18 (BCLK) | Pin 12 |
| WS | → | GPIO19 (LRCLK) | Pin 35 |
| SD | → | GPIO20 (DIN) | Pin 38 |
| L/R | → | GND | Pin 6（左チャンネル選択） |

#### MAX98357A（アンプ）→ Pi Zero 2 W

| MAX98357A | → | Pi Zero 2 W | ピン番号 |
|---|---|---|---|
| VIN | → | 5V | Pin 2 |
| GND | → | GND | Pin 9 |
| BCLK | → | GPIO18 | Pin 12 ※マイクと共有 |
| LRC | → | GPIO19 | Pin 35 ※マイクと共有 |
| DIN | → | GPIO21 | Pin 40 |
| GAIN | → | GND | Pin 9（12dBゲイン） |
| SD | → | 未接続 | （常時ON） |

#### スピーカー → MAX98357A

スピーカーの＋/ーをMAX98357Aの＋/ー端子に接続。

#### 共有ピンについて

- **Pin 12（GPIO18）** と **Pin 35（GPIO19）** はマイクとアンプの両方を同じピンに接続する（I2Sバス共有）

#### MAX98357A の GAIN / SD ピンについて

| ピン | 接続先 | 動作 |
|---|---|---|
| GAIN 未接続 | — | 9dB（デフォルト） |
| **GAIN → GND** | **GND** | **12dB（推奨）** |
| GAIN → VIN | VIN | 15dB |
| SD 未接続 | — | 常時ON（デフォルト） |
| SD → GND | GND | シャットダウン（ミュート） |

---

## ソフトウェア設定詳細

### main.py の調整パラメータ

| パラメータ | 現在値 | 説明 |
|---|---|---|
| `MODEL` | `gemini-2.5-flash-native-audio-latest` | Gemini Live APIモデル |
| `MIC_GAIN` | `26.0` | マイク増幅倍率（INMP441は出力が小さいため必要） |
| `SPEAKER_VOL` | `0.4` | スピーカー音量（0.0〜1.0、大きいとビビる） |
| `MIC_RATE` | `16000` | マイクサンプルレート |
| `SPK_RATE` | `24000` | スピーカーサンプルレート（Gemini出力に合わせる） |

### エコー防止機能

スピーカーから出た音をマイクが拾ってしまう問題（フィードバックループ）への対策：
- Geminiが音声を返している間はマイクをミュート（無音データを送信）
- `turn_complete` または `interrupted` を受信したらマイク復帰

### 会話ログ

- `/home/pi/doll-ai/logs/chat_YYYYMMDD_HHMMSS.txt` に自動保存
- Geminiの `input_transcription`（ユーザー発言）と `output_transcription`（AI発言）を記録
- 確認: `cat /home/pi/doll-ai/logs/chat_*.txt`

---

## 手動セットアップ手順（setup.sh が行う内容）

### 1. /boot/firmware/config.txt の編集

```bash
sudo nano /boot/firmware/config.txt
```

以下を設定する（`[cm4]` `[cm5]` などのセクションヘッダの **前** に記述）：

```ini
# I2S有効化（コメントアウトを外す）
dtparam=i2s=on

# I2Sマイク＋アンプ共用オーバーレイ
dtoverlay=googlevoicehat-soundcard
```

> **注意:** `#dtparam=i2s=on` のように `#` がついていると無効。`#` を外すこと。

設定後に再起動：
```bash
sudo reboot
```

### 2. デバイス認識の確認

```bash
arecord -l   # マイク（card 0 が表示されればOK）
aplay -l     # スピーカー（card 0 が表示されればOK）
```

期待される出力：
```
card 0: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar], device 0: ...
```

### 3. /etc/asound.conf の作成

```bash
sudo nano /etc/asound.conf
```

以下の内容を記述（softvolでソフトウェア音量制御を追加）：

```
pcm.doll_mic_raw {
    type plug
    slave {
        pcm "hw:0,0"
    }
}

pcm.doll_mic {
    type softvol
    slave.pcm "doll_mic_raw"
    control {
        name "Mic Boost"
        card 0
    }
    min_dB -5.0
    max_dB 50.0
}

pcm.doll_spk_raw {
    type plug
    slave {
        pcm "hw:0,0"
    }
}

pcm.doll_spk {
    type softvol
    slave.pcm "doll_spk_raw"
    control {
        name "Speaker Boost"
        card 0
    }
    min_dB -5.0
    max_dB 30.0
}

pcm.!default {
    type asym
    playback.pcm "doll_spk"
    capture.pcm  "doll_mic"
}

ctl.!default {
    type hw
    card 0
}
```

### 4. 音声テスト

```bash
# ビープ音テスト
speaker-test -D plughw:0,0 -t sine -f 440 -l 1

# 録音（3秒）
arecord -D plughw:0,0 -f S32_LE -r 16000 -c 1 -d 3 /tmp/test.wav

# 再生
aplay -D plughw:0,0 /tmp/test.wav
```

### 5. 音量調整

```bash
alsamixer
```

- **Mic Boost**: マイク入力の増幅（上げすぎるとノイズ注意）
- **Speaker Boost**: スピーカー出力の増幅

> `googlevoicehat-soundcard` ドライバ自体にはハードウェア音量コントロールがないため、
> `softvol` によるソフトウェア制御で音量調整を行う。

---

## サービス操作

```bash
# 自動起動を有効にする
sudo systemctl enable doll-ai

# 自動起動を無効にする
sudo systemctl disable doll-ai

# 手動で起動/停止
sudo systemctl start  doll-ai
sudo systemctl stop   doll-ai
sudo systemctl status doll-ai

# ログ確認
journalctl -u doll-ai -f
```

---

## トラブルシューティング

### マイクが認識しない（arecord -l に何も出ない）

1. `/boot/firmware/config.txt` を確認:
   - `dtparam=i2s=on` が有効か（`#` がついていないか）
   - `dtoverlay=googlevoicehat-soundcard` があるか
   - セクションヘッダ `[cm4]` `[cm5]` の **前** に書いてあるか
2. 配線を確認（特に SD → GPIO20）
3. 再起動したか

```bash
cat /boot/firmware/config.txt | grep -E "i2s|google"
lsmod | grep snd
```

### 音が出ない

1. `/etc/asound.conf` のカード番号が `aplay -l` と一致しているか
2. MAX98357Aの GAIN → GND に接続して音量を上げる
3. `alsamixer` で Speaker Boost を上げる
4. スピーカーケーブルの接触不良を確認

### スピーカーがビビる（歪む）

- `main.py` の `SPEAKER_VOL` を下げる（0.4 → 0.3 など）
- GAIN ピンを GND から外す（9dBに戻す）

### 会話が噛み合わない

- エコー防止が効いているか確認（ログに `[STATE] mic MUTED` / `mic ON` が出ているか）
- `MIC_GAIN` を調整（しゃべったとき peak 3000〜15000 が理想）
- 会話ログを確認: `cat /home/pi/doll-ai/logs/chat_*.txt`

### alsamixer が "No such file or directory"

`/etc/asound.conf` の `ctl.!default` セクションのカード番号を確認。

### alsamixer が "This sound device does not have any controls"

`softvol` 設定を追加していない場合に表示される。
`/etc/asound.conf` に softvol の設定を追加すること（上記参照）。

### Ctrl+C で止まらない

別ターミナルから `ssh` して `pkill -f main.py`

### Gemini APIエラー (model not found)

使用可能なモデルを確認:
```bash
source /home/pi/doll-ai/venv/bin/activate
python3 -c "
from google import genai
import os
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
for m in client.models.list():
    actions = getattr(m, 'supported_actions', []) or []
    if any('bidi' in str(a).lower() for a in actions):
        print(m.name, actions)
"
```
