"""검토 한 건의 신뢰도(0~100%)와 경고. 도구가 아는 약점(영상 파일 · 메뉴 못 찾음 · 캐릭터 수 부족 · 이름 못 읽음 · 워터마크 · 낮은 화질 ·
시트에서 눈으로 읽은 값의 불확실함)을 깎아서 계산한다. 문턱 이하면 「LOW CONFIDENCE」 경고를 붙인다.
python confidence.py <rev> [--low "이유:깎을 점수" ...] [--threshold 80]
  --confirmed-missing  tabs.py 가 못 찾은 화면을 8fps 시트 · 전체 개요로 직접 확인해 정말 없었음을 확인했을 때(감점 없앰)
  --low  사람이(내가) 눈으로 읽을 때 불확실했던 것. 예: --low "AV cell read from blurry frame:20" --low "Eidolon lock icons small:10"
출력 한 줄: 「Confidence: 85% (reasons ...)」 + 문턱 이하면 「⚠ LOW CONFIDENCE」"""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RUNS as ROOT   # noqa: E402
rev = sys.argv[1]
thr = 80
lows = []
confirmed = False
a = sys.argv[2:]
i = 0
while i < len(a):
    if a[i] == "--threshold":
        thr = int(a[i + 1]); i += 2
    elif a[i] == "--confirmed-missing":
        confirmed = True; i += 1
    elif a[i] == "--low":
        t, _, n = a[i + 1].rpartition(":"); lows.append((t, int(n))); i += 2
    else:
        i += 1
d = os.path.join(ROOT, rev)
rj = json.load(open(os.path.join(d, "review.json"), encoding="utf8"))
p = rj["payload"]
sides = p.get("runs") or [p]
team = len({x.get(f"p{k}_char") for x in sides for k in range(1, 5) if x.get(f"p{k}_char")})
score, why = 100, []
vids = json.load(open(os.path.join(d, "videos.json"), encoding="utf8")) if os.path.exists(os.path.join(d, "videos.json")) else [{"file": "video0.mp4"}]
tabs = []
for k in range(len(vids)):
    sj = os.path.join(d, f"tabs{k}", "summary.json")
    if os.path.exists(sj):
        tabs.append(json.load(open(sj)))
if not tabs:
    score, why = 0, ["no tabs.py result"]
else:
    if any(t.get("decode_error") for t in tabs):
        score, why = 0, ["video file broken (decode error)"]
    else:
        lc = sum(t["distinct"]["LightCone"] + t["unnamed"]["LightCone"] for t in tabs)
        ei = sum(t["distinct"]["Eidolon"] + t["unnamed"]["Eidolon"] for t in tabs)
        if all(t["windows"] == 0 for t in tabs):
            score -= 50; why.append("no character screens found (tool may have failed)")
        for name, n in (("Light Cone", lc), ("Eidolon", ei)):
            if n < team:
                if confirmed:
                    why.append(f"{name} screens found for {n}/{team} characters - missing ones confirmed by dense scan")
                else:
                    score -= 25 * (team - n); why.append(f"{name} screens found for {n}/{team} characters (confirm 'not shown' by 8fps scan)")
            elif n > team + 1:
                score -= 5; why.append(f"{name} screens found for {n} (> team {team}), duplicates possible")
        un = sum(t["unnamed"]["LightCone"] + t["unnamed"]["Eidolon"] for t in tabs)
        if un:
            score -= 8 * un; why.append(f"{un} screen(s) whose character name could not be read")
        for k in range(len(tabs)):
            tl = os.path.join(d, f"tabs{k}", "timeline.txt")
            if os.path.exists(tl):
                m = re.search(r"watermark_px=(\d+)", open(tl, encoding="utf8").read())
                if m and int(m.group(1)) > 1500:
                    score -= 5; why.append("heavy watermark over the name line")
for k, v in enumerate(vids):
    inf = os.path.join(d, f"video{k}.info")
    vf = os.path.join(d, v.get("file", f"video{k}.mp4"))
    if os.path.exists(vf):
        sh = os.popen(f'"C:\\Users\\User\\AppData\\Roaming\\Python\\Python314\\site-packages\\imageio_ffmpeg\\binaries\\ffmpeg-win-x86_64-v7.1.exe" -i "{vf}" 2>&1').read()
        m = re.search(r"Video:.*?, (\d{3,5})x(\d{3,5})", sh)
        if m and min(int(m.group(1)), int(m.group(2))) < 540:
            score -= 10; why.append(f"low resolution video ({m.group(1)}x{m.group(2)})")
for t, n in lows:
    score -= n; why.append(f"{t} (-{n})")
score = max(0, min(100, score))
line = f"Confidence: {score}%" + (f" ({'; '.join(why)})" if why else " (all checks clean)")
if score <= thr:
    line += f"\n⚠ LOW CONFIDENCE (<= {thr}%): please check this one yourself before clicking"
print(line)
