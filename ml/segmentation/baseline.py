"""T74 사용자 군집 baseline · 품질 평가 (ML04 / F-025). 표준 라이브러리만 사용합니다.

입력: 기술 숙련도 벡터 JSONL (T147 합성 공장 `--out-features` 형식)
      {"entity_id", "skills": {코드: 1~5}, "dataset_version", "source", ...}
출력: 모델 버전·데이터 버전이 붙은 평가 보고서(dict). 개인 식별자와 개별 배정 결과는 보고서에 넣지 않습니다.

안전 규칙 (T25 Feature 계약, T71 행동·동의 계약, AI_SYSTEM_ARCHITECTURE §3.1)
  * 특징은 기술 숙련도만 사용한다. 민감·차별 우려 속성이 특징 입력에 있으면 거부한다.
  * 동의하지 않았거나(`consent` 가 false) 기준 시각 이후에 이용 가능해진(`available_at` > as_of) 행은 제외한다.
  * 편향 평가용 집단 라벨(`groups_by_entity`)은 평가에만 쓰며, 군집 입력으로 쓰이지 않는다.
  * 5명 미만 군집은 보고서에서 크기를 숨긴다 (T71 k=5).
  * 같은 입력·seed → 같은 결과 (결정적).

이 모듈은 DB·네트워크에 접근하지 않고 아무것도 저장하지 않습니다. 임계값은 제안값이며 PM 승인 전입니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from typing import Iterable

SEGMENTATION_VERSION = "t74.1"
FEATURE_VERSION = "skill_vector.v1"
MAX_PROFICIENCY = 5
K_ANON_MIN = 5  # T71 집계 조회 k (제안)

# 특징 입력에 있으면 안 되는 속성 (T71 §4 민감·차별 우려 속성, 직접 식별 정보)
FORBIDDEN_FEATURE_KEYS = frozenset(
    {
        "name", "email", "phone", "ip", "address", "gender", "sex", "age", "birth", "birth_year",
        "disability", "religion", "politics", "health", "nationality", "race", "marital_status",
        "photo", "location_gps",
    }
)
ALLOWED_SOURCES = frozenset({"synthetic_seed"})  # 승인된 실데이터 출처는 별도 승인 후 추가

# 제안 임계값 (PM 승인 전)
PROPOSED_TARGETS = {
    "silhouette_min": 0.10,
    "seed_stability_ari_min": 0.80,
    "representation_ratio_range": (0.5, 2.0),
    "min_cluster_size": K_ANON_MIN,
}


class SegmentationError(Exception):
    """잘못된 입력·금지된 특징·평가 실패."""


# ---------------------------------------------------------------- 입력 검증

def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise SegmentationError("timestamps must include a timezone")
    return dt.astimezone(timezone.utc)


def prepare_rows(rows: Iterable[dict], as_of: str) -> tuple[list[dict], dict]:
    """검증하고 제외 사유별 건수를 센다. 금지 특징·출처·중복·잘못된 값은 오류로 거부한다."""
    cutoff = _parse_time(as_of)
    kept: list[dict] = []
    excluded: Counter = Counter()
    seen: set[str] = set()
    versions: set[str] = set()
    for row in rows:
        entity = row.get("entity_id")
        if not isinstance(entity, str) or not entity:
            raise SegmentationError("entity_id is required")
        if entity in seen:
            raise SegmentationError("duplicate entity_id")
        seen.add(entity)
        if row.get("source") not in ALLOWED_SOURCES:
            raise SegmentationError("source is not approved for segmentation")
        skills = row.get("skills")
        if not isinstance(skills, dict):
            raise SegmentationError("skills must be an object")
        bad = FORBIDDEN_FEATURE_KEYS & {str(k).lower() for k in list(row) + list(skills)}
        if bad:
            raise SegmentationError(f"forbidden feature attribute: {sorted(bad)[0]}")
        for level in skills.values():
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= MAX_PROFICIENCY:
                raise SegmentationError("proficiency must be an integer 1..5")
        if row.get("consent") is False:
            excluded["no_consent"] += 1
            continue
        if row.get("available_at") is not None and _parse_time(row["available_at"]) > cutoff:
            excluded["available_after_as_of"] += 1
            continue
        if not skills:
            excluded["empty_skills"] += 1
            continue
        versions.add(str(row.get("dataset_version")))
        kept.append(row)
    if len(versions) > 1:
        raise SegmentationError("mixed dataset_version")
    info = {
        "input_rows": len(seen),
        "used_rows": len(kept),
        "excluded": dict(sorted(excluded.items())),
        "dataset_version": next(iter(versions), None),
    }
    return kept, info


def build_matrix(rows: list[dict]) -> tuple[list[list[float]], list[str]]:
    """숙련도/5 로 정규화한 벡터. 미입력은 0 (원본을 덮어쓰지 않는 계산 스냅샷)."""
    codes = sorted({c for r in rows for c in r["skills"]})
    index = {c: i for i, c in enumerate(codes)}
    matrix = []
    for r in rows:
        vec = [0.0] * len(codes)
        for c, level in r["skills"].items():
            vec[index[c]] = level / MAX_PROFICIENCY
        matrix.append(vec)
    return matrix, codes


# ---------------------------------------------------------------- 군집

def _sqdist(a: list[float], b: list[float]) -> float:
    return sum((x - y) * (x - y) for x, y in zip(a, b))


def kmeans(X: list[list[float]], k: int, seed: int, n_init: int = 5, max_iter: int = 100):
    """k-means++ 초기화 + Lloyd. (labels, inertia). seed 가 같으면 결과도 같다."""
    n = len(X)
    if not 2 <= k <= n:
        raise SegmentationError("k must satisfy 2 <= k <= number of rows")
    best = None
    for run_no in range(n_init):
        rng = random.Random(f"{seed}:{run_no}")
        centers = [X[rng.randrange(n)]]
        while len(centers) < k:
            d2 = [min(_sqdist(x, c) for c in centers) for x in X]
            total = sum(d2)
            if total == 0:
                centers.append(X[rng.randrange(n)])
                continue
            pick, acc = rng.random() * total, 0.0
            chosen = X[-1]
            for i, w in enumerate(d2):
                acc += w
                if acc >= pick:
                    chosen = X[i]
                    break
            centers.append(chosen)
        labels: list[int] = []
        for step in range(max_iter):
            new = [min(range(k), key=lambda j: (_sqdist(x, centers[j]), j)) for x in X]
            if new == labels:
                break
            labels = new
            dim = len(X[0])
            sums = [[0.0] * dim for _ in range(k)]
            counts = [0] * k
            for x, lab in zip(X, labels):
                counts[lab] += 1
                for i, v in enumerate(x):
                    sums[lab][i] += v
            for j in range(k):
                if counts[j]:
                    centers[j] = [s / counts[j] for s in sums[j]]
        inertia = sum(_sqdist(x, centers[lab]) for x, lab in zip(X, labels))
        if best is None or inertia < best[1] - 1e-12:
            best = (labels, inertia)
    return best


# ---------------------------------------------------------------- 평가 지표

def silhouette(X: list[list[float]], labels: list[int]) -> float:
    """평균 silhouette (유클리드). 크기 1 군집의 점은 0 으로 둔다. O(n²)."""
    n = len(X)
    clusters: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        clusters.setdefault(lab, []).append(i)
    if len(clusters) < 2:
        raise SegmentationError("silhouette needs at least 2 clusters")
    total = 0.0
    for i in range(n):
        own = clusters[labels[i]]
        if len(own) == 1:
            continue
        a = sum(math.sqrt(_sqdist(X[i], X[j])) for j in own if j != i) / (len(own) - 1)
        b = min(
            sum(math.sqrt(_sqdist(X[i], X[j])) for j in members) / len(members)
            for lab, members in clusters.items() if lab != labels[i]
        )
        denom = max(a, b)
        total += 0.0 if denom == 0 else (b - a) / denom
    return total / n


def adjusted_rand_index(a: list, b: list) -> float:
    """두 군집화의 일치도 (-1~1, 라벨 이름·순서와 무관)."""
    if len(a) != len(b) or not a:
        raise SegmentationError("label lists must have the same non-zero length")
    n = len(a)

    def comb2(x: int) -> int:
        return x * (x - 1) // 2

    sum_ij = sum(comb2(v) for v in Counter(zip(a, b)).values())
    sum_a = sum(comb2(v) for v in Counter(a).values())
    sum_b = sum(comb2(v) for v in Counter(b).values())
    expected = sum_a * sum_b / comb2(n) if n > 1 else 0.0
    max_index = (sum_a + sum_b) / 2
    if max_index == expected:
        return 1.0
    return (sum_ij - expected) / (max_index - expected)


def seed_stability(X: list[list[float]], k: int, seeds: list[int]) -> dict:
    """서로 다른 seed 로 군집화한 결과들의 쌍별 ARI."""
    runs = [kmeans(X, k, s)[0] for s in seeds]
    aris = [adjusted_rand_index(x, y) for x, y in combinations(runs, 2)]
    return {"seeds": seeds, "ari_mean": sum(aris) / len(aris), "ari_min": min(aris)}


def representation_report(labels: list[int], groups: list[str]) -> dict:
    """집단별 군집 표현 비율 = (군집 내 집단 비중) / (전체 집단 비중). 평가 전용 라벨."""
    if len(groups) != len(labels):
        raise SegmentationError("groups must align with rows")
    n = len(labels)
    overall = {g: c / n for g, c in Counter(groups).items()}
    low, high = PROPOSED_TARGETS["representation_ratio_range"]
    ratios, flagged = [], []
    for lab in sorted(set(labels)):
        member_groups = [g for g, lb in zip(groups, labels) if lb == lab]
        if len(member_groups) < K_ANON_MIN:
            continue  # 작은 군집은 비율이 불안정하고 k=5 로 숨김
        for g, share in overall.items():
            ratio = (member_groups.count(g) / len(member_groups)) / share
            ratios.append(ratio)
            if not low <= ratio <= high:
                flagged.append({"cluster": lab, "group": g, "ratio": round(ratio, 3)})
    return {
        "ratio_min": round(min(ratios), 3) if ratios else None,
        "ratio_max": round(max(ratios), 3) if ratios else None,
        "flagged": flagged,
        "within_range": not flagged,
    }


# ---------------------------------------------------------------- 보고서

def feature_distribution(rows: list[dict], codes: list[str]) -> dict:
    n = len(rows)
    per_skill = {}
    for c in codes:
        levels = [r["skills"][c] for r in rows if c in r["skills"]]
        per_skill[c] = {"coverage": round(len(levels) / n, 4), "mean": round(sum(levels) / len(levels), 3)}
    counts = [len(r["skills"]) for r in rows]
    return {
        "skills_per_user": {"min": min(counts), "max": max(counts), "mean": round(sum(counts) / n, 3)},
        "per_skill": per_skill,
    }


def fingerprint(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def run(
    rows: Iterable[dict],
    as_of: str,
    k_range: tuple[int, int] = (2, 8),
    seed: int = 74,
    stability_seeds: tuple[int, ...] = (1, 2, 3, 4, 5),
    groups_by_entity: dict[str, str] | None = None,
    reference_by_entity: dict[str, str] | None = None,
) -> tuple[dict, list[int]]:
    """(보고서, 사용된 행 순서대로의 군집 라벨). 라벨은 호출자 메모리에만 있고 보고서에는 없다."""
    used, info = prepare_rows(rows, as_of)
    if len(used) < K_ANON_MIN * 2:
        raise SegmentationError("not enough rows for segmentation")
    X, codes = build_matrix(used)
    lo = max(2, k_range[0])
    hi = min(k_range[1], len(used) // K_ANON_MIN)
    if lo > hi:
        raise SegmentationError("k range is empty for this number of rows")
    candidates = []
    for k in range(lo, hi + 1):
        labels, inertia = kmeans(X, k, seed)
        sizes = Counter(labels)
        candidates.append(
            {
                "k": k,
                "silhouette": round(silhouette(X, labels), 4),
                "inertia": round(inertia, 4),
                "min_cluster_size": min(sizes.values()),
            }
        )
    eligible = [c for c in candidates if c["min_cluster_size"] >= K_ANON_MIN] or candidates
    chosen = max(eligible, key=lambda c: (c["silhouette"], -c["k"]))
    labels, _ = kmeans(X, chosen["k"], seed)
    sizes = Counter(labels)
    targets = PROPOSED_TARGETS
    stab = seed_stability(X, chosen["k"], list(stability_seeds))
    report = {
        "model": {
            "name": "kmeans_skill_vector",
            "segmentation_version": SEGMENTATION_VERSION,
            "feature_version": FEATURE_VERSION,
            "seed": seed,
        },
        "data": {**info, "as_of": as_of, "skill_count": len(codes)},
        "feature_distribution": feature_distribution(used, codes),
        "k_selection": candidates,
        "chosen_k": chosen["k"],
        "cluster_sizes": sorted(
            ({"cluster": c, "size": s if s >= K_ANON_MIN else f"<{K_ANON_MIN}"} for c, s in sizes.items()),
            key=lambda d: d["cluster"],
        ),
        "metrics": {
            "silhouette": chosen["silhouette"],
            "seed_stability": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in stab.items()},
        },
        "proposed_targets": {**targets, "representation_ratio_range": list(targets["representation_ratio_range"])},
        "target_check": {
            "silhouette": chosen["silhouette"] >= targets["silhouette_min"],
            "seed_stability": stab["ari_mean"] >= targets["seed_stability_ari_min"],
            "min_cluster_size": chosen["min_cluster_size"] >= targets["min_cluster_size"],
        },
        "status_note": "targets are proposals pending PM approval; synthetic data only",
    }
    if groups_by_entity is not None:
        groups = [groups_by_entity[r["entity_id"]] for r in used]
        report["representation"] = representation_report(labels, groups)
        report["target_check"]["representation"] = report["representation"]["within_range"]
    if reference_by_entity is not None:
        # 활용성 참고 지표: 군집이 사용자가 밝힌 목표 직무 같은 비민감 기준과 얼마나 맞는지 (평가 전용)
        ref = [reference_by_entity[r["entity_id"]] for r in used]
        report["external_agreement_ari"] = round(adjusted_rand_index(labels, ref), 4)
    report["report_fingerprint"] = fingerprint(report)
    return report, labels


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T74 segmentation baseline (synthetic/approved data only)")
    ap.add_argument("--input", required=True, help="features JSONL")
    ap.add_argument("--as-of", required=True, help="ISO-8601 timestamp with timezone")
    ap.add_argument("--k-min", type=int, default=2)
    ap.add_argument("--k-max", type=int, default=8)
    ap.add_argument("--seed", type=int, default=74)
    ap.add_argument("--out", help="report JSON path (default: stdout)")
    args = ap.parse_args(argv)
    with open(args.input, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    try:
        report, _ = run(rows, args.as_of, (args.k_min, args.k_max), args.seed)
    except SegmentationError as exc:
        print(f"T74_SEGMENTATION=FAIL reason={exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    print(
        f"T74_SEGMENTATION=OK k={report['chosen_k']} silhouette={report['metrics']['silhouette']} "
        f"fingerprint={report['report_fingerprint']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
