# 对第三方插件做过的改动

这些改动都在 `tools/patchcheck.py` 里有断言，插件更新后能查出来丢了哪条。

| 名称 | 文件 | 说明 |
|---|---|---|
| B站 直读时长阈值 | `astrbot_plugin_bili_scroll\core\video.py` | ≤5 分钟直读视频、超过抽帧；记忆里带上来源 |
| B站 分享视频看完回评价 | `astrbot_plugin_bili_scroll\core\share.py` | 不再发固定模板卡片；每天最多解析 10 次 |
| B站 视觉调用记账 | `astrbot_plugin_bili_scroll\core\vision.py` | MiniMax 等视觉调用写进 usage_log，日预算才算得准 |
| B站 配置 schema 两个键 | `astrbot_plugin_bili_scroll\_conf_schema.json` | 两个关键阈值能真正写进配置，不再只靠代码默认值 |
| 陪伴 TTS 文字就好 | `astrbot_plugin_private_companion\tts_enhancement.py` | 说「用文字/别发语音」时这一轮不念 |
| 陪伴 GIF 抽帧复用 | `astrbot_plugin_private_companion\private_image.py` | 同一张动图不再抽两遍帧 |
| 陪伴 图片链清残留标签 | `astrbot_plugin_private_companion\private_image.py` | 图片回合的 &&标签&& 不会漏成正文 |
| 陪伴 入站图片 7 天清理 | `astrbot_plugin_private_companion\private_image.py` | 私聊图片目录不会无限增长 |
| 余额上涨记伙食 | `tools\balance_watch.py` | DeepSeek 余额涨了就算主人改善伙食，推「等熊猫改善伙食」 |
| 主动消息 群聊通配 | `astrbot_plugin_proactive_chat\core\services\config_service.py` | session_list 写 * 就能覆盖所有群，不用每加一个群手改 |
| 主动消息 通配展开 | `astrbot_plugin_proactive_chat\core\services\scheduler_service.py` | 启动时把 * 展开成已知群会话，否则 * 会被当成无效会话 |
| 记忆桥插件 | `astrbot_plugin_memory_companion\main.py` | 陪伴插件的 Bot Personal 归档接到 livingmemory，原来只能堆在出站队列 |
| 记忆桥能力探测 | `astrbot_plugin_memory_companion\main.py` | 契约常量对齐，否则陪伴插件判定 capability_probe_missing 不投递 |
| 陪伴 schema 记忆桥开关 | `astrbot_plugin_private_companion\_conf_schema.json` | 开关不在 schema 会被 AstrBot 裁掉，桥默认关闭 |
| 记忆出站队列有界 | `astrbot_plugin_private_companion\memory_companion_adapter.py` | 记忆桥不可用时不让 bot_personal_outbox 无限增长 |
| 个人目标 中文单字关键词 | `astrbot_plugin_private_companion\daily_state.py` | 允许「吃」「饭」「躺」这类单字关键词，否则目标永远不动 |
| 陪伴 戳一戳发送 | `astrbot_plugin_private_companion\proactive_message.py` | aiocqhttp 客户端没有 group_poke，改走标准 send_poke |
| 表情包 提示词注入优先级 | `meme_manager\main.py` | 排在人格重写之后，否则表情提示词会被整段覆盖 |
| 戳一戳忍耐度 插件 | `astrbot_plugin_chengyin_poke_guard\main.py` | 反戳 + 越戳越烦 + 小黑屋 2 小时（自写插件） |
| 戳一戳忍耐度 配置 schema | `astrbot_plugin_chengyin_poke_guard\_conf_schema.json` | 插件被重装时配置项还在 |

## 关键配置值

| 名称 | 值 | 说明 |
|---|---|---|
| B站 直读阈值 | `300`秒 | |
| B站 分享分析 | `True` | |
| B站 分享解析开关 | `True` | |
| B站 分享不发原视频 | `False` | |
| B站 每日视频额度 | `20`个 | |
| 陪伴 只发语音 | `voice_only` | |
| 主动消息 群聊开关 | `True` | |
| 主动消息 群聊会话 | `['*']`所有群 | |
| 群聊 兴趣唤醒概率 | `24`% | |
| 表情包 emotion-llm | `True` | |
| 表情包 发送概率 | `50`% | |
| 群聊 触发词 | `['澄音']` | |
| 戳一戳 反戳概率 | `0.7` | |
| 戳一戳 忍耐度-反戳概率 | `0.7` | |
| 戳一戳 忍耐度-拉黑时长 | `7200`秒 | |
| 戳一戳 回戳冷却 | `10`秒 | |
| 戳一戳 回戳后说话 | `True` | |
