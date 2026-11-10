# 澄音 · 本地陪伴机器人

一个跑在自己电脑上的 QQ 陪伴机器人：接 AstrBot + NapCat，
有自己的性格、生活日程和记忆，会发表情包、发语音、主动找你说话。

这个仓库是「配置与工具」部分：人格、监控脚本、自写插件、脱敏后的配置样例。
AstrBot 本体、NapCat、各种第三方插件都不在这里。

## 里面有什么

| 目录 | 内容 |
|---|---|
| `persona/` | 人格设定（脱敏版） |
| `plugins/` | 自己写的两个 AstrBot 插件 |
| `tools/` | 自检、审计、看门狗、面板、余额监控 |
| `tools/growth/` | 每日成长、帮忙规划、每周归档 |
| `tools/panel/` | 本地网页面板（8899） |
| `config/` | 脱敏后的配置样例，照着填自己的 |
| `docs/` | 部署说明与补丁清单 |

## 两个自己写的插件

| 插件 | 作用 |
|---|---|
| `astrbot_plugin_chengyin_poke_guard` | 戳一戳忍耐度：反戳、越戳越烦、连续戳关小黑屋 2 小时 |
| `astrbot_plugin_memory_companion` | 记忆桥：把日程日记归档进 livingmemory 长期记忆 |

## 自检体系

改完配置最怕「一更新全没了」。这里用三层检查兜住：

```
tools/patchcheck.py   37 条：文件补丁 + 关键配置值
tools/verify_all.py   89 项：进程/端口/插件/JSON/人格/面板/补丁/磁盘/错误窗口
tools/audit_all.py    深度审计：日志告警、数据膨胀、残留文件、计划任务、配置漂移
```

跑法：

```bat
runtime\python\python.exe tools\verify_all.py
runtime\python\python.exe tools\audit_all.py
```

## 后台守护

```bat
:: 常驻（开机自启）
runtime\python\pythonw.exe tools\supervisor.py
:: 单轮检查（计划任务每 10 分钟）
runtime\python\pythonw.exe tools\supervisor.py --once
```

它负责：成长/帮忙/归档按时跑、面板挂了拉起来、DeepSeek 余额涨了算作「改善伙食」。

## 开始用

看 [`docs/SETUP.md`](docs/SETUP.md)。

## 许可

MIT，见 `LICENSE`。人格文本是我自己写的，随便改。
