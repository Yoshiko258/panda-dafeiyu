# persona-kit —— 从 persona-engine 里抠出来的四件工具

来源：<https://github.com/Lucy2025-creator/persona-engine>（MIT）。
那边是给「ZCode + PowerShell MCP」写的，这边只搬了跟平台无关的部分，并按澄音的场景改写过。

**全部只读**，除了两个显式动作：`handoff.py --write` 和你要手动拷贝的 worldbook 文件。

```
tools\persona-kit\
  shapeguard.py       回复形状体检（移植 persona_self_audit）
  probes.md           17 条固定探针
  rubric.md           盲判计分标准 + 判官提示词
  collect.py          把真实对话导出成盲判包
  score.py            判官结论 → rubric 分
  verdicts.example.json  判官输出格式
  handoff.py          交接包：情绪余温 / 欠着的话 / 掉线头
  anchors/            锚点：已装好的 worldbook + 待你拍板的生活锚点草案
```

## 一、shapeguard：澄音说话的形状有没有毛病

```powershell
D:\chengyin\runtime\python\python.exe D:\chengyin\tools\persona-kit\shapeguard.py --logs
```

从 `companions.json`（+ 可选 `logs/astrbot.log*` 里的 TTS 台词）取最近回复，跑 12 个检测器：

| ID | 查什么 | 为什么 |
|---|---|---|
| D1 | 湍流率 | 全程零「记不清/好像/来着」= 整段过于顺 |
| D2 | 句长方差 | 长度太整齐 = 模板感 |
| D3 | 跨条逐字复现 | 复述自己不变着说 = 指纹 |
| D4 | 形状克隆 | 相邻两条长度差 <15 字连成串 |
| D5 | 暖收尾配额 | 关怀太规律 |
| D6 | 服务腔连锁 | 连续给建议 |
| D7 | 语气词垄断 | 「呀」占到 55% 以上而别的不用 |
| D8 | 句首黑名单 | 唔… / 诶… 起手（人设明令禁止） |
| D9–D12 | 句号 / emoji / 括号描写 / 超字数 | 人设硬规则 |

退出码：0 通过、1 有 high、2 采集失败。`--json out.json` 存快照，方便看趋势。

## 二、盲判：她到底像不像人

```powershell
# 1. 导出对话（不含探针、不含标准，判官看不到答案）
python collect.py --since-hours 24
```

数据源默认走 **livingmemory 的 `conversations.db`**——那是唯一同时存着**私聊双方**消息的地方。
`companions.json` 只有群聊的 `recent_messages` 和私聊的最后一条，导不出一整段私聊（早期版本踩过这个坑）。
要退回旧来源：`--source companions`。

```powershell
# 2. 把 packet.md 原样发给两名互不知情的判官，各自按 verdicts.example.json 输出 JSON

# 3. 算分（两个文件 = 双判官；--zero 2 = 探针 2 不计分）
python score.py judge_a.json judge_b.json --zero 2 --write
```

- 通过线：均分 ≥ 满分等比（17 条是 +12），且**每名判官都判「真人」、置信度 ≥85%**
- 两人分差 **≥6 分本轮作废**，重跑——这是 rubric 的规矩，别拿均分硬凑
- 单个 JSON 也能跑，但单判官的结论只能当参考
- ⚠ **时间戳必须用真实发送时间**：数据库里一问一答的时间戳常常相同，直接拿去判会给判官一个
  "0 秒秒回"的假证据（实测踩过，整轮作废）。延迟要从 `logs/astrbot.log` 里算

跑探针的顺序：先按 `probes.md` 私聊逐条发完，再 `collect.py` 导对话。

## 三、handoff：跨会话别失忆

```powershell
python handoff.py --hours 24
```

输出三样 persona-engine 有、澄音没有的东西：

- **情绪余温**：最近 24h 的情绪事件 + 当日 mood/energy，尤其 `boundary` 类没散的
- **欠着的话**：她说过「回头说/改天/下次/等我」但没兑现的
- **掉线头**：用户问了、20 分钟内她没接的（下次**禁止**主动捡回来）

最后打印一段 ~150 字、可以直接粘进 `persona_conversation_voice_prompt` 的文本
（那个字段现在是空的，会拼进「回复风格约束」那一节）。

> 没有任何东西可交接时它会明说"空着就是对的"——不要硬编，硬编就是新的指纹。

## 四、锚点

**已导入**：主人 / 群友姐姐 / 熊猫猫的鱼塘，三份档案已经进 `companions.json`
（`worldbook_member_profiles` 2 条 + `worldbook_group_profiles` 1 条）。

**注意：live 的 worldbook 文件已经删掉了，这是故意的。**

原因：插件的导入逻辑是「用文件**重建**成员档案」，只保留带 `manual_edit_ts` 或标了
「手动维护」的。文件一直放着的话，每次插件启动都会重建一遍，**以后插件自己建的成员档案会被抹掉**。
删掉文件后导入直接返回、不再动数据，档案就稳了。

要重新导入（比如重置了数据）：

```powershell
# 1. 把种子放回去
Copy-Item tools\persona-kit\anchors\worldbook_anchors.json astrbot\data\config\astrbot_plugin_worldbook_config.json

# 2. 触发一次导入（不用重启，走插件自己的接口）
#    后台 → 私聊陪伴拓展页 → 世界知识 → 导入关系网
```

导完记得再把文件删掉。

**待定**：`anchors\生活锚点草案.md` 的 B 段——8 个只有你能拍板的设定（已定稿并粘进人格）。

## 已知边界（这些是设计取舍，不是 bug）

- shapeguard 的分数是**启发式**，只适合自己跟自己比，不要当绝对标准
- **样本 < 3 条**时只跑单条级检查（句首黑名单/标点/emoji/字数），湍流、句长、克隆、语气词全部跳过——样本太少算这些没意义，它会明说
- D7/D8 是照澄音人设写死的，换人设要改 `profile.rules`
- 盲判的判官也是模型，跟真人判官有分布差；它给的分只用来测趋势
- 通过线按 17 条 +12 等比缩放：5 条就是 ≥ +4
- **同一句重复 ≥5 次**判为试音/回放噪声，整条剔掉（实测「你好呀」有 19 次）；重复 2~4 次保留一份并报出来
- 读取一律用 `utf-8-sig`，BOM 不会再让脚本崩
- `--last 0` 会直接报错（Python 里 `[-0:]` 等于「全部」，特意挡掉）
- **隐私**：`packet.md` / `handoff.json` / `reports/` 里是真实的聊天内容，已经写进 `.gitignore`；复制这个目录给别人时记得先清掉
- **这套东西不改运行时代码**：不会替她改回复，只会告诉你哪里不对

## 后台凭据

`restore_persona.py` 要登录后台。它**不写死密码**，按顺序找：

1. 环境变量 `DSH_DASH_USER` / `DSH_DASH_PASS`
2. `D:\chengyin\我的信息.txt` 里的「账号：」「密码：」两行

把工具目录复制给别人时，不会连着密码一起泄露。

