#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AutoDL 租机控制 + 花费记账。

两套凭据（都放 auth/ 下，.gitignore 已覆盖）：
  - auth/autodl.md        开发者 Token（develop_api，aud=develop_api）
      可用：balance 查余额（assets 单位：厘=1/1000 元，实测校对过）
  - auth/autodl_web_token.txt  控制台 web Token（www.autodl.com 登录后取得）
      可用：list / off / cost（普通容器实例走 www.autodl.com 控制台接口）

web Token 获取方法（一次性，过期重取）：
  1. 浏览器登录 www.autodl.com
  2. F12 → Console 执行：copy(JSON.parse(localStorage.getItem('token')||'""'))
     （或 Network 面板任意 /api/v1/ 请求 → 请求头 Authorization 的值）
  3. 粘贴进 auth/autodl_web_token.txt（纯文本，一行）

用法：
  python3 tools/autodl_ctl.py balance           # 查余额
  python3 tools/autodl_ctl.py list              # 列实例（开工前必跑）
  python3 tools/autodl_ctl.py off <实例uuid> [--job <job目录名>]   # 关机并记账
  python3 tools/autodl_ctl.py cost [--last N]   # 花费汇总

记账文件：logs/rental-costs.jsonl（每行一条 JSON）
注意：关机只停 GPU 计费，系统盘仍按天扣费；释放实例会删数据，必须用户确认。
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_DEV = ROOT / "auth" / "autodl.md"
TOKEN_WEB = ROOT / "auth" / "autodl_web_token.txt"
COST_LOG = ROOT / "logs" / "rental-costs.jsonl"


def _read_token(path: Path) -> str:
    if not path.exists():
        sys.exit(f"缺少凭据文件：{path}\n见文件头注释获取方法。")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and " " not in line and len(line) > 30:
            return line
    sys.exit(f"凭据文件格式不对：{path}")


def _api(url: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": token, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def cmd_balance(_args):
    """develop_api：查余额（assets 单位：分）"""
    d = _api("https://api.autodl.com/api/v1/dev/wallet/balance", _read_token(TOKEN_DEV), {})
    if d.get("code") != "Success":
        sys.exit(f"查询失败：{d.get('msg')} ({d.get('code')})")
    a = d["data"]
    # 实测：assets 单位是厘（1/1000 元）。36780 = ¥36.78，与控制台显示一致
    print(f"余额：¥{a['assets']/1000:.2f}  （累计充值 ¥{a['total_recharge_asset']/1000:.2f}）")
    print(f"更新时间：{a['updated_at']}")


def _instances() -> list[dict]:
    d = _api("https://www.autodl.com/api/v1/instance", _read_token(TOKEN_WEB))
    if d.get("code") != "Success":
        sys.exit(f"查询失败：{d.get('msg')} ({d.get('code')}) — web Token 可能过期，重取 auth/autodl_web_token.txt")
    return d["data"]


def cmd_list(_args):
    rows = _instances()
    if not rows:
        print("没有实例（或全部被释放）。")
        return
    # 控制台接口字段以实测为准；常见字段做了防御式取值
    def g(i, *keys, default="?"):
        for k in keys:
            v = i.get(k)
            if v not in (None, ""):
                return v
        return default
    for i in rows:
        status = g(i, "status")
        price = g(i, "amount_per_hour", "price", default=0)
        try:
            price = f"¥{float(price):.2f}/h"
        except (TypeError, ValueError):
            price = str(price)
        uuid = g(i, "uuid")
        name = g(i, "name", "instance_name")
        gpu = g(i, "gpu_name", "gpu_label")
        started = g(i, "started_at", "create_time")
        flag = "⚠️ 运行中" if str(status).lower() in ("running", "运行中") else ""
        print(f"{uuid}  {name}  [{gpu}]  {status}  {price}  开机于 {started} {flag}")


def cmd_off(args):
    rows = _instances()
    hit = [i for i in rows if i.get("uuid") == args.instance_id]
    if not hit:
        sys.exit(f"未找到实例 {args.instance_id}，先跑 list 看 uuid。")
    i = hit[0]
    started_at = i.get("started_at") or i.get("create_time") or ""
    price = i.get("amount_per_hour") or i.get("price") or 0
    name = i.get("name") or i.get("instance_name") or ""
    # 关机动前确认
    d = _api("https://www.autodl.com/api/v1/instance/power_off",
             _read_token(TOKEN_WEB), {"instance_id": args.instance_id})
    if d.get("code") != "Success":
        sys.exit(f"关机失败：{d.get('msg')} ({d.get('code')})")
    stopped_at = datetime.now().astimezone().isoformat(timespec="seconds")
    # 估算时长/费用（started_at 格式若解析不了则留空，只记事实）
    duration_h, cost = None, None
    try:
        t0 = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(stopped_at)
        duration_h = round((t1 - t0).total_seconds() / 3600, 2)
        cost = round(duration_h * float(price), 2)
    except Exception:
        pass
    rec = {
        "stopped_at": stopped_at,
        "uuid": args.instance_id,
        "name": name,
        "started_at": started_at,
        "duration_h": duration_h,
        "price_per_h": float(price) if price else None,
        "cost_yuan_est": cost,
        "job": args.job or "",
    }
    COST_LOG.parent.mkdir(exist_ok=True)
    with COST_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    est = f"，估算 {duration_h}h × ¥{price}/h ≈ ¥{cost}" if cost is not None else ""
    print(f"已关机：{name} ({args.instance_id}){est}")
    print(f"已记账 → {COST_LOG}")


def cmd_cost(args):
    if not COST_LOG.exists():
        print("还没有记账记录。")
        return
    recs = [json.loads(l) for l in COST_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.last:
        recs = recs[-args.last:]
    total = sum(r["cost_yuan_est"] or 0 for r in recs)
    for r in recs:
        print(f"{r['stopped_at'][:16]}  {r.get('name','')}  ¥{r.get('cost_yuan_est')}  job={r.get('job','')}")
    print(f"— 共 {len(recs)} 笔，合计 ¥{total:.2f}（仅含本工具记账部分；控制台上的开机时段未记账）")


def main():
    p = argparse.ArgumentParser(description="AutoDL 租机控制与记账")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("balance").set_defaults(fn=cmd_balance)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    po = sub.add_parser("off")
    po.add_argument("instance_id")
    po.add_argument("--job", default="", help="关联的 job 目录名")
    po.set_defaults(fn=cmd_off)
    pc = sub.add_parser("cost")
    pc.add_argument("--last", type=int, default=0)
    pc.set_defaults(fn=cmd_cost)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
