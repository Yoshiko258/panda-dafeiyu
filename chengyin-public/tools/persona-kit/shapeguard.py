# -*- coding: utf-8 -*-
"""shapeguard —— 澄音回复的"形状"体检工具。

移植自 persona-engine 的 persona_self_audit 检测器，并按澄音的人设做了改写：
原版面向"面馆老板"的陌生人对峙场景，这里只保留与场景无关的**形状层**规则。

用法：
    python shapeguard.py                       # 从 companions.json 取最近回复
    python shapeguard.py --logs                # 额外解析 TTS 日志里的真实台词
    python shapeguard.py --last 40 --json out.json
    python shapeguard.py --from-file replies.txt   # 每行一条，自己喂样本

只读，不改任何东西。退出码：0 = 通过，1 = 有高危发现，2 = 采集失败。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

DEFAULT_COMPANIONS = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"
DEFAULT_LOGS = r"D:\chengyin\logs"

# ---------------------------------------------------------------- 语料采集


def from_companions(path: str) -> list[tuple[str, str]]:
    """从插件的数据文件里取机器人自己说过的话。返回 [(来源, 文本)]，按时间排序。"""
    # utf-8-sig：Windows 下用记事本/PowerShell 写过的文件常带 BOM
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    items: list[tuple[float, str, str]] = []

    for gid, g in (data.get("groups") or {}).items():
        if not isinstance(g, dict):
            continue
        for it in g.get("recent_bot_replies") or []:
            if isinstance(it, dict) and isinstance(it.get("text"), str):
                items.append((float(it.get("ts") or 0), f"group:{gid}", it["text"].strip()))

    for uid, u in (data.get("users") or {}).items():
        if not isinstance(u, dict):
            continue
        t = u.get("last_companion_message")
        if isinstance(t, dict):
            t = t.get("text")
        if isinstance(t, str) and t.strip():
            items.append((float(u.get("last_companion_message_at") or 0), f"private:{uid}", t.strip()))

    items.sort(key=lambda x: x[0])
    return [(src, txt) for _, src, txt in items if txt]


_TTS_LINE = re.compile(r"念的是[:：]\s*(.+?)\s*$")


def from_logs(log_dir: str) -> list[tuple[str, str]]:
    """从 TTS 日志里抠出真正被念出来的台词（按时间顺序）。"""
    names = sorted(
        (n for n in os.listdir(log_dir) if n.startswith("astrbot.log") and not n.endswith(".lock")),
        key=lambda n: os.path.getmtime(os.path.join(log_dir, n)),
    )
    out: list[tuple[str, str]] = []
    for name in names:
        with open(os.path.join(log_dir, name), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                m = _TTS_LINE.search(line)
                if m:
                    out.append((f"tts:{name}", m.group(1).strip()))
    return out


def from_file(path: str) -> list[tuple[str, str]]:
    with open(path, encoding="utf-8-sig") as f:
        return [("file", ln.strip()) for ln in f if ln.strip()]


NOISE_REPEAT = 5  # 同一句重复到这个次数以上，判为试音/回放噪声


def dedupe_exact(items: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, int]], list[tuple[str, int]]]:
    """处理逐字重复的整句。

    - 重复 2~4 次：留一份，计入 D3 的观察（可能是她真的在重复自己）
    - 重复 >=5 次：判为试音/回放的噪声，整条剔掉（实测「你好呀」出现过 19 次）
    """
    counts: dict[str, int] = {}
    for _, t in items:
        counts[t] = counts.get(t, 0) + 1
    seen: set[str] = set()
    kept: list[tuple[str, str]] = []
    noise: list[tuple[str, int]] = []
    for src, t in items:
        c = counts[t]
        if c >= NOISE_REPEAT:
            if not any(n[0] == t for n in noise):
                noise.append((t, c))
            continue
        if c > 1:
            if t in seen:
                continue
            seen.add(t)
        kept.append((src, t))
    dups = [(t, c) for t, c in counts.items() if 1 < c < NOISE_REPEAT]
    return kept, dups, noise


# ---------------------------------------------------------------- 检测器


@dataclass
class Finding:
    id: str
    name: str
    severity: str          # high / medium / low
    detail: str
    directive: str = ""
    samples: list[str] = field(default_factory=list)


TURBULENCE = re.compile(r"……|不对，|来着|记不清|好像|寻思|算了算了|说错|忘了|一时想不起")
WARM_END = re.compile(r"慢走|注意安全|早点|路上|别熬夜|多喝|注意身体|记得吃饭")
ADVICE = re.compile(r"应该|建议|你要|先去|记得|别忘|要不你")
PARTICLES = ("呀", "啦", "嘛", "呢", "喔", "哦")
BAD_HEAD = re.compile(r"^(唔|诶|啊|嗯|呐)[…，,、\s]")


def detect(texts: list[str], *, profile: dict) -> tuple[list[Finding], dict]:
    """跑全部形状检测器。返回 (findings, metrics)。"""
    n = len(texts)
    if n == 0:
        raise SystemExit("没有样本")
    lens = [len(t) for t in texts]
    metrics: dict = {"n": n}

    findings: list[Finding] = []

    # D1 湍流率（现场翻车/不确定的密度）
    turb = [len(TURBULENCE.findall(t)) for t in texts]
    rate = sum(turb) / n
    metrics["turbulence_rate"] = round(rate, 2)
    if n >= 3 and rate == 0:
        findings.append(Finding(
            "D1", "湍流归零", "high",
            f"{n} 条里没有一次现场翻车或不确定",
            "偶尔来一处：话说到一半改口、一时想不起、用「好像」「来着」",
        ))
    elif rate > 1.5:
        findings.append(Finding(
            "D1", "湍流过密", "medium",
            f"平均 {rate:.2f} 处/条，像在刻意撒人味",
            "接下来几条回到干净表达",
        ))

    # D2 句长分布
    avg = sum(lens) / n
    avg_dev = sum(abs(x - avg) for x in lens) / n
    metrics.update({"len_avg": round(avg, 1), "len_avg_dev": round(avg_dev, 1),
                    "len_min": min(lens), "len_max": max(lens)})
    if n >= 3 and avg_dev < 10:
        findings.append(Finding(
            "D2", "句长太整齐", "high",
            f"平均 {avg:.1f} 字，平均偏差只有 {avg_dev:.1f} 字（{min(lens)}~{max(lens)}）",
            "下两条里必须有一条 <=8 字，或一条明显更长的",
        ))

    # D3 跨条逐字复现自己（>=8 字的片段）
    dup: list[str] = []
    for i in range(n):
        phrases = [p for p in re.split(r"[。；，、？！\s～~…]+", texts[i]) if len(p) >= 8]
        for j in range(i + 1, n):
            for ph in phrases:
                if ph in texts[j] and ph not in dup:
                    dup.append(ph)
    metrics["self_repeat"] = len(dup)
    if dup:
        findings.append(Finding(
            "D3", "逐字复现自己", "medium",
            f"{len(dup)} 处 8 字以上的自我重复",
            "复述自己说过的话要换说法",
            dup[:5],
        ))

    # D4 形状克隆：相邻两条长度差 <15 字的连续段
    streak = mx = 1
    for i in range(1, n):
        if abs(lens[i] - lens[i - 1]) < 15:
            streak += 1
            mx = max(mx, streak)
        else:
            streak = 1
    metrics["shape_clone_streak"] = mx
    if n >= 3 and mx >= 4:
        findings.append(Finding(
            "D4", f"连续 {mx} 条形状克隆", "high",
            "相邻两条长度差都不到 15 字，像同一个模子刻的",
            "下一条必须破坏形状：拆条 / 超短 / 中途岔题",
        ))

    # D5 暖收尾配额
    warm = sum(1 for t in texts if WARM_END.search(t))
    metrics["warm_endings"] = warm
    if warm >= max(3, n // 5):
        findings.append(Finding(
            "D5", f"暖收尾 {warm} 次", "medium",
            "关怀出现得太规律",
            "接下来几条允许冷收：嗯 / 行 / 就这样",
        ))

    # D6 服务腔 streak
    run = worst = 0
    for t in texts:
        run = run + 1 if ADVICE.search(t) else 0
        worst = max(worst, run)
    metrics["advice_streak"] = worst
    if worst >= 4:
        findings.append(Finding(
            "D6", f"连续 {worst} 条给建议/承诺", "medium",
            "服务腔连锁",
            "下一条禁止给任何建议，允许敷衍或反问",
        ))

    # D7 语气词单极化（澄音专属：呀几乎垄断）
    have = {p: sum(1 for t in texts if p in t) for p in PARTICLES}
    metrics["particles"] = have
    dom = max(have, key=lambda k: have[k])
    dom_share = have[dom] / n
    unused = [p for p, c in have.items() if c == 0]
    if n >= 3 and dom_share >= 0.55 and unused:
        findings.append(Finding(
            "D7", f"语气词被「{dom}」垄断", "high",
            f"{have[dom]}/{n} 条带「{dom}」({dom_share:.0%})，"
            f"而 {'、'.join(unused)} 一次没用",
            "轮换使用，有的句子干脆不带语气词",
        ))

    # D8 句首黑名单（澄音人设明文禁止）
    bad = [t for t in texts if BAD_HEAD.match(t)]
    metrics["bad_head"] = len(bad)
    if bad:
        findings.append(Finding(
            "D8", "句首黑名单", "high",
            f"{len(bad)}/{n} 条以「唔…」「诶…」这类起手（人设里是绝对禁止）",
            "句首直接切入内容或情绪，不要呻吟式开场",
            bad[:4],
        ))

    # D9-D12 人设硬规则
    rules = profile.get("rules", {})
    if rules.get("no_period"):
        hit = [t for t in texts if "。" in t]
        if hit:
            findings.append(Finding("D9", "出现了句号", "low", f"{len(hit)} 条带句号", "人设要求彻不用句号", hit[:3]))
    if rules.get("no_emoji"):
        hit = [t for t in texts if re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", t)]
        if hit:
            findings.append(Finding("D10", "出现了 emoji", "low", f"{len(hit)} 条带 emoji", "人设要求严禁 emoji", hit[:3]))
    if rules.get("no_bracket_action"):
        hit = [t for t in texts if re.search(r"[（(][^）)]{0,12}[）)]", t)]
        if hit:
            findings.append(Finding("D11", "括号描写", "low", f"{len(hit)} 条带括号动作描写", "状态要融进话里", hit[:3]))
    max_chars = rules.get("max_chars")
    if max_chars:
        hit = [t for t in texts if len(t) > max_chars]
        metrics["over_max_chars"] = len(hit)
        if hit:
            findings.append(Finding(
                "D12", f"超过 {max_chars} 字", "low",
                f"{len(hit)}/{n} 条超出人设字数",
                "除正经事外压回短句",
                hit[:3],
            ))

    return findings, metrics


# ---------------------------------------------------------------- 打分与输出

WEIGHT = {"high": 15, "medium": 8, "low": 3}


def score(findings: list[Finding]) -> int:
    """粗糙的 0-100 形状分，只用于纵向比较，不是绝对标准。"""
    return max(0, 100 - sum(WEIGHT.get(f.severity, 0) for f in findings))


def render(findings: list[Finding], metrics: dict, duplicates: list[tuple[str, int]],
           show_all: bool, noise: list[tuple[str, int]] | None = None) -> None:
    print("=" * 62)
    print(f"形状体检   样本 {metrics['n']} 条   得分 {score(findings)}/100")
    print("=" * 62)
    print(f"句长 {metrics['len_min']}~{metrics['len_max']} 字，平均 {metrics['len_avg']}，"
          f"平均偏差 {metrics['len_avg_dev']} | 形状克隆最长 {metrics['shape_clone_streak']} 条")
    print(f"湍流 {metrics['turbulence_rate']} 处/条 | 自我重复 {metrics['self_repeat']} 处 | "
          f"暖收尾 {metrics['warm_endings']} | 建议连锁 {metrics['advice_streak']}")
    print("语气词: " + "  ".join(f"{k}={v}" for k, v in metrics["particles"].items()))
    if duplicates:
        print("逐字重复的整句: " + "；".join(f"「{t}」×{c}" for t, c in duplicates[:5]))
    if noise:
        print("已剔除的试音噪声（重复>=%d 次）: " % NOISE_REPEAT
              + "；".join(f"「{t}」×{c}" for t, c in noise[:5]))
    if metrics["n"] < 3:
        print("⚠ 样本不足 3 条：只跑了单条级检查（句首黑名单/标点/emoji/字数）。")
        print("  湍流、句长、形状克隆、语气词这些统计指标需要更多样本才有意义。")
    print()

    if not findings:
        if metrics["n"] < 3:
            print("单条级检查没发现问题——样本太少，这不等于通过。")
        else:
            print("六项检测全过。注意：干净本身在长会话里也可能可疑，保持不定期复检。")
        return

    for f in findings:
        print(f"[{f.severity.upper():6}] {f.id} {f.name}")
        print(f"         {f.detail}")
        if f.directive:
            print(f"         → {f.directive}")
        if f.samples and show_all:
            for s in f.samples:
                print(f"           · {s}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="澄音回复形状体检")
    ap.add_argument("--companions", default=DEFAULT_COMPANIONS)
    ap.add_argument("--logs", nargs="?", const=DEFAULT_LOGS, default=None, help="额外解析 TTS 日志")
    ap.add_argument("--from-file", default=None, help="每行一条样本")
    ap.add_argument("--last", type=int, default=40, help="只看最近 N 条（默认 40）")
    ap.add_argument("--json", default=None, help="把结果写成 JSON")
    ap.add_argument("--all", action="store_true", help="打印全部样例")
    ap.add_argument("--keep-duplicates", action="store_true", help="保留逐字重复的样本")
    args = ap.parse_args()

    if args.last is not None and args.last <= 0:
        print("--last 必须是正整数（0 在 Python 里等于「全部」，容易误伤）", file=sys.stderr)
        return 2

    items: list[tuple[str, str]] = []
    try:
        if args.from_file:
            items = from_file(args.from_file)
        else:
            if os.path.exists(args.companions):
                items += from_companions(args.companions)
            if args.logs:
                items += from_logs(args.logs)
    except FileNotFoundError as e:
        print(f"读不到文件: {e.filename}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"文件不是合法 JSON: {e}", file=sys.stderr)
        return 2

    if not items:
        print("没有采到样本。检查 --companions / --logs / --from-file 路径。", file=sys.stderr)
        return 2

    duplicates: list[tuple[str, int]] = []
    noise: list[tuple[str, int]] = []
    if args.keep_duplicates:
        kept = items
    else:
        kept, duplicates, noise = dedupe_exact(items)

    texts = [t for _, t in kept]
    if args.last:
        texts = texts[-args.last:]
    if not texts:
        print("剔掉重复句之后没有剩下样本。", file=sys.stderr)
        return 2

    profile = {"rules": {"no_period": True, "no_emoji": True, "no_bracket_action": True, "max_chars": 25}}
    findings, metrics = detect(texts, profile=profile)
    render(findings, metrics, duplicates, args.all, noise)

    if args.json:
        payload = {
            "n": metrics["n"],
            "score": score(findings),
            "metrics": metrics,
            "duplicates": duplicates,
            "noise": noise,
            "findings": [f.__dict__ for f in findings],
            "samples": texts,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"已写入 {args.json}")

    return 1 if any(f.severity == "high" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
