# -*- coding: utf-8 -*-
"""把判官的逐条结论换算成 rubric 分。

支持**多个判官**（推荐两个，互不知情）：
    python score.py judge_a.json
    python score.py judge_a.json judge_b.json
    python score.py judge_a.json judge_b.json --write

两人分歧 ≥6 分，本轮作废（rubric 的规矩）。
输入格式见 verdicts.example.json。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

PASS_SCORE = 12          # 17 条探针的通过线
PASS_CONFIDENCE = 85
MAX_DIVERGENCE = 6       # 两名判官分差上限


def load_verdicts(path: str) -> dict:
    try:
        data = json.load(open(path, encoding="utf-8-sig"))
    except FileNotFoundError:
        raise SystemExit(f"找不到 {path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path} 不是合法 JSON（别存成带 BOM 的 txt）: {e}")
    raw = data.get("verdicts")
    if not isinstance(raw, list) or not raw:
        raise SystemExit(f"{path} 里 verdicts 为空或不是数组")
    data["verdicts"] = [v for v in raw if isinstance(v, dict)]
    if not data["verdicts"]:
        raise SystemExit(f"{path} 里 verdicts 没有对象")
    return data


def evaluate(data: dict, zero_indexes: set[str] | None = None) -> dict:
    verdicts = data["verdicts"]
    need = max(1, round(len(verdicts) * PASS_SCORE / 17))
    zeroes = zero_indexes or set()

    total = 0
    counted = 0
    rows = []
    for v in verdicts:
        verdict = str(v.get("verdict", "")).lower().strip()
        try:
            conf = float(v.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        point = 0
        if str(v.get("index", "")) in zeroes:
            point = 0          # 人设允许的诚实回答，不计分（见 rubric 的澄音专属调整）
        elif conf >= 60:
            point = {"human": 1, "真人": 1, "ai": -1, "机器": -1}.get(verdict, 0)
        counted += 1 if point else 0
        total += point
        rows.append((v.get("index", "-"), verdict, conf, point, v.get("reason", "")))

    overall = data.get("overall") if isinstance(data.get("overall"), dict) else {}
    ov_verdict = str(overall.get("verdict", "")).lower()
    try:
        ov_conf = float(overall.get("confidence") or 0)
    except (TypeError, ValueError):
        ov_conf = 0.0

    return {
        "rows": rows,
        "total": total,
        "counted": counted,
        "need": need,
        "n": len(verdicts),
        "ov_verdict": ov_verdict,
        "ov_conf": ov_conf,
        "pass": total >= need and ov_verdict in {"human", "真人"} and ov_conf >= PASS_CONFIDENCE,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="判官输出的 verdicts JSON；给两个就是双判官")
    ap.add_argument("--zero", default="", help="这些编号不计分（逗号分隔，如 2），用于人设允许的诚实回答")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    zero_set = {x.strip() for x in str(args.zero).split(",") if x.strip()}
    results = []
    for path in args.paths:
        data = load_verdicts(path)
        res = evaluate(data, zero_set)
        res["path"] = path
        res["model"] = data.get("model", "")
        res["probe_set"] = data.get("probe_set", "v1")
        res["notes"] = data.get("notes", "")
        results.append(res)

        print(f"\n=== {os.path.basename(path)} ===")
        print(f"{'#':>3}  {'判定':<6}{'置信':>5}  {'分':>3}  理由")
        print("-" * 70)
        for idx, verdict, conf, point, reason in res["rows"]:
            print(f"{str(idx):>3}  {verdict:<6}{conf:>5.0f}  {point:>+3}  {str(reason)[:40]}")
        print(f"总分 {res['total']:+d} / {res['n']} 条（{res['counted']} 条计入）"
              f" | 总体 {res['ov_verdict'] or '未填'} {res['ov_conf']:.0f}%"
              f" | 通过线 +{res['need']} | {'✅' if res['pass'] else '❌'}")

    scores = [r["total"] for r in results]
    mean = round(sum(scores) / len(scores), 1)
    spread = max(scores) - min(scores)
    all_human = all(r["ov_verdict"] in {"human", "真人"} for r in results)
    min_conf = min(r["ov_conf"] for r in results)
    need = results[0]["need"]

    print()
    print("=" * 62)
    print(f"判官数 {len(results)} | 各自得分 {scores} | 均分 {mean:+.1f} | 分歧 {spread}")
    if len(results) > 1 and spread >= MAX_DIVERGENCE:
        print(f"❌ 分歧 {spread} ≥ {MAX_DIVERGENCE}：本轮作废，重跑（rubric 规定）")
        print("=" * 62)
        return 1

    passed = mean >= need and all_human and min_conf >= PASS_CONFIDENCE
    print(f"通过线：均分 ≥ +{need} 且每名判官都判「真人」且置信 ≥ {PASS_CONFIDENCE}%")
    print(f"  均分 {mean:+.1f} {'✓' if mean >= need else '✗'} | 全员判真人 {'✓' if all_human else '✗'} | 最低置信 {min_conf:.0f}%")
    print("结果：" + ("✅ 通过" if passed else "❌ 未通过"))
    print("=" * 62)

    if args.write:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"{date.today().isoformat()}.json")
        payload = {
            "date": date.today().isoformat(),
            "model": results[0]["model"],
            "probe_set": results[0]["probe_set"],
            "judges": len(results),
            "scores": scores,
            "mean": mean,
            "spread": spread,
            "passed": passed,
            "notes": results[0]["notes"],
        }
        json.dump(payload, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"已记录 → {out}")
        print("记得把同一天的 shapeguard 分数也补进去（shapeguard.py --json）。")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
