# Dota2 Invoker Voice Control

## 1) 安装依赖
```bash
cd ~/Documents/vibe_coding/dota2_voice
python3 -m pip install -r requirements.txt
```

## 2) 启动 SenseVoice 服务 (需先可用)
目标接口: `http://localhost:8771/transcribe`

健康检查:
```bash
curl -s http://localhost:8771/health
```

## 3) 运行
```bash
cd ~/Documents/vibe_coding/dota2_voice
python3 main.py
```

启动后持续监听麦克风，说以下技能名可触发:
- 天火 / 陨石 / 吹风 / 磁暴 / 隐身 / 冰墙 / 推波 / 火人

## 按键映射
- 元素: Z/X/C (对应 Q/W/E)
- 切技能: V
- 释放: D

## 时序
- 元素键间隔 30-50ms
- 元素后到 V: 50ms
- V 到 D: 80-100ms

## 备注
- macOS 需要给终端辅助功能权限 (pynput)
- Dota2 必须是当前焦点窗口
- 当前版本为能量阈值 VAD + 中文模糊匹配
