# 澄音自动成长 · 使用说明

> 2026-11-08 上线。设计参考 AI-Buddy R30，但按我们的栈重写（astrbot + 后台 API，不是 Electron）。

## 它每天做什么

```
读最近 24 小时的对话 + 她的日记和梦
        ↓
DeepSeek 判断："她这段时间有没有真的变化"
        ↓
没有 → 什么都不写（这是最常见的结果）
有   → 每条必须带原文证据 → 写进人格第十节「成长履历」
```

**核心纪律**（从人家文档里抄的，也是防跑偏的关键）：

- **允许"没有变化"**。模型返回空数组是正常结果，不会为了交差硬凑
- **每条必须有原文证据**，不能从人设推断、不能编
- **只写第十节**，一到九节一个字不动
- **每次写之前自动备份**，`--rollback` 可以退回去
- 换汤不换药的重说会被挡掉（相似度 ≥0.5）

## 命令

```powershell
$py = "D:\chengyin\runtime\python\python.exe"
$g  = "D:\chengyin\tools\growth\growth.py"

& $py $g                    # 预演：出候选，不写人设
& $py $g --apply            # 采纳并写入人格
& $py $g --status           # 看现在长成什么样了
& $py $g --rollback         # 退回上一次
& $py $g --dedupe           # 清历史里的重复条目（先预演，加 --apply 才写）
& $py $g --hours 168        # 看一周的材料
```

## 存档

```powershell
& $py "D:\chengyin\tools\growth\archive.py"
```

打包 `companions.json` / `conversations.db` / `plugin_config.json` / `growth.json` / `persona.json`，
附逐文件 SHA-256，打完自动回读校验。产物在 `D:\chengyin\archives\life-*.zip`（约 0.3 MB）。

**不打包** `cmd_config.json`（里面有 API key）。

## 她也知道自己卡在哪儿（help.py）

```powershell
& $py "D:\chengyin\tools\growth\help.py"            # 预演
& $py "D:\chengyin\tools\growth\help.py" --apply    # 写进人格第十一节
& $py "D:\chengyin\tools\growth\help.py" --status   # 看现在卡着什么
& $py "D:\chengyin\tools\growth\help.py" --clear --apply   # 全部视为解决
```

每天 06:10 自动跑。它读她的长期目标 + 最近 48 小时对话，判断有没有
"想做但做不动、需要人搭把手"的事，写成：

```
- 想把歪尾巴的鱼画完，卡在画笔设置还没弄明白，尾巴改不直（需要主人：帮忙把画笔设置弄好）
```

第十一节还会告诉她：卡住了别憋着，找机会主动说；说一次就够，不反复念。

**两条稳定性规则**（不然模型每次措辞不一样，人设天天变）：
- 和上次意思一样的条目，沿用旧措辞，不重写
- 这次没出现的条目，再撑一轮才删（避免模型漏报就丢事）

## 定时任务

| 任务名 | 时间 | 做什么 |
|---|---|---|
| `ChengYin-Growth` | 每天 05:10 | `growth.py --apply --hours 24` |
| `ChengYin-Help` | 每天 06:10 | `help.py --apply` |
| `ChengYin-Archive` | 每周日 05:30 | `archive.py` |

排在 04:00 的 daily_review 之后，让成长分析能吃到当天的复盘结果。

日志：`D:\chengyin\logs\growth.log`、`logs\archive.log`

查/删：

```powershell
schtasks /Query /TN "ChengYin-Growth" /FO LIST
schtasks /Delete /TN "ChengYin-Growth" /F
```

## 出问题怎么办

| 症状 | 处理 |
|---|---|
| 人格越来越长、越来越歪 | `growth.py --rollback` 退一格（**只退成长记录，不动一到九节**） |
| 第十节出现明显编造 | `--rollback`，然后把那一条从 `growth.json` 的 entries 里删掉，再 `--dedupe --apply` 重拼 |
| 彻底崩了 | 重贴原始人设（`backups\snapshot_*.json` 里最早那份，或 [生活锚点_定稿.md](../persona-kit/anchors/生活锚点_定稿.md) 前面的正文） |
| 定时任务没跑 | 确认 AstrBot 在跑（脚本要调 6185 的接口）；看 `logs\growth.log` |
| 报「连不上后台」 | AstrBot 没开，或后台在重启。脚本会以 exit 3 退出，不会留堆栈 |

## 已知边界

- **依赖 AstrBot 在运行**：脚本通过后台 API 读写人格，机器人关着就跑不了
- **消耗 DeepSeek 费用**：每天一次，读 ~3000 字材料，约几分钱
- 成长条目最多 12 条进 prompt，更早的留在 `growth.json` 里但不占 token
- 它写的是"她变了什么"，**不保证她下一轮就会表现出来**——那要看模型用不用第十节
- **24 小时窗口 + 保守判断 = 经常空手而归**。实测连跑 6 次全返回「没有值得记的变化」，
  这是设计如此（不硬凑），不是坏了。想更快看到成长可以把窗口调到 `--hours 72`
- 回滚是「退一格」，连退几次就回到更早的状态；不会一键清空

## 2026-11-08 五轮压测修掉的问题

| 问题 | 现象 | 修法 |
|---|---|---|
| 存档同名覆盖 | 同一秒跑两次，第二次覆盖第一次 | 文件名加毫秒 |
| import 关掉 stdout | `ValueError: I/O operation on closed file` | 改用 `reconfigure` |
| 登录 429 | 连跑 5 次第 5 次失败（后台限流 1 次/秒） | 令牌缓存 + 429 重试 |
| 回滚吃掉无关改动 | 会把快照之后的改称呼、改锚点一起冲掉 | 只重建第十节 |
| 回滚带回旧称呼 | 老快照里写着"给主人念语音" | 重建时统一刷术语 |
| 存档只涨不删 | 15 份 4.5MB 无上限 | `--keep`，默认留 14 份 |
| 断网抛堆栈 | 定时任务日志里全是 traceback | 友好提示 + exit 3 |
