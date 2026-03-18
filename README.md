# Dota2 Invoker Voice Control (Pure KWS)

纯关键词唤醒（KWS）方案：不走 STT/ASR，仅识别技能关键词后触发按键。

## 功能
- 纯 KWS 实时识别（sherpa-onnx）
- 关键词 → Invoker 连招（改键 QWER → ZXCV）
- 350ms 同关键词去抖动
- `skills.yaml` 可配置关键词与元素组合

---

## 1) 安装依赖

```bash
cd ~/Documents/vibe_coding/dota2_voice
python3 -m pip install -r requirements.txt
```

Windows:
```powershell
py -3.10 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 2) 配置 KWS 模型

程序默认从 `./kws_model` 读取模型文件，需包含：
- `encoder*.onnx`
- `decoder*.onnx`
- `joiner*.onnx`
- `tokens.txt`

### Windows 一键下载脚本

已提供：`scripts/download_kws_model.ps1`

```powershell
cd dota2_voice
powershell -ExecutionPolicy Bypass -File .\scripts\download_kws_model.ps1 -ModelZipUrl "<你的 sherpa-onnx 中文KWS模型zip直链>"
```

下载完成后会自动解压并拷贝到 `kws_model/`。

> 也可手动放置模型，或用环境变量指定路径：
> `DOTA_KWS_MODEL_DIR=你的模型目录`

---

## 3) 运行

```bash
cd ~/Documents/vibe_coding/dota2_voice
python3 main.py
```

---

## 4) 技能关键词配置（skills.yaml）

当前默认：

- 天火 → `CCC + V + D`
- 陨石 → `CCX + V + D`
- 吹风 → `ZXX + V + D`
- 磁暴 → `XXX + V + D`
- 隐身 → `ZZX + V + D`
- 冰墙 → `ZZC + V + D`
- 推波 → `ZXC + V + D`

元素映射：
- `Z = Quas(冰)`
- `X = Wex(电)`
- `C = Exort(火)`
- `V = Invoke(切)`
- `D = Cast(释放)`

你可直接编辑 `skills.yaml` 修改关键词和组合。

---

## 5) 测试

```bash
python3 test_kws.py
```

预期：`11 passed, 0 failed`

---

## 6) 注意事项

- 需要麦克风权限
- Dota2 必须是当前焦点窗口（按键才会打到游戏）
- macOS 需要给终端辅助功能权限（pynput）
- 本项目是纯 KWS，不包含 STT fallback
