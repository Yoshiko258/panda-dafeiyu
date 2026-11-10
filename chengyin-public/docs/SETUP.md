# 部署说明

## 1. 先有能用的 AstrBot

按官方文档装好 AstrBot 和 NapCat，QQ 小号扫码登录，
在 QQ 里给她发条消息能收到回复，再往下做。

需要的第三方插件（从 AstrBot 插件市场装）：

```
astrbot_plugin_private_companion   陪伴主插件
astrbot_plugin_livingmemory        长期记忆
astrbot_plugin_group_chat_plus     群聊插话
astrbot_plugin_proactive_chat      主动消息
astrbot_plugin_bili_scroll         B站观察
meme_manager                       表情包
```

## 2. 放人格

打开 AstrBot 后台 → 人格 → 新建，把 `persona/chengyin.md` 的内容
粘进「系统提示词」。称呼按你习惯改（默认叫「主人」）。

## 3. 装两个自写插件

把 `plugins/` 下的两个目录整个复制到：

```
<AstrBot>/data/plugins/
```

然后在后台插件页启用。

## 4. 填配置

`config/` 里是脱敏样例（`<SECRET>` 之类都是占位符），
对照着在 AstrBot 后台填自己的：

| 样例 | 对应插件 |
|---|---|
| `cmd_config.example.json` | AstrBot 本体（模型、平台、后台账号） |
| `astrbot_plugin_private_companion.example.json` | 陪伴主插件 |
| `astrbot_plugin_group_chat_plus.example.json` | 群聊 |
| `astrbot_plugin_proactive_chat.example.json` | 主动消息 |
| `astrbot_plugin_bili_scroll.example.json` | B站 |
| `astrbot_plugin_chengyin_poke_guard.example.json` | 戳一戳 |

## 5. 工具（可选）

把 `tools/` 复制到你自己的项目根目录，改掉里面写死的路径
（`D:\chengyin`），再跑：

```bat
python tools\verify_all.py
```

## 6. 开机自启（Windows）

- 桌面放个快捷方式指向 `tools\启动守护.vbs`，拖进启动文件夹
- 或者建个计划任务，每 10 分钟跑一次 `tools\supervisor.py --once`

## 7. 面板（可选）

```bat
python tools\panel\server.py     :: 起服务，浏览器开 http://127.0.0.1:8899
```
