# tools 索引

> 这里的东西都是**只读或可回滚**的辅助工具，不参与聊天主链路。
> 所有会改人格的脚本都是「备份 → 改 → 回读校验 → 失败自动回滚」。

## 面板（本地看板）

**桌面上有个「澄音面板」快捷方式**，双击就行——它会先看 8899 端口在不在跑，
没跑就后台起服务，然后开浏览器。

手动起：

```powershell
& D:\chengyin\runtime\python\python.exe D:\chengyin\tools\panel\server.py
# → http://127.0.0.1:8899
```

快捷方式指向 `tools\panel\open-panel.vbs`，图标是 `tools\panel\panel.ico`（自己画的：深色底 + 青色小鱼 + 暗纹「澄」）。

只读看板，不写人格、不改配置、不给她发消息。上面能看到：

- 人格字数、成长条目、想要的、技能、对话原文、B站看过 —— 六个计数
- 人格结构 5 个分节的检查结果 + 称呼残留
- 她长出了什么 / 她想要什么（直接读人格第十、十一节）
- 她的技能（带等级）和个人目标
- 她能查到什么（B站/记忆/日记/梦/复盘/关系/技能/屏幕，带实时条数）
- **聊天里能用的指令**：扫 `data\plugins` 自动收集 83 条，**连别名一起收**（如「澄音画图」也叫「鱼鱼画图」，共 17 条带别名），搜索能搜别名
- **她的触发词**：点名就叫谁、老板直呼、弱相关词、要语音、图片唤醒开关
- **她最近说了什么**：最近 12 条对话（媒体占位符显示成 [媒体]）
- **她能调用的工具**：34 个 LLM 工具，可搜索
- 巡检脚本（一键复制）+ 定时任务的下次运行时间
- 「跑一次体检」按钮：直接调 `healthcheck.py`，把 17 项结果打出来

加新插件后重启面板，指令和工具列表会自动跟上。

## 两个工具箱

### `persona-kit` —— 观察与评测

| 文件 | 干什么 |
|---|---|
| `shapeguard.py` | 回复形状体检：湍流率、句长方差、形状克隆、语气词垄断、句首黑名单 |
| `collect.py` | 把真实对话导成盲判包（默认读 livingmemory 的 conversations.db） |
| `score.py` | 判官结论 → rubric 分，支持双判官、分歧 ≥6 作废 |
| `probes.md` / `rubric.md` | 17 条固定探针 + 评分标准 |
| `handoff.py` | 交接包：情绪余温 / 欠着的话 / 掉线头 |
| `restore_persona.py` | 从备份还原人格 |
| `rename_owner.py` | 批量改称呼（主人 → 主人），已跑过，留作模板 |
| `anchors/` | 生活锚点定稿、worldbook 种子文件 |

### `growth` —— 让她自己长

| 文件 | 干什么 | 定时 |
|---|---|---|
| `growth.py` | 每天判断有没有真的成长，写人格第十节 | 05:10 |
| `wants.py` | 搜 B 站看别人家有什么 + 判断她想要什么新能力，写第十一节 | 06:10 |
| `archive.py` | 人生存档（5 个文件 + SHA-256，保留 14 份），自动镜像到 E 盘 | 周日 05:30 |
| `healthcheck.py` | 一条命令体检：结构 / 称呼 / 同步 / 开关 / 档案 | 手动 |
| `help.py` | 旧版「卡住的事」，已被 wants.py 取代，留作参考 | — |

## 常用命令

```powershell
$py = "D:\chengyin\runtime\python\python.exe"

# 体检（最常跑）
& $py D:\chengyin\tools\growth\healthcheck.py

# 看现状
& $py D:\chengyin\tools\growth\growth.py --status
& $py D:\chengyin\tools\growth\wants.py  --status

# 预演（不写人设）
& $py D:\chengyin\tools\growth\growth.py
& $py D:\chengyin\tools\growth\wants.py

# 真写
& $py D:\chengyin\tools\growth\growth.py --apply
& $py D:\chengyin\tools\growth\wants.py  --apply

# 回滚
& $py D:\chengyin\tools\growth\growth.py --rollback      # 只退第十节
& $py D:\chengyin\tools\persona-kit\restore_persona.py --list

# 形状体检（带日志样本）
& $py D:\chengyin\tools\persona-kit\shapeguard.py --logs --last 40
```

## 定时任务

| 任务名 | 时间 | 脚本 | 日志 |
|---|---|---|---|
| `ChengYin-Growth` | 每天 05:10 | `growth.py --apply --hours 48` | `logs\growth.log` |
| `ChengYin-Help` | 每天 06:10 | `wants.py --apply` | `logs\wants.log` |
| `ChengYin-Archive` | 周日 05:30 | `archive.py` | `logs\archive.log` |

查/删：`schtasks /Query /TN "ChengYin-Growth" /FO LIST`、
`schtasks /Delete /TN "ChengYin-Growth" /F`

## 备份在哪

| 目录 | 内容 | 说明 |
|---|---|---|
| `persona-kit\backup\` | 人格快照（根目录）+ `config\` 配置 + `data\` 技能表/companions | 改之前的原样 |
| `growth\backups\` | 每次写入前的快照（`snapshot_` / `persona_before_help_` / `persona_before_wants_`） | 保留最近 5 份/类 |
| `D:\chengyin\archives\` | 人生存档 ZIP | 保留最近 14 份 |
| `D:\chengyin\archives\` | **异地镜像**（E: 在磁盘 0，I: 在磁盘 3） | 每次打包后自动复制并校验 SHA |

## 三条通用坑（都踩过）

1. **配置在内存里**：直接改配置文件不生效，要走后台 API（`PUT /api/v1/plugins/config`）
2. **登录有 429 限流**（1 次/秒）：脚本都做了令牌缓存，别自己再裸调 login
3. **时间戳不能用数据库的**：一问一答在库里是同一个时间，测延迟要从 `logs\astrbot.log` 算
