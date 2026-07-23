# PourNotify

PourNotify 是面向 Codex 的轻量、本地优先 Windows 与 macOS 通知中心。它支持桌面原生通知、
Bark iPhone 推送、分类声音、免打扰时段、通知历史和防刷屏控制。应用不包含遥测、云端后端，
不会读取浏览器 Cookie，也不会保存对话。

## 运行

需要 Python 3.11 或更高版本：

```powershell
python -m pip install -e ".[dev]"
python -m pournotify
```

Codex 可通过 `python -m pournotify --notify <Codex JSON>` 调用同一条正式通知管线。
每个通知分类都能独立设置启用状态、Bark、桌面通知、声音、历史、音效、音量与优先级。
“通知测试”页面与真实事件使用完全相同的分发器。

历史页面使用有长度限制的纯文本预览，同时保留完整原文。每条记录显示优先级和重复次数，
支持查看完整详情、一键复制、全文搜索，以及无损 JSON 或 CSV 导出。
