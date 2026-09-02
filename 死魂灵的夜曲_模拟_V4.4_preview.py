# -*- coding: utf-8 -*-
"""
《死魂灵的夜曲》随机基准推演 —— V4.3.1 vs V4.4 preview
行为模型对齐《模拟器_V4.3_重构版》autoOneGame 的随机口径：
- 魂灵：每名存活魂灵随机刀 1 名存活人类
- 死神：补足夜死上限剩余刀位 min(2, 2-存活魂灵数)；有已死亡人类时 70%/夜 发动夜祷转化
- 夜祷：随机刀 1 名存活人类（穿透、最高优先级）
- 莱莱可：N2 起随机刀任意存活者（可能误伤狼）
- 门先生：随机守 2 人（不含自己、不含昨夜被守者）
- 水妖①：80% 从有效死亡候选随机救 1 人；②放逐复活 70%；③被动复活 80%（均只救人类，对齐重构版基准）
- 米提亚/降临者：默认启用信息驱动投票模型（可用 `--random` 关闭）
- 投票：死亡方随机投人类，人类随机投他人；领袖 1.5 票；平票无人出局
- 平局保护：80 夜未分胜负判死亡阵营胜

V4.4 变体开关：
- n_common=5        平民 +2（13 人局）
- n1_death_only     首夜只有死亡方行动（无守护/无救护/无查验/无刺客）
- guard_subst       门先生双守目标同夜均被非穿透刀命中且均被守护抵消 → 门先生代替出局
                    （代出局进入有效死亡候选，可被水妖①救护；总死亡数仍 ≤2，不破上限）
"""
import random
from collections import Counter

DEATH_CAP = 2
ROLES_FIXED = ["莱莱可", "门先生", "米提亚", "降临者", "水妖", "死神", "魂灵", "魂灵"]


def rnd(lst):
    return random.choice(lst)


def new_game(cfg):
    roles = ROLES_FIXED + ["普通人"] * cfg["n_common"]
    random.shuffle(roles)
    ps = [{"id": i, "role": r, "base": r, "alive": True, "cause": None,
           "soul_out": False, "knife_gone": False} for i, r in enumerate(roles)]
    return {"cfg": cfg, "players": ps, "night": 0, "last_guard": set(),
            "pending": [], "convert_used": False, "convert_pick": None,
            "nixie": {"night": 1, "exile": 1, "passive": 1},
            "leader": None, "election_done": False,
            "mitia_check": None, "arrival_check": None,
            "a_count": 0, "winner": None, "st": Counter(),
            "exile_revive": False, "nixie_dead_passive": False}


def faction(p):
    return "death" if p["role"] in ("魂灵", "死神", "夜祷") else "human"


def alive_ps(G):
    return [p for p in G["players"] if p["alive"]]


def alive_death(G):
    return [p for p in alive_ps(G) if faction(p) == "death"]


def alive_humans(G):
    return [p for p in alive_ps(G) if faction(p) == "human"]


def do_kill(G, p, cause):
    p["alive"] = False
    p["cause"] = cause
    G["st"]["d_" + cause] += 1


def check_end(G):
    """屠城阈值：场上人类 ≤ 场上死亡阵营人数 → 死亡阵营胜。"""
    if G["winner"]:
        return True
    if len(alive_humans(G)) <= len(alive_death(G)):
        G["winner"] = "death"
        return True
    return False


def night_phase(G, acts):
    G["night"] += 1
    N = G["players"]
    alive = alive_ps(G)
    humans = alive_humans(G)

    # 1. 门先生守护
    guard_set = set()
    gd = next((p for p in alive if p["role"] == "门先生"), None)
    if acts and gd is not None:
        pool = [p for p in alive if p["id"] != gd["id"] and p["id"] not in G["last_guard"]]
        random.shuffle(pool)
        guard_set = {p["id"] for p in pool[:2]}

    # 2. 死亡阵营提交击杀 + 转化
    souls = [p for p in alive if p["role"] == "魂灵"]
    soul_knives = [rnd(humans)["id"] for _ in souls] if humans else []
    rea = next((p for p in alive if p["role"] == "死神"), None)
    reaper_knives = []
    G["convert_pick"] = None
    if rea is not None:
        slots = min(2, max(0, DEATH_CAP - len(souls)))
        reaper_knives = [rnd(humans)["id"] for _ in range(slots)] if humans else []
        if not G["convert_used"]:
            used = [pid for pid, _ in G["pending"]]
            dead_h = [p for p in N if (not p["alive"]) and faction(p) == "human"
                      and p["role"] != "夜祷" and p["id"] not in used]
            if dead_h and random.random() < 0.7:
                G["convert_pick"] = rnd(dead_h)["id"]

    # 3. 莱莱可
    ass_knife = None
    lai = next((p for p in alive if p["role"] == "莱莱可" and not p["knife_gone"]), None)
    if acts and lai is not None and G["night"] > 1:
        pool = [p for p in alive if p["id"] != lai["id"]]
        if pool:
            ass_knife = rnd(pool)["id"]

    # 4. 夜祷（穿透）
    pray = next((p for p in alive if p["role"] == "夜祷"), None)
    pray_knife = rnd(humans)["id"] if (pray is not None and humans) else None

    # 击杀优先级：夜祷 > 魂灵① > 莱莱可 > 魂灵② > 死神刀
    ordered = []
    if pray_knife is not None:
        ordered.append((pray_knife, True))
    if soul_knives:
        ordered.append((soul_knives[0], False))
    if ass_knife is not None:
        ordered.append((ass_knife, False))
    if len(soul_knives) > 1:
        ordered.append((soul_knives[1], False))
    ordered += [(t, False) for t in reaper_knives]

    taken, kills, slots = set(), [], DEATH_CAP
    for t, pierce in ordered:
        if slots <= 0:
            break
        if t in taken:      # 同目标不重复计数、不重复占名额
            continue
        taken.add(t)
        slots -= 1
        kills.append({"t": t, "pierce": pierce, "canceled": False, "saved": False})
    for k in kills:
        if not k["pierce"] and k["t"] in guard_set:
            k["canceled"] = True  # 守护抵消（刀位已消耗）

    # V4.4 门先生代出局：两名被守者同夜均被非穿透刀命中且均被守护抵消
    subst = False
    if G["cfg"]["guard_subst"] and gd is not None and len(guard_set) == 2:
        canceled_ts = {k["t"] for k in kills if k["canceled"]}
        if guard_set <= canceled_ts:
            subst = True

    # 5. 水妖① 夜间即时救护
    eff = [k["t"] for k in kills if not k["canceled"]]
    if subst:
        eff.append(gd["id"])
    nix = next((p for p in alive if p["role"] == "水妖"), None)
    if acts and nix is not None and G["nixie"]["night"] > 0 and eff:
        if random.random() < 0.8:
            t = rnd(eff)
            if subst and t == gd["id"]:
                subst = False  # 门先生被救回
            else:
                for k in kills:
                    if not k["canceled"] and k["t"] == t:
                        k["saved"] = True
                        break
            G["nixie"]["night"] -= 1
            G["st"]["nixie_save"] += 1

    # 死亡结算
    for k in kills:
        if k["canceled"] or k["saved"]:
            continue
        do_kill(G, N[k["t"]], "night")
    if subst:
        do_kill(G, gd, "subst")
        G["st"]["subst"] += 1

    # 信息记录：只把“验到死亡阵营”的结果交给白天投票 AI。
    # V4.4 N1 不行动；旧规则也可通过 info_model=False 保持完全随机口径。
    if acts and G["cfg"].get("info_model", True):
        mi = next((p for p in alive_ps(G) if p["role"] == "米提亚"), None)
        if mi is not None:
            pool = alive_ps(G)
            targets = random.sample(pool, min(2, len(pool)))
            G["mitia_check"] = {"targets": [p["id"] for p in targets],
                                 "positive": any(faction(p) == "death" for p in targets)}
        ar = next((p for p in alive_ps(G) if p["role"] == "降临者"), None)
        reaper = next((p for p in alive_ps(G) if p["role"] == "死神"), None)
        if ar is not None and reaper is not None:
            G["arrival_check"] = {"target": reaper["id"], "positive": True}

    # B2：莱莱可刺杀死神（2 魂灵出局后 = 永久）
    if G["winner"] is None and rea is not None and not rea["alive"] and rea["cause"] == "night":
        if G["a_count"] >= 2:
            G["winner"] = "human"
            G["st"]["win_B2"] += 1
        else:
            G["pending"].append((rea["id"], "return"))

    # 夜祷转化结算（复活优先冲突：目标已在回归名单 → 转化不生效不耗次数）
    if G["convert_pick"] is not None and not G["convert_used"]:
        tp = N[G["convert_pick"]]
        if (not tp["alive"]) and tp["id"] not in [pid for pid, _ in G["pending"]]:
            G["convert_used"] = True
            G["pending"].append((tp["id"], "prayer"))
            G["st"]["convert"] += 1

    # 水妖③：水妖本人当夜出局 → 被动复活
    if nix is not None and not nix["alive"] and G["nixie"]["passive"] > 0:
        used = [pid for pid, _ in G["pending"]]
        cands = [p for p in N if (not p["alive"]) and faction(p) == "human"
                 and p["role"] != "夜祷" and not (p["base"] == "魂灵" and p["soul_out"])
                 and p["id"] not in used]
        if cands and random.random() < 0.8:
            G["pending"].append((rnd(cands)["id"], "revive"))
            G["nixie"]["passive"] -= 1
            G["st"]["nixie_passive"] += 1

    G["last_guard"] = guard_set


def do_exile(G, p):
    do_kill(G, p, "exile")
    if p["role"] == "死神":
        if G["a_count"] >= 2:  # B1 终局放逐
            G["winner"] = "human"
            G["st"]["win_B1"] += 1
            return
        G["pending"].append((p["id"], "return"))
    elif p["role"] == "魂灵":
        if not p["soul_out"]:
            p["soul_out"] = True
            G["a_count"] += 1
            G["st"]["soul_out"] += 1
    elif p["role"] == "夜祷":
        G["st"]["prayer_dead"] += 1  # 永久死亡
    else:
        nix = next((q for q in alive_ps(G) if q["role"] == "水妖"), None)
        if nix is not None and G["nixie"]["exile"] > 0:
            G["exile_revive"] = True
        if p["role"] == "水妖":
            G["nixie_dead_passive"] = True


def day_phase(G):
    # 回归名单
    if G["pending"]:
        for pid, kind in G["pending"]:
            p = G["players"][pid]
            p["alive"] = True
            p["cause"] = None
            if kind == "prayer":
                p["role"] = "夜祷"
        G["st"]["returns"] += len(G["pending"])
        G["pending"] = []
    if check_end(G):
        return

    # 领袖（首日票选，出局后补选）
    alive = alive_ps(G)
    if not G["election_done"]:
        mitia = next((p for p in alive if p["role"] == "米提亚"), None)
        # 有信息时好人有 40%–60% 的浮动意愿推举米提亚；其余仍随机。
        if G["cfg"].get("info_model", True) and mitia is not None and random.random() < random.uniform(.4, .6):
            G["leader"] = mitia["id"]
        else:
            G["leader"] = rnd(alive)["id"]
        G["election_done"] = True
    elif G["leader"] is None or not G["players"][G["leader"]]["alive"]:
        G["leader"] = rnd(alive)["id"]

    # 放逐投票
    humans = alive_humans(G)
    tally = Counter()
    leader_vote = None
    for p in alive:
        if faction(p) == "death":
            pool = humans if humans else [q for q in alive if q["id"] != p["id"]]
        else:
            pool = [q for q in alive if q["id"] != p["id"]]
            if G["cfg"].get("info_model", True):
                mc = G.get("mitia_check")
                ac = G.get("arrival_check")
                # 米提亚验出死亡阵营且本人是领袖：99% 集中在被验两人之间。
                if mc and mc["positive"] and G["leader"] == next((q["id"] for q in alive if q["role"] == "米提亚"), -1):
                    checked = [q for q in alive if q["id"] in mc["targets"] and faction(q) == "death"]
                    if checked and random.random() < .99:
                        pool = checked
                # 米提亚非领袖仍有较强影响；降临者确认死神时同理。
                elif mc and mc["positive"] and random.random() < .72:
                    checked = [q for q in alive if q["id"] in mc["targets"] and faction(q) == "death"]
                    if checked:
                        pool = checked
                elif ac and ac["positive"] and random.random() < .85:
                    target = next((q for q in alive if q["id"] == ac["target"]), None)
                    if target is not None:
                        pool = [target]
        if not pool:
            continue
        v = rnd(pool)["id"]
        tally[v] += 1
        if p["id"] == G["leader"]:
            leader_vote = v
    if leader_vote is not None:
        tally[leader_vote] += 0.5  # 领袖 1.5 票
    if tally:
        mx = max(tally.values())
        top = [t for t, c in tally.items() if c == mx]
        if len(top) == 1:  # 平票无人出局
            do_exile(G, G["players"][top[0]])
            if G["winner"]:
                return

    # 水妖② 白天放逐复活
    if G["exile_revive"]:
        G["exile_revive"] = False
        used = [pid for pid, _ in G["pending"]]
        cands = [q for q in G["players"] if (not q["alive"]) and q["cause"] == "exile"
                 and faction(q) == "human" and q["role"] != "夜祷" and q["id"] not in used]
        if cands and random.random() < 0.7:
            G["pending"].append((rnd(cands)["id"], "revive"))
            G["nixie"]["exile"] -= 1
            G["st"]["nixie_exile_revive"] += 1

    # 水妖③（放逐触发）
    if G["nixie_dead_passive"]:
        G["nixie_dead_passive"] = False
        if G["nixie"]["passive"] > 0:
            used = [pid for pid, _ in G["pending"]]
            cands = [q for q in G["players"] if (not q["alive"]) and faction(q) == "human"
                     and q["role"] != "夜祷" and not (q["base"] == "魂灵" and q["soul_out"])
                     and q["id"] not in used]
            if cands and random.random() < 0.8:
                G["pending"].append((rnd(cands)["id"], "revive"))
                G["nixie"]["passive"] -= 1
                G["st"]["nixie_passive"] += 1

    check_end(G)


def play(cfg):
    G = new_game(cfg)
    while G["winner"] is None and G["night"] < 80:
        acts = not (cfg["n1_death_only"] and G["night"] == 0)
        night_phase(G, acts)
        if G["winner"]:
            break
        day_phase(G)
    if G["winner"] is None:
        G["winner"] = "death"  # 僵局
    G["humans_left"] = len(alive_humans(G))
    return G


def run(label, cfg, n):
    random.seed(20260902)
    res = [play(cfg) for _ in range(n)]
    hw = [g for g in res if g["winner"] == "human"]
    n_hw = len(hw)
    rate = n_hw / n * 100
    se = (max(rate * (100 - rate), 0.01) / n) ** 0.5
    avg_days = sum(g["night"] for g in res) / n
    avg_days_hw = (sum(g["night"] for g in hw) / n_hw) if hw else float("nan")
    agg = Counter()
    for g in res:
        agg.update(g["st"])
    subst_pg = agg["subst"] / n
    conv_pg = agg["convert"] / n
    print(f"[{label}]")
    print(f"  局数 {n} | 人类胜 {n_hw} ({rate:.1f}% ± {1.96*se:.1f}) | 死亡阵营胜 {n-n_hw}")
    print(f"  平均昼夜数 {avg_days:.2f} | 人类胜局平均昼夜 {avg_days_hw:.2f}")
    print(f"  场均: 门先生代出局 {subst_pg:.3f} | 夜祷转化 {conv_pg:.2f} | 水妖①救 {agg['nixie_save']/n:.2f}"
          f" | ②放逐复活 {agg['nixie_exile_revive']/n:.2f} | ③被动复活 {agg['nixie_passive']/n:.2f}"
          f" | 回归人次 {agg['returns']/n:.2f} | 魂灵出局 {agg['soul_out']/n:.2f}")
    print(f"  人类胜来源: B1 放逐 {agg['win_B1']} | B2 刺杀 {agg['win_B2']}")
    dw = [g for g in res if g["winner"] == "death"]
    hl = sum(g["humans_left"] for g in dw) / max(len(dw), 1)
    d5 = sum(1 for g in res if g["night"] >= 5) / n * 100
    print(f"  死亡阵营胜局终局人类余量 {hl:.2f} 人 | ≥5 昼夜局占比 {d5:.1f}%")
    print()
    return rate, avg_days


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3000
    info_model = "--random" not in sys.argv
    variants = [
        ("V4.3.1 基准(11人)", {"n_common": 3, "n1_death_only": False, "guard_subst": False, "info_model": info_model}),
        ("V4.4-A 仅平民+2(13人)", {"n_common": 5, "n1_death_only": False, "guard_subst": False, "info_model": info_model}),
        ("V4.4-B A+首夜死亡方行动", {"n_common": 5, "n1_death_only": True, "guard_subst": False, "info_model": info_model}),
        ("V4.4 完整(+门先生代出局)", {"n_common": 5, "n1_death_only": True, "guard_subst": True, "info_model": info_model}),
    ]
    print(f"=== 《死魂灵的夜曲》随机基准推演 · 每变体 {n} 局 ===\n")
    for label, cfg in variants:
        run(label, cfg, n)
