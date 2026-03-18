# Dota2 Invoker Voice Control

## 概述
用语音控制 Dota2 中 Invoker(祈求者) 的技能释放。说出技能中文名 → 自动按出元素组合 → 切技能 → 释放到当前鼠标位置。

## 技术栈
- **ASR**: SenseVoice STT (http://localhost:8771) - 中文识别强
- **意图匹配**: 关键词/模糊匹配(中文技能名)
- **输入模拟**: pynput (macOS兼容性好)
- **语言**: Python 3.12

## 改键映射
Karl 的 Dota2 改键: QWER → ZXCV
- Z = Quas(冰), X = Wex(电), C = Exort(火), V = Invoke(切技能), D = 释放技能

## 技能映射表
| 技能中文名 | 元素组合 | 按键序列(含切+放) |
|-----------|---------|-------------------|
| 天火 (Sun Strike) | 火火火 | C C C → V → D |
| 陨石 (Chaos Meteor) | 火火电 | C C X → V → D |
| 吹风 (Tornado) | 冰电电 | Z X X → V → D |
| 磁暴 (EMP) | 电电电 | X X X → V → D |
| 隐身 (Ghost Walk) | 冰冰电 | Z Z X → V → D |
| 冰墙 (Ice Wall) | 冰冰火 | Z Z C → V → D |
| 推波 (Deafening Blast) | 冰电火 | Z X C → V → D |
| 火人 (Forge Spirit) | 冰火火 | Z C C → V → D |

## 按键时序
- 元素键之间间隔: 30-50ms (模拟人手速度，太快游戏可能不响应)
- 元素键 → V(切): 50ms
- V → D(释放): 80-100ms (等服务器确认切好)
- D 释放到**当前鼠标位置**，不需要移动鼠标

## 实现要求
1. **实时麦克风监听**: 持续录音，VAD 检测说话段
2. **流式/分段识别**: 检测到说话结束后立即送 SenseVoice 识别
3. **模糊匹配**: 识别结果可能不完美，用编辑距离/模糊匹配容错
   - "天火" 也可能识别成 "添火"、"天活" 等
4. **按键模拟**: 用 pynput 模拟键盘按键，发送到当前焦点窗口(Dota2)
5. **状态反馈**: 终端显示识别结果和执行的操作
6. **安全**: 只在检测到高置信度匹配时执行，防误触

## 运行方式
```bash
cd ~/Documents/vibe_coding/dota2_voice
python3 main.py
# 启动后持续监听麦克风，说技能名即触发
# Ctrl+C 退出
```

## 依赖
- pynput (键盘模拟)
- pyaudio / sounddevice (麦克风采集)
- requests (调 SenseVoice API)
- numpy (音频处理)
- rapidfuzz (模糊匹配，可选)

## SenseVoice API 格式
```bash
# 需要确认 :8771 的具体 API 格式
# 大概率是 POST multipart/form-data 上传 wav/pcm
curl -X POST http://localhost:8771/asr -F "audio=@test.wav"
```

## 注意事项
- macOS 需要在 系统设置 > 隐私与安全 > 辅助功能 中授权 Terminal/iTerm pynput 权限
- Dota2 需要是当前焦点窗口
- 首次运行会请求麦克风权限
