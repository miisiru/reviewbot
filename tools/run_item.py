"""한 건의 검토 재료를 한 번에 만든다(AI 없음).
python run_item.py <rev_id> [queue 파일(기본 work/queue.json)]
  1. 받기(prep.py: 모든 파트) 2. tabs.py(광추 · 성혼 시트, 쇼케이스 시작) 3. gp_fast(보유 효과 4fps 시트, 90초 단위)
  4. 전체 개요(0.25fps) — 결과 화면 · 시작 위치 확인용
출력: 요약을 찍고 runs/<rev>/ 아래에 tabs<i>/sheet.jpg, gpf<i>/NN.jpg, ov<i>.jpg 를 만든다."""
import sys, os, json, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ROOT, RUNS, WORK, PY, FF   # noqa: E402
SCR = WORK
os.makedirs(SCR, exist_ok=True)
rev = sys.argv[1]
qf = sys.argv[2] if len(sys.argv) > 2 else os.path.join(WORK, "queue.json")
q = json.load(open(qf, encoding="utf8"))
item = next(x for x in q if x["id"] == rev)
one = os.path.join(SCR, f"q_{rev}.json")
json.dump([item], open(one, "w", encoding="utf8"), ensure_ascii=False)
env = dict(os.environ, HQ_QUEUE=one, PYTHONIOENCODING="utf8")
print(subprocess.run([PY, os.path.join(ROOT, "tools", "prep.py"), rev], capture_output=True, text=True, encoding="utf8", env=env).stdout.strip())
d = os.path.join(RUNS, rev)
vids = json.load(open(os.path.join(d, "videos.json"), encoding="utf8"))
p = item["payload"]
sides = p.get("runs") or [p]
print("submitted:", json.dumps({k: p.get(k) for k in ("mode", "boss_name", "subcategory", "metric_value", "action_value", "flags")}, ensure_ascii=False))
print("team:", [(p.get(f"p{i}_char"), p.get(f"p{i}_eidolon"), p.get(f"p{i}_lc"), p.get(f"p{i}_superimp")) for i in range(1, 5)])
print("urls:", [s["video_url"] for s in sides])
for i, v in enumerate(vids):
    vf = os.path.join(d, v["file"])
    out = subprocess.run([FF, "-i", vf], capture_output=True, text=True, errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    print(f"--- {v['file']} part {v['part']}/{v['parts']}{' (run part)' if v['run_part'] else ''} {dur:.0f}s")
    t = subprocess.run([PY, os.path.join(ROOT, "tools", "tabs.py"), rev, str(i)], capture_output=True, text=True, encoding="utf8", env=env).stdout
    wins = [l for l in t.splitlines() if l.startswith("#")]
    print("\n".join(wins) if wins else "tabs: no character screens")
    print(t.strip().splitlines()[-1])
    # 보유 효과 4fps 시트(90초 단위, 전체)
    n = int(dur // 90) + 1
    for s in range(n):
        subprocess.run(["bash", os.path.join(ROOT, "tools", "gp_fast.sh"), rev, str(i), str(s * 90), "90"], capture_output=True)
        o = os.path.join(d, f"gpf{i}")
        keep = os.path.join(d, f"gpf{i}_{s * 90}")
        os.makedirs(keep, exist_ok=True)
        for fn in os.listdir(o):
            os.replace(os.path.join(o, fn), os.path.join(keep, fn))
    print("gp sheets:", ", ".join(f"gpf{i}_{s * 90}/01.jpg" for s in range(n)))
    # 개요 0.25fps(최대 14열)
    subprocess.run(["bash", os.path.join(ROOT, "tools", "scan_sheet.sh"), rev, str(i), "0", str(int(dur)), "0.25", "14"], capture_output=True,
                   env=dict(os.environ, PATH=os.path.dirname(PY) + os.pathsep + os.environ["PATH"]))
    src = os.path.join(d, f"scan{i}", "01.jpg")
    if os.path.exists(src):
        os.replace(src, os.path.join(d, f"ov{i}.jpg"))
        print(f"overview: ov{i}.jpg")
