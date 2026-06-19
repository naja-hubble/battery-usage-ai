#!/usr/bin/env python
"""Stage and zip the FCC patent-evidence v4 deliverables into a single bundle.

Bundles the published data artifacts (internal `_*` caches excluded), the four v4
reports + intervention scaffolds, and all dpi=300 anonymous figures, with a
README manifest (SHA-256). Technical evidence for patent review -- NOT legal advice.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from battery_usage import patent_common_v4 as pc

DATE = "2026-06-19"
REPORT_FILES = [
    "fcc_patent_evidence_v4_report.md", "fcc_invention_disclosure_v4.md",
    "fcc_patent_counsel_brief_v4.md", "fcc_patent_v4_adversarial_review.md",
    "fcc_patent_summary_slides_v4.md", "fcc_patent_summary_slides_v4.pptx",
    "fcc_intervention_data_schema_v4.csv", "fcc_intervention_power_simulation_v4.csv",
]


def sha16(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()[:16]


def main() -> int:
    bundle = pc.REPORTS / "patent_evidence_v4_bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "data").mkdir(parents=True)
    (bundle / "reports").mkdir()
    (bundle / "figures").mkdir()

    data_files = [p for p in pc.V4_DIR.glob("*") if p.is_file() and not p.name.startswith("_")]
    for p in data_files:
        shutil.copy2(p, bundle / "data" / p.name)
    report_files = [pc.REPORTS / n for n in REPORT_FILES if (pc.REPORTS / n).exists()]
    for p in report_files:
        shutil.copy2(p, bundle / "reports" / p.name)
    figs = sorted(pc.FIG_DIR.glob("*.png"))
    for p in figs:
        shutil.copy2(p, bundle / "figures" / p.name)

    bt = chr(96)   # backtick, kept out of any shell-interpolated context
    L = []
    L.append(f"# FCC Patent Evidence v4 Bundle ({DATE})")
    L.append("")
    L.append("> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。")
    L.append("> 先行技術はUNVERIFIED。地上真実・介入結果・FWバージョン・因果結論は一切捏造していない。")
    L.append("")
    L.append("## 構成")
    L.append(f"- {bt}data/{bt} : 解析成果物（CSV/parquet/JSON、内部キャッシュ {bt}_*{bt} は除外）")
    L.append(f"- {bt}reports/{bt} : v4報告書・発明届・カウンセルブリーフ・敵対的レビュー・介入schema/power-sim")
    L.append(f"- {bt}figures/{bt} : 全図（dpi=300・匿名、user_id/serial/UUID無し）")
    L.append("")
    L.append("## 主要結論（独立エンドポイント、proxy非依存）")
    L.append("- IC1 機会条件付きEND無応答: STRONG（A2刺激-応答特異性 5/5・A3 END汚染0）")
    L.append("- IC2 デュアルトラック非対称リセット: STRONG（C2: 対称比+115証拠温存・hard減112）※production実装済を開示")
    L.append("- IC5 有界保持因果台帳+最小状態: STRONG（D: recall1/dup0 @ストレージ比0.042）")
    L.append("- IC6 ギャップ/censor品質: STRONG（E: 誤no-response naive→proposed 大幅減）")
    L.append("- IC7 クローズドループ: PROSPECTIVE（介入/version NOT AVAILABLE）")
    L.append("- IC8 機種非依存スクリーニング: MEDIUM / version局在 PROSPECTIVE")
    L.append("")
    L.append("## 留保")
    L.append("技術エビデンス強度 ≠ 新規性リスク。先行技術は全てUNVERIFIED、出願前に正式FTO/特許性調査・弁理士レビュー必須。")
    L.append("法的novelty/inventive step/侵害自由/登録可能性は一切主張しない。")
    L.append("")
    total = len(data_files) + len(report_files) + len(figs)
    L.append(f"## ファイル一覧（{total} files, SHA-256 16桁）")
    L.append("")
    for sub in ("data", "reports", "figures"):
        L.append(f"### {sub}/")
        for p in sorted((bundle / sub).glob("*")):
            L.append(f"- {bt}{p.name}{bt} ({p.stat().st_size} B, sha256:{sha16(p)})")
        L.append("")
    (bundle / "README.md").write_text("\n".join(L), encoding="utf-8")

    zip_path = pc.REPORTS / f"patent_evidence_v4_bundle_{DATE}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(bundle.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(bundle.parent))
    n = sum(1 for p in bundle.rglob("*") if p.is_file())
    print(f"BUNDLE: {zip_path.relative_to(pc.REPO)}")
    print(f"  staged dir: {bundle.relative_to(pc.REPO)}")
    print(f"  files: {n} (data={len(data_files)}, reports={len(report_files)}, "
          f"figures={len(figs)}, +README)")
    print(f"  zip size: {zip_path.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
