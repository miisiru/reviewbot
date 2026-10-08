"""검토 한 건 준비: 영상 받기 + 겹친 프레임 시트.
python prep.py <rev_id> [<rev_id> ...]   (queue.json 에서 payload 를 읽는다)

빌리빌리 영상은 한 영상 안에 여러 파트(P1 실전, P2 配置补录 등)를 올리는 일이 있다. 공유 링크의 p= 는 한 파트만
가리키므로, p= 를 떼고 모든 파트를 각각 video{i}.mp4 로 받는다. 받은 파일 목록은 videos.json 에 적는다
(file, url, part, parts, run_part: 제출 링크가 가리킨 파트인지, src: 제출 링크)."""
import sys, json, os, subprocess, re, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ROOT, RUNS, WORK, YT, FF   # noqa: E402
q = {x["id"]: x for x in json.load(open(os.environ.get("HQ_QUEUE") or os.path.join(WORK, "queue.json"), encoding="utf8"))}

def tstart(url):
    m = re.search(r"[?&#]t=(\d+)(?:s)?", url) or re.search(r"[?&]start=(\d+)", url)
    return int(m.group(1)) if m else 0

def sheet(video, out, start=0, dur=None, every=3, cols=5, rows=5, width=480):
    os.makedirs(out, exist_ok=True)
    vf = f"fps=1/{every},scale={width}:-1,drawtext=text='%{{pts\\:hms}}':x=5:y=5:fontsize=20:fontcolor=yellow:box=1:boxcolor=black,tile={cols}x{rows}"
    if start: vf = vf.replace("%{pts\\:hms}", f"%{{pts\\:hms\\:{start}}}")
    cmd = [FF, "-loglevel", "error", "-ss", str(start)] + (["-t", str(dur)] if dur else []) + ["-i", video, "-vf", vf, "-q:v", "3", "-y", os.path.join(out, "%02d.jpg")]
    subprocess.run(cmd, stderr=subprocess.DEVNULL)

def resolve(url):
    """b23.tv 같은 짧은 링크는 넘겨주는 주소로 푼다."""
    if re.search(r"//(b23\.tv|bili2233\.cn)/", url):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=20).geturl()
        except Exception:
            return url
    return url

def bili_parts(url):
    """빌리빌리 BV 영상이면 (BV, 링크가 가리킨 파트, 파트 수). 아니면 None."""
    m = re.search(r"bilibili\.com/video/(BV[0-9A-Za-z]+)", url)
    if not m:
        return None
    bv = m.group(1)
    pm = re.search(r"[?&]p=(\d+)", url)
    p = subprocess.run([YT, "--flat-playlist", "--print", "%(playlist_index)s", f"https://www.bilibili.com/video/{bv}"],
                       capture_output=True, text=True, encoding="utf8", errors="replace")
    n = len([x for x in p.stdout.split() if x.strip()])
    return bv, int(pm.group(1)) if pm else 1, max(1, n)

FORMATS = ["bv*[vcodec^=avc1][height<=720]/bv*[height<=720][ext=mp4]/bv*[height<=720]/b",
           "bv*[vcodec^=avc1][height<=480]/bv*[height<=480]/b",
           "bv*[vcodec^=avc1][height<=1080]/bv*[height<=1080]/b"]


def decoded_ratio(v, expect=None):
    """끝까지 디코드되는 몫(1fps 로 센 프레임 / 길이). 빌리빌리 720p 파일이 끝부분에서 깨지는 일이 있다.
    길이는 사이트가 알려 준 길이(expect)를 먼저 쓴다 — 깨진 파일은 머리의 길이 정보도 틀릴 수 있다."""
    out = subprocess.run([FF, "-i", v, "-vf", "fps=1", "-f", "null", "-"], capture_output=True, text=True, errors="replace").stderr
    f = re.findall(r"frame=\s*(\d+)", out)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    dur = expect or (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0)
    if not f or not dur:
        return 0.0
    return min(1.0, int(f[-1]) / max(1.0, dur))


MAX_SECONDS = 20 * 60   # 이보다 긴 영상은 받지 않고 CHECK(사용자, 2026-10-09)

BILI_HOSTS = ["upos-sz-mirrorcosov.bilivideo.com", "upos-sz-mirrorali.bilivideo.com", "upos-sz-mirrorcos.bilivideo.com"]


def bili_fast(u, fmt, v):
    """빌리빌리: 영상 주소만 yt-dlp 로 얻고, CDN 미러를 빠른 곳(cosov)으로 바꿔 curl 로 받는다.
    빌리빌리는 요청마다 미러를 다르게 주는데 어떤 미러(G-Core 오사카 등)는 80KB/s 라 한 건에 수십 분 걸렸다.
    → yt-dlp --print 꼴의 「길이|제목」, 못 받으면 None(그때는 yt-dlp 로 받는다)"""
    p = subprocess.run([YT, "--js-runtimes", "node", "--no-playlist", "-f", fmt, "--print", "%(duration)s|%(title)s", "--print", "urls", u],
                       capture_output=True, text=True, encoding="utf8", errors="replace")
    lines = [x for x in p.stdout.splitlines() if x.strip()]
    if len(lines) < 2 or not lines[1].startswith("http") or "\n" in lines[1].strip():
        return None
    orig = lines[1].strip()
    tmp = v + ".m4s"
    # 미러를 차례로: 15초 동안 500KB/s 밑이면 끊고 다음 미러(cosov 도 가끔 멈춘다: rev_p81y5s 12분)
    srcs = [re.sub(r"^https://upos-[a-z0-9-]+\.bilivideo\.com", f"https://{h}", orig) for h in BILI_HOSTS] + [orig]
    ok = False
    for src in dict.fromkeys(srcs):
        if os.path.exists(tmp):
            os.remove(tmp)
        r = subprocess.run(["curl", "-s", "-f", "-L", "--speed-limit", "500000", "--speed-time", "15", "--connect-timeout", "10",
                            "-H", "Referer: https://www.bilibili.com/", "-A", "Mozilla/5.0", "-o", tmp, src])
        if r.returncode == 0 and os.path.exists(tmp):
            ok = True
            break
    if not ok:
        if os.path.exists(tmp):
            os.remove(tmp)
        return None
    subprocess.run([FF, "-loglevel", "error", "-y", "-i", tmp, "-c", "copy", v])
    os.remove(tmp)
    return lines[0] + "\n" if os.path.exists(v) else None


def download(u, v):
    """720p 로 받고, 끝까지 디코드되지 않으면(90% 미만) 480p, 1080p 순으로 다시 받는다."""
    log = ""
    for k, fmt in enumerate(FORMATS):
        if os.path.exists(v):
            os.remove(v)
        out = bili_fast(u, fmt, v) if "bilibili.com" in u else None
        if out:
            log += out + "(fast mirror)\n"
        else:
            # 빌리빌리 CDN 은 10M 조각 요청에 639바이트 오류 응답만 줘서 재시도로 수십 분을 버린다 → 조각 없이 받으면 수 초
            chunk = [] if "bilibili.com" in u else ["--http-chunk-size", "10M"]
            p = subprocess.run([YT, "-q", "--no-progress", "--js-runtimes", "node", "--retries", "50", "--fragment-retries", "50", *chunk, "-N", "4", "--ffmpeg-location", FF,
                                "--no-playlist", "-f", fmt, "-o", v, "--print", "%(duration)s|%(title)s", "--no-simulate", u],
                               capture_output=True, text=True, encoding="utf8", errors="replace")
            log += p.stdout + p.stderr[-1000:]
            out = p.stdout
        if os.path.exists(v):
            dm = re.match(r"\s*([\d.]+)\|", out)
            r = decoded_ratio(v, float(dm.group(1)) if dm else None)
            log += f"\nformat try {k + 1}: decoded {r:.0%}\n"
            if r >= 0.9:
                return log
    return log + "\nWARNING: every format decoded incompletely\n"

for rid in sys.argv[1:]:
    rev = q[rid]; d = os.path.join(RUNS, rid); os.makedirs(d, exist_ok=True)
    runs = rev["payload"].get("runs") or [rev["payload"]]
    json.dump(rev, open(os.path.join(d, "review.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    entries, seen = [], set()
    for r in runs:
        src = r["video_url"]
        url = resolve(src)
        bp = bili_parts(url)
        if bp:
            bv, runp, n = bp
            for k in range(1, n + 1):
                key = (bv, k)
                if key in seen:
                    for e in entries:
                        if e["key"] == list(key) and k == runp:
                            e["run_part"] = True
                    continue
                seen.add(key)
                entries.append({"key": [bv, k], "url": f"https://www.bilibili.com/video/{bv}?p={k}" if n > 1 else f"https://www.bilibili.com/video/{bv}",
                                "part": k, "parts": n, "run_part": k == runp, "src": src})
        else:
            base = re.sub(r"[?&](t|start|si|is)=[^&]*", "", url)
            if base in seen:
                continue
            seen.add(base)
            entries.append({"key": base, "url": base, "part": 1, "parts": 1, "run_part": True, "src": src})
    # 20분 넘는 영상은 받지 않는다(사용자, 2026-10-09: 시간만 들고 틀리기 쉽다) → too_long.json, run_queue 가 CHECK 로 보낸다
    tl_p = os.path.join(d, "too_long.json")
    long_ = []
    for i, e in enumerate(entries):
        v = os.path.join(d, f"video{i}.mp4")
        if os.path.exists(v):
            # 이미 받은 파일은 파일 길이로
            o = subprocess.run([FF, "-i", v], capture_output=True, text=True, errors="replace").stderr
            mm = re.search(r"Duration: (\d+):(\d+):([\d.]+)", o)
            sec = int(mm.group(1)) * 3600 + int(mm.group(2)) * 60 + float(mm.group(3)) if mm else 0
        else:
            p = subprocess.run([YT, "--js-runtimes", "node", "--no-playlist", "--skip-download", "--print", "%(duration)s", e["url"]],
                               capture_output=True, text=True, encoding="utf8", errors="replace")
            m = re.match(r"\s*([\d.]+)", p.stdout)
            sec = float(m.group(1)) if m else 0
        if sec > MAX_SECONDS:
            long_.append({"url": e["url"], "seconds": sec})
    if long_:
        json.dump(long_, open(tl_p, "w", encoding="utf8"), ensure_ascii=False, indent=1)
        json.dump(entries, open(os.path.join(d, "videos.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
        print(rid, "TOO-LONG", ", ".join(f"{x['seconds'] / 60:.0f}min" for x in long_))
        continue
    if os.path.exists(tl_p):
        os.remove(tl_p)
    for i, e in enumerate(entries):
        v = os.path.join(d, f"video{i}.mp4")
        e["file"] = f"video{i}.mp4"
        if not os.path.exists(v):
            out = download(e["url"], v)
            open(os.path.join(d, f"video{i}.info"), "w", encoding="utf8").write(
                e["url"] + f"\npart {e['part']}/{e['parts']}" + (" (run part)" if e["run_part"] else "") + "\n" + out)
        if os.path.exists(v): sheet(v, os.path.join(d, f"sheet{i}"))
    json.dump(entries, open(os.path.join(d, "videos.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    ok = all(os.path.exists(os.path.join(d, e["file"])) for e in entries)
    parts = ", ".join(f"{e['file']}=p{e['part']}/{e['parts']}{'*' if e['run_part'] else ''}" for e in entries)
    print(rid, "ok" if ok else "FAIL", parts)
