"""EnergyFlex command line.

  python cli.py generate    --scale starter|full [--seed N]   synthetic data -> data/<scale>/
  python cli.py validate    --scale ...                         data/<scale>/validation_summary.{md,json}
  python cli.py analyze     --scale ...                         outputs/<scale>/
  python cli.py repro-check --scale ...                         regenerate twice, compare checksums
  python cli.py build-site  --scale full                        site/data/*.json for the dashboard
  python cli.py all         --scale ...                         everything above in order
  python cli.py package     [--out PATH]                        release ZIP of HEAD + every manifest file, verified
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from energyflex import config

ROOT = Path(__file__).resolve().parent


def data_dir(scale):
    return ROOT / "data" / scale


def out_dir(scale):
    return ROOT / "outputs" / scale


def cmd_generate(a, root=None):
    from energyflex.export import write_dataset
    from energyflex.generate import generate
    root = Path(root or data_dir(a.scale))
    if root.exists():
        shutil.rmtree(root)
    t0 = time.time()
    tables, gt, meta = generate(a.scale, a.seed)
    formats = ("csv", "json", "sql") if not getattr(a, "csv_only", False) else ("csv",)
    m = write_dataset(tables, gt, meta, root, formats)
    from energyflex import docs
    docs.render(ROOT / "docs" / "DATA_DICTIONARY.md")
    print(f"[generate] {a.scale} seed={a.seed} -> {root} in {time.time() - t0:.1f}s")
    for k, v in m["row_counts"].items():
        print(f"  {k:28s}{v:>9,}")
    return m


def cmd_validate(a):
    from energyflex import io, validate
    root = data_dir(a.scale)
    rows = validate.run(io.load_dataset(root), io.load_ground_truth(root))
    s = validate.write_report(rows, root)
    print(f"[validate] {s['checks']} checks: PASS {s['pass']}, EXPECTED_FAIL {s['expected_fail']}, FAIL {s['fail']}")
    for r in rows:
        if r["status"] == "FAIL":
            print(f"  FAIL {r['check']}: {r['unexplained']} unexplained, e.g. {r['sample'][:3]}")
    return s


def cmd_analyze(a):
    from energyflex.analytics import pipeline
    res = pipeline.run(data_dir(a.scale), out_dir(a.scale))
    print(json.dumps(res["headline"], indent=2))
    return res


def cmd_repro(a):
    runs = []
    for i in (1, 2):
        tmp = Path(tempfile.mkdtemp(prefix=f"energyflex-repro{i}-"))
        m = cmd_generate(a, tmp)
        runs.append(m)
        shutil.rmtree(tmp)
    f1 = {f["path"]: f for f in runs[0]["files"]}
    f2 = {f["path"]: f for f in runs[1]["files"]}
    diffs = [p for p in sorted(set(f1) | set(f2)) if f1.get(p, {}).get("sha256") != f2.get(p, {}).get("sha256")]
    report = {"scale": a.scale, "seed": a.seed, "files_compared": len(f1), "row_counts_equal":
              runs[0]["row_counts"] == runs[1]["row_counts"], "checksum_mismatches": diffs,
              "reproducible": not diffs and runs[0]["row_counts"] == runs[1]["row_counts"],
              "row_counts": runs[0]["row_counts"],
              "checksums": {p: f["sha256"] for p, f in f1.items()}}
    committed = data_dir(a.scale) / "manifest.json"
    if committed.exists():
        cm = {f["path"]: f["sha256"] for f in json.loads(committed.read_text())["files"]}
        report["matches_committed_dataset"] = all(cm.get(p) == f["sha256"] for p, f in f1.items() if p in cm)
    data_dir(a.scale).mkdir(parents=True, exist_ok=True)
    (data_dir(a.scale) / "repro_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    print(f"[repro-check] reproducible={report['reproducible']} files={len(f1)} mismatches={diffs}")
    return report


def cmd_site(a):
    from energyflex import site
    site.build(data_dir(a.scale), out_dir(a.scale), ROOT / "site" / "data")
    print(f"[build-site] wrote {ROOT / 'site' / 'data'}")


PACKAGE_PREFIX = "EnergyFlex/"
PACKAGE_FORBIDDEN = (".env", ".vercel", ".git/")


def manifest_problems(read, names, scales=tuple(config.SCALES)):
    """Every file listed in each data/<scale>/manifest.json must be present (read(path) -> bytes) with its SHA-256."""
    bad = []
    for s in scales:
        m = json.loads((data_dir(s) / "manifest.json").read_text(encoding="utf-8"))
        for f in m["files"]:
            p = f"data/{s}/{f['path']}"
            if p not in names:
                bad.append(f"missing  {p}")
            elif hashlib.sha256(read(p)).hexdigest() != f["sha256"]:
                bad.append(f"checksum {p}")
    return bad


def cmd_package(a):
    """Release ZIP = committed HEAD (git archive) + manifest-listed files that .gitignore keeps out of Git.
    Refuses to run with uncommitted changes and deletes the ZIP unless every manifest file matches its checksum."""
    git = lambda *c: subprocess.run(["git", *c], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    dirty = git("status", "--porcelain", "--untracked-files=no").strip()
    if dirty:
        sys.exit(f"[package] commit or stash these changes first:\n{dirty}")
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    git("archive", "--format=zip", f"--prefix={PACKAGE_PREFIX}", "-o", str(out), "HEAD")
    tracked = set(git("ls-files").splitlines())
    added = []
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as z:
        for s in config.SCALES:
            for f in json.loads((data_dir(s) / "manifest.json").read_text(encoding="utf-8"))["files"]:
                p = f"data/{s}/{f['path']}"
                if p not in tracked and (ROOT / p).exists():
                    z.write(ROOT / p, PACKAGE_PREFIX + p)
                    added.append(p)
    with zipfile.ZipFile(out) as z:
        names = {n[len(PACKAGE_PREFIX):] for n in z.namelist()}
        bad = manifest_problems(lambda p: z.read(PACKAGE_PREFIX + p), names)
        bad += [f"forbidden {n}" for n in names if any(x in n for x in PACKAGE_FORBIDDEN)]
    if bad:
        out.unlink()
        sys.exit("[package] ZIP rejected; regenerate with `python cli.py all --scale <scale>` then retry:\n  " + "\n  ".join(bad))
    print(f"[package] {out} ({out.stat().st_size / 2**20:.1f} MB, {len(names)} entries, "
          f"{len(added)} untracked data files added); all manifest checksums verified")


def main(argv=None):
    p = argparse.ArgumentParser(description="EnergyFlex: energy waste & peak demand correlation")
    p.add_argument("command", choices=["generate", "validate", "analyze", "repro-check", "build-site", "all", "package"])
    p.add_argument("--scale", choices=list(config.SCALES), default="starter")
    p.add_argument("--seed", type=int, default=config.SEED)
    p.add_argument("--out", default=str(ROOT / "dist" / "EnergyFlex.zip"), help="package: ZIP path")
    a = p.parse_args(argv)
    if a.command == "package":
        cmd_package(a)
        return
    if a.command == "generate":
        cmd_generate(a)
    elif a.command == "validate":
        s = cmd_validate(a)
        sys.exit(1 if s["fail"] else 0)
    elif a.command == "analyze":
        cmd_analyze(a)
    elif a.command == "repro-check":
        r = cmd_repro(a)
        sys.exit(0 if r["reproducible"] else 1)
    elif a.command == "build-site":
        cmd_site(a)
    else:
        cmd_generate(a)
        cmd_validate(a)
        cmd_repro(a)
        cmd_analyze(a)
        if a.scale == "full":
            cmd_site(a)


if __name__ == "__main__":
    main()
