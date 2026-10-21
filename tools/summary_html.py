"""한 번에 처리한 기록들의 간단한 요약을 HTML 한 장으로 만든다(판정별 묶음 + 기록 카드).
모양은 theherta.com 의 기록 목록(/archive)을 따른다: 어두운 배경, 「✦ 묶음 이름 (n entries)」 머리글, 캐릭터 · 광추 그림 + E / S 배지,
사이클 알약, LTD / STD 알약, 날짜 · 플랫폼. 사이트의 클래스 이름을 그대로 쓰고 사이트 스타일시트(ui_theme/site.css)를 함께 싣는다.
그림은 우리 assets 저장소(HF fffffffff1/assets)의 캐릭터 얼굴(spriteoutput/avataricon/avatar/<아이디>.png)과 광추 아이콘
(spriteoutput/itemicon/lightconeicons/<아이디>.png) — 사이트 그림과 맞춰 본 것(캐릭터는 픽셀까지 같은 그림). 아이디를 모르거나(개척자)
그림이 없으면 사이트 그림. 시각(m s)은 영상의 그 시각으로 가는 링크(유튜브 ?t=초 · 빌리빌리 ?p=파트&t=초), 사유마다 관련 시각을 붙인다.
python summary_html.py [rev_id ...] [--out work/summary.html]   (rev 를 주지 않으면 runs/ 전체의 auto.json)"""
import os, sys, re, json, html
from datetime import datetime
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import ROOT, RUNS, WORK   # noqa: E402

SITE = 'https://theherta.com'
HF = 'https://huggingface.co/datasets/fffffffff1/assets/resolve/main/'
THEME = os.path.join(ROOT, 'ui_theme', 'site.css')
ORDER = ['CHECK', 'REJECT', 'APPROVE']            # 사람이 먼저 봐야 할 것부터
VERDICT_LOOK = {                                   # 카드 테두리 · 배지 색(사이트의 강조 행: 붉은 테두리 · 보라 테두리 행과 같은 방식)
    'APPROVE': ('border-emerald-400/40 bg-emerald-500/[0.06] rb-c-approve', 'text-emerald-300 border-emerald-400/40 bg-emerald-500/10 rb-v-approve'),
    'CHECK': ('border-amber-400/40 bg-amber-500/[0.06] rb-c-check', 'text-amber-300 border-amber-400/40 bg-amber-500/10 rb-v-check'),
    'REJECT': ('border-red-500/50 bg-red-500/[0.07] rb-c-reject', 'text-red-300 border-red-500/50 bg-red-500/10 rb-v-reject'),
}

LITE_CSS = """
:root{--bg:#020205;--panel:rgba(15,15,25,.72);--text:#e2e8f0;--dim:#94a3b8;--blue:#60a5fa;--purple:#c084fc;--pink:#fb7185;--gold:#fbbf24}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,rgba(96,165,250,.10),transparent),radial-gradient(900px 500px at 100% 0,rgba(192,132,252,.08),transparent),#020205;
  color:var(--text);min-height:100vh;background-attachment:fixed;font-family:Geist,Inter,system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.35}
a{color:inherit;text-decoration:none}
.rb-wrap{max-width:860px;margin:0 auto;padding:18px 12px 60px;display:flex;flex-direction:column;gap:12px}
.rb-title{font-size:26px;font-weight:800;letter-spacing:-.01em;background:linear-gradient(120deg,#60a5fa 0%,#c084fc 52%,#fb7185 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.rb-sub{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:rgba(255,255,255,.35);font-weight:700}
.rb-stats{display:flex;flex-wrap:wrap;gap:8px}
.rb-group{display:flex;flex-direction:column;gap:4px;border-radius:12px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);overflow:hidden}
.rb-ghead{display:flex;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.08);font-size:14px;font-weight:600;text-align:left}
.rb-gicon{color:var(--blue)}
.rb-gcount{color:rgba(255,255,255,.3);font-size:12px;font-weight:400}
.rb-gbody{display:flex;flex-direction:column;gap:4px;padding:2px}
.rb-card{position:relative;border-radius:12px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);overflow:hidden;transition:all .4s cubic-bezier(.4,0,.2,1)}
.rb-card:hover{background:rgba(255,255,255,.05)}
.rb-row{display:flex;gap:10px;padding:8px}
.rb-team{display:flex;gap:6px;flex-shrink:0}
.rb-slot{display:flex;flex-direction:column;align-items:center;gap:4px}
.rb-char{position:relative;display:block;width:56px;height:56px;border-radius:8px;overflow:hidden;background:rgba(255,255,255,.05);box-shadow:0 0 0 1px rgba(255,255,255,.08)}
.rb-char.rb-first{box-shadow:0 0 0 1px rgba(147,197,253,.5),0 0 10px rgba(96,165,250,.15)}
.rb-lc{position:relative;display:block;width:36px;height:50px;border-radius:4px;overflow:hidden;background:rgba(255,255,255,.05);box-shadow:0 0 0 1px rgba(255,255,255,.1);margin-top:2px}
.rb-char img,.rb-lc img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.rb-char img{object-position:top}
.rb-badge{position:absolute;right:0;bottom:0;font-size:11px;font-weight:700;padding:0 6px;line-height:15px;border-radius:4px 0 0 0;background:rgba(0,0,0,.85)}
.rb-e{color:#bfdbfe}.rb-s{color:#e9d5ff}
a.rb-char:hover,a.rb-lc:hover{box-shadow:0 0 0 2px rgba(147,197,253,.8)}
.rb-mid{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:4px}
.rb-line{display:flex;align-items:center;gap:6px;min-width:0}
.rb-name{font-size:14px;font-weight:600;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
a.rb-name:hover{color:#93c5fd}
.rb-meta{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:11px;color:rgba(255,255,255,.25);white-space:nowrap;font-variant-numeric:tabular-nums}
a.rb-meta:hover{color:rgba(255,255,255,.6)}
.rb-yt,.rb-bili{display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:10px;letter-spacing:.06em}.rb-yt{color:#f87171}.rb-bili{color:#38bdf8}
.rb-pills{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.rb-pill{display:inline-flex;align-items:center;gap:6px;padding:2px 8px 2px 6px;border-radius:999px;border:1px solid rgba(56,189,248,.3);background:linear-gradient(90deg,rgba(14,165,233,.15),rgba(59,130,246,.10),rgba(14,165,233,.05));box-shadow:0 0 10px -2px rgba(56,189,248,.35);white-space:nowrap}
.rb-pill i{width:4px;height:4px;border-radius:99px;background:#7dd3fc;box-shadow:0 0 6px rgba(56,189,248,.9)}
.rb-pill b{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:rgba(125,211,252,.7)}
.rb-pill span{font-size:12px;font-weight:700;color:#bae6fd;font-variant-numeric:tabular-nums}
.rb-sub-pill{font-size:10px;padding:2px 8px;border-radius:999px;background:rgba(59,130,246,.1);border:1px solid rgba(59,130,246,.2);color:rgba(96,165,250,.8);white-space:nowrap}
.rb-verdict{font-size:10px;font-weight:800;letter-spacing:.08em;padding:2px 8px;border-radius:999px;border:1px solid;white-space:nowrap}
.rb-cnt{display:inline-flex;align-items:center;gap:6px;padding:2px 4px 2px 8px;border-radius:999px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.02);white-space:nowrap}
.rb-cnt b{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:rgba(255,255,255,.3)}
.rb-cnt span{font-size:12px;font-weight:700;min-width:20px;text-align:center;padding:2px 6px;border-radius:999px;background:rgba(255,255,255,.05);color:rgba(255,255,255,.4)}
.rb-cnt.rb-ltd{background:rgba(249,115,22,.1);border-color:rgba(249,115,22,.5)}
.rb-cnt.rb-ltd b{color:#fdba74}.rb-cnt.rb-ltd span{background:rgba(255,255,255,.1);color:#fff}
.rb-end{margin-left:auto;display:flex;gap:6px}
.rb-why{margin:2px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:2px;font-size:11px;color:rgba(255,255,255,.55)}
.rb-why li:before{content:"• ";color:rgba(255,255,255,.3)}
.rb-why.rb-bad li{color:#fca5a5}.rb-why.rb-chk li{color:#fcd34d}
.rb-t{color:#93c5fd;border-bottom:1px dotted rgba(147,197,253,.6);white-space:nowrap;font-variant-numeric:tabular-nums}
.rb-t:hover{color:#dbeafe;border-bottom-style:solid}
.rb-links{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.rb-link{font-size:10px;padding:2px 8px;border-radius:999px;background:rgba(59,130,246,.1);border:1px solid rgba(59,130,246,.2);color:#93c5fd;white-space:nowrap}
.rb-link:hover{background:rgba(59,130,246,.2)}
.rb-process{font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px;background:linear-gradient(120deg,rgba(96,165,250,.28),rgba(192,132,252,.24));border:1px solid rgba(147,197,253,.5);color:#dbeafe;white-space:nowrap}
.rb-process:hover{background:linear-gradient(120deg,rgba(96,165,250,.45),rgba(192,132,252,.4))}
.rb-c-approve{border-color:rgba(52,211,153,.4)!important;background:rgba(16,185,129,.06)!important}
.rb-c-check{border-color:rgba(251,191,36,.4)!important;background:rgba(245,158,11,.06)!important}
.rb-c-reject{border-color:rgba(239,68,68,.5)!important;background:rgba(239,68,68,.07)!important}
.rb-v-approve{color:#6ee7b7;border-color:rgba(52,211,153,.4);background:rgba(16,185,129,.1)}
.rb-v-check{color:#fcd34d;border-color:rgba(251,191,36,.4);background:rgba(245,158,11,.1)}
.rb-v-reject{color:#fca5a5;border-color:rgba(239,68,68,.5);background:rgba(239,68,68,.1)}
@media(max-width:640px){.rb-char{width:40px;height:40px}.rb-lc{width:24px;height:36px}.rb-meta{display:none}.rb-row{flex-wrap:wrap}}
"""


def esc(x):
    return html.escape(str(x if x is not None else ''), quote=True)


# ---------- 그림 ----------
def _en(name):
    from judge import en_key
    return en_key(name)


def char_src(name):
    """우리 assets 의 캐릭터 얼굴. 아이디가 하나로 정해지지 않으면(개척자: 여덟 아이디) None → 사이트 그림."""
    try:
        import imgrec
        ids = imgrec.char_ids(_en(name))
        if ids and len(set(ids)) == 1:
            return f'{HF}spriteoutput/avataricon/avatar/{ids[0]}.png'
    except Exception:
        pass
    return None


def lc_src(name):
    try:
        import imgrec
        i = imgrec.lc_ids()[0].get(_en(name))
        if i:
            return f'{HF}spriteoutput/itemicon/lightconeicons/{i}.png'
    except Exception:
        pass
    return None


def site_src(kind, name):
    return f'{SITE}/px_{kind}/{quote(str(name))}.png'


def img_tag(kind, name, cls=''):
    ours = char_src(name) if kind == 'char' else lc_src(name)
    site = site_src(kind, name)
    return (f'<img alt="{esc(name)}" title="{esc(name)}" loading="lazy" referrerpolicy="no-referrer" src="{esc(ours or site)}" class="{cls}" '
            f'onerror="if(this.dataset.f){{this.style.display=\'none\'}}else{{this.dataset.f=1;this.src=\'{esc(site)}\'}}">')


# ---------- 시각 ----------
def fmt(sec):
    sec = int(max(0, float(sec)))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f'{h}h {m}m {s}s' if h else f'{m}m {s}s' if m else f'{s}s'


def url_at(base, sec):
    """영상 주소의 sec 초 지점. 유튜브 ?t=초, 빌리빌리 ?p=파트&t=초(빌리빌리는 ?t=100 으로 100초부터 재생되는 것을 확인함)."""
    if not base:
        return ''
    u = urlsplit(re.sub(r'(youtu\.be/[^?&#/]+)&', r'\1?', base.strip(), count=1))
    q = [(k, v) for k, v in parse_qsl(u.query) if k not in ('t', 'start', 'time_continue', 'si', 'is')]
    if (u.hostname or '').endswith('bilibili.com') or u.hostname == 'b23.tv':
        q = [kv for kv in q if kv[0] == 'p']
    q.append(('t', str(int(max(0, float(sec))))))
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(q), ''))


def when(iso):
    try:
        return datetime.fromisoformat(str(iso).replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except Exception:
        return ''


def platform(url):
    u = url or ''
    # 아이콘과 글자를 같은 색 글자 상자 하나에 넣는다(사이트: text-red-400 안에 아이콘 + 「YT」). 따로 두면 아이콘이 바깥의 흐린 색을 물려받는다
    if 'bilibili' in u or 'b23.tv' in u:
        return '<span class="rb-bili inline-flex items-center gap-1.5 text-sky-400"><i class="fa-brands fa-bilibili text-[11px]"></i>bili</span>'
    if 'youtu' in u:
        return '<span class="rb-yt inline-flex items-center gap-1.5 text-red-400"><i class="fa-brands fa-youtube text-[11px]"></i>YT</span>'
    return ''


def _json(path):
    try:
        return json.load(open(path, encoding='utf8'))
    except (OSError, ValueError):
        return None


def load(rev):
    d = os.path.join(RUNS, rev)
    item, auto = _json(os.path.join(d, 'review.json')), _json(os.path.join(d, 'auto.json'))
    if not item or not auto:
        return None
    pl = item.get('payload') or {}
    sides = pl.get('runs') or [pl]
    videos = _json(os.path.join(d, 'videos.json')) or []
    selection = _json(os.path.join(d, 'segment_selection.json'))
    judged = _json(os.path.join(d, 'judge.json')) or {}
    side = dict(pl, **sides[0])
    battle = selection['battle_index'] if selection else next((i for i, v in enumerate(videos) if v.get('run_part')), 0)
    build = selection['build_index'] if selection else (judged.get('build_indices') or [battle])[0]
    return {'rev': rev, 'side': side, 'runs': len(sides), 'auto': auto, 'videos': videos, 'selection': selection,
            'judged': judged, 'battle_vid': battle, 'build_vid': build}


class Times:
    """한 기록의 시각 링크 만들기."""
    def __init__(self, e):
        self.e = e
        self.base = e['side'].get('video_url') or ''
        self.chars = e['auto'].get('build') or []
        self.judged = e['judged']

    def base_of(self, vid):
        v = self.e['videos']
        if 0 <= vid < len(v):
            return v[vid].get('url') or v[vid].get('src') or self.base
        return self.base

    def link(self, sec, vid=None, label=None, prefix=''):
        if sec is None:
            return ''
        vid = self.e['build_vid'] if vid is None else vid
        return f'<a class="rb-t" href="{esc(url_at(self.base_of(vid), sec))}" target="_blank" rel="noopener">{esc(prefix)}{esc(label or fmt(sec))}</a>'

    def char_time(self, name, kind):
        """name 캐릭터가 영상에 나오는 시각: kind = 'lc' | 'e' | 'any'. 못 찾으면 None."""
        k = next((i for i, c in enumerate(self.chars) if c.get('char') == name), None)
        if k is None:
            return None
        c = self.chars[k]
        t = {'lc': c.get('lc_t'), 'e': c.get('e_t')}
        for o in ([kind, 'e', 'lc'] if kind in t else ['e', 'lc']):
            if t.get(o) is not None:
                return t[o]
        fr = [f['t'] for f in (self.judged.get('frames') or []) if f.get('char_k') == k and f.get('vid') == self.e['build_vid']]
        return min(fr) if fr else None

    def battle(self):
        sel = self.e['selection']
        return sel['battle'] if sel else None

    def showcase(self):
        sel = self.e['selection']
        return sel['build'][0] if sel else self.e['auto'].get('showcase')

    def reason(self, text):
        """사유 글 + 관련 시각 링크. 이름이 든 사유는 그 캐릭터가 나오는 시각, 「(at 12.3s, 45.6s)」는 그 시각들, 사이클 · 점수는 전투 끝."""
        out = esc(text)
        m = re.search(r'\(at ((?:\d+(?:\.\d+)?s(?:, )?)+)\)', text)
        if m:
            secs = re.findall(r'(\d+(?:\.\d+)?)s', m.group(1))
            return esc(text[:m.start()]) + '(at ' + ', '.join(self.link(float(x)) for x in secs) + ')' + esc(text[m.end():])
        names = sorted((c.get('char') for c in self.chars if c.get('char') and text.startswith(str(c['char']))), key=len, reverse=True)
        if names:
            kind = 'e' if 'Eidolon' in text else 'lc' if ('Light Cone' in text or 'Superimposition' in text) else 'any'
            t = self.char_time(names[0], kind)
            if t is not None:
                return out + ' — ' + self.link(t, prefix=f'{names[0]} ')
            return out + ' — <span class="rb-gcount">not found in the video</span>'
        if re.search(r'Cycles mismatch|Score mismatch|Action Value|Category mismatch|HUD|hourglass|Cycles \(', text):
            b = self.battle()
            if b:
                return out + ' — ' + self.link(b[1], vid=self.e['battle_vid'], prefix='battle end ')
            s = self.showcase()
            if s is not None:
                return out + ' — ' + self.link(s, prefix='showcase ')
        if re.search(r'incomplete attempt|Shared showcase|imestamp|showcase', text):
            parts = []
            b = self.battle()
            if b:
                parts.append(self.link(b[0], vid=self.e['battle_vid'], prefix='battle '))
            s = self.showcase()
            if s is not None:
                parts.append(self.link(s, prefix='showcase '))
            if parts:
                return out + ' — ' + ' · '.join(parts)
        return out


def card(e):
    s, a = e['side'], e['auto']
    tm = Times(e)
    verdict = a.get('verdict', 'CHECK')
    border, badge = VERDICT_LOOK.get(verdict, VERDICT_LOOK['CHECK'])
    video = s.get('video_url') or ''
    slots = []
    for i in range(1, 5):
        c = s.get(f'p{i}_char')
        if not c:
            continue
        lc = s.get(f'p{i}_lc')
        first = ' rb-first ring-1 ring-blue-300/50' if i == 1 else ' ring-1 ring-white/8'
        t_char, t_lc = tm.char_time(c, 'e'), tm.char_time(c, 'lc')
        base = tm.base_of(e['build_vid'])

        def wrap(cls, tag_cls, inner, t, title):
            if t is not None:
                return (f'<a class="{cls}{tag_cls}" href="{esc(url_at(base, t))}" target="_blank" rel="noopener" '
                        f'title="{esc(title)} · {esc(fmt(t))}">{inner}</a>')
            return f'<div class="{cls}{tag_cls}">{inner}</div>'
        light = ''
        if lc:
            light = '<div class="run-card-light-cone">' + wrap(
                'rb-lc relative w-6 h-9 sm:w-9 sm:h-[3.1rem] rounded overflow-hidden bg-white/5 ring-1 ring-white/10 mt-0.5', '',
                img_tag('lc', lc, cls='object-cover') +
                f'<span class="rb-badge rb-s absolute bottom-0 right-0 text-[11px] font-bold px-1.5 leading-[15px] rounded-tl bg-black/85 text-purple-200">S{esc(s.get(f"p{i}_superimp", "?"))}</span>',
                t_lc, lc) + '</div>'
        slots.append('<div class="flex flex-col items-center gap-1 select-none rb-slot">' + wrap(
            'rb-char relative w-10 h-10 sm:w-14 sm:h-14 rounded-lg overflow-hidden bg-white/5 group', first,
            img_tag('char', c, cls='object-cover object-top') +
            f'<span class="rb-badge rb-e absolute bottom-0 right-0 text-[11px] font-bold px-1.5 leading-[15px] rounded-tl bg-black/85 text-blue-200">E{esc(s.get(f"p{i}_eidolon", "?"))}</span>',
            t_char, c) + light + '</div>')
    mode = str(s.get('mode') or '').upper()
    metric = s.get('metric_value')
    if isinstance(metric, float) and metric.is_integer():
        metric = int(metric)
    label = 'Score' if mode == 'AS' else 'Cycle'
    pills = [f'<span class="rb-verdict {badge}">{esc(verdict)} {esc(a.get("confidence", ""))}%</span>']
    if metric not in (None, ''):
        pills.append(f'<div class="theme-metric-pill theme-metric-pill-blue rb-pill inline-flex items-center gap-1 rounded-full border stat-number"><i class="theme-metric-pill-dot"></i>'
                     f'<b class="theme-metric-pill-label">{label}</b><span class="theme-metric-pill-value">{esc(metric)}</span></div>')
    for t in (s.get('subcategory'), s.get('boss_name'), mode):
        if t:
            pills.append(f'<span class="theme-run-subcategory-pill rb-sub-pill">{esc(t)}</span>')
    ltd, std = s.get('total_limited_5star_count'), s.get('total_standard_5star_count')
    counts = ''
    if ltd is not None:
        counts = (f'<div class="rb-end"><div class="rb-cnt rb-ltd stat-number"><b>Ltd</b><span>{esc(ltd)}</span></div>'
                  f'<div class="rb-cnt stat-number"><b>Std</b><span>{esc(std if std is not None else 0)}</span></div></div>')
    why = [('rb-bad', x) for x in (a.get('problems') or [])[:6]] + [('rb-chk', x) for x in (a.get('check_reasons') or [])[:6]]
    reasons = ''.join(f'<ul class="rb-why {c}"><li>{tm.reason(t)}</li></ul>' for c, t in why)
    links = [f'<a class="rb-process" href="{SITE}/mod?review={esc(e["rev"])}" target="_blank" rel="noopener" title="사이트에서 이 기록 처리하기">Process on site ↗</a>']
    if video:
        links.append(f'<a class="rb-link" href="{esc(video)}" target="_blank" rel="noopener">Video ↗</a>')
    b = tm.battle()
    if b:
        links.append('<span class="rb-link">Battle ' + tm.link(b[0], vid=e['battle_vid']) + ' – ' + tm.link(b[1], vid=e['battle_vid']) + '</span>')
    sc = tm.showcase()
    if sc is not None:
        links.append('<span class="rb-link">Showcase ' + tm.link(sc) + '</span>')
    note = f' <span class="rb-gcount">({e["runs"]} runs in one item)</span>' if e['runs'] > 1 else ''
    who = esc(s.get('author_name') or e['rev'])
    name = (f'<a class="rb-name text-sm font-semibold leading-tight truncate text-white" href="{esc(video)}" target="_blank" rel="noopener">{who}</a>'
            if video else f'<span class="rb-name">{who}</span>')
    meta = (f'<a class="rb-meta stat-number text-white/25 text-[11px]" href="{esc(video)}" target="_blank" rel="noopener">{platform(video)} {esc(when(s.get("video_date")))}</a>'
            if video else f'<span class="rb-meta">{esc(when(s.get("video_date")))}</span>')
    return (f'<div id="run-card-{esc(e["rev"])}" class="theme-run-card rb-card relative rounded-xl border overflow-hidden {border}">'
            f'<div class="rb-row p-1.5 sm:p-2 flex gap-1.5 sm:gap-2.5"><div class="rb-team flex gap-1 sm:gap-1.5 shrink-0">{"".join(slots)}</div>'
            f'<div class="rb-mid flex-1 min-w-0 flex flex-col justify-center gap-0.5 sm:gap-1">'
            f'<div class="rb-line flex items-center gap-x-1 sm:gap-x-1.5 min-w-0">{name}{note}{meta}</div>'
            f'<div class="rb-pills flex items-center gap-2 min-w-0">{"".join(pills)}{counts}</div>'
            f'{reasons}<div class="rb-links">{"".join(links)}</div></div></div></div>')


def page(entries, title='Review summary', seconds=None):
    # 사이트 스타일시트(ui_theme/site.css)를 먼저, 그 뒤에 이 파일의 스타일을 붙인다: 사이트 CSS 는 사이트가 쓰는 클래스만 들어 있어(Tailwind 가
    # 안 쓰는 클래스를 뺀다) 요약 전용 클래스(rb-*)는 따로 필요하다. 같은 것을 가리키면 뒤에 오는 이 스타일이 이긴다
    css = (open(THEME, encoding='utf8').read() + '\n' if os.path.exists(THEME) else '') + LITE_CSS
    groups = {v: [e for e in entries if e['auto'].get('verdict') == v] for v in ORDER}
    other = [e for e in entries if e['auto'].get('verdict') not in ORDER]
    if other:
        groups['CHECK'] += other
    stats = ''.join(f'<span class="rb-verdict {VERDICT_LOOK[v][1]}">{v} {len(groups[v])}</span>' for v in ORDER)
    body = []
    for v in ORDER:
        if not groups[v]:
            continue
        rows = sorted(groups[v], key=lambda e: (e['auto'].get('confidence') or 0, e['rev']))
        body.append(f'<div class="flex flex-col gap-1 rounded-xl border border-white/8 bg-white/[0.025] overflow-hidden rb-group">'
                    f'<div class="rb-ghead px-2.5 py-1 sm:px-4 sm:py-2 border-b border-white/8 flex items-center gap-1 sm:gap-2">'
                    f'<span class="theme-run-team-header-icon rb-gicon text-[10px] sm:text-sm">✦</span>'
                    f'<span class="theme-run-team-header-text text-[11px] sm:text-sm font-semibold">{v}</span>'
                    f'<span class="rb-gcount text-white/30 text-[9px] sm:text-xs">({len(rows)} entries)</span></div>'
                    f'<div class="rb-gbody flex flex-col gap-1 p-0.5">{"".join(card(e) for e in rows)}</div></div>')
    took = f' · {seconds / 60:.1f} min' if seconds else ''
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">'
            f'<style>{css}</style></head><body><main class="rb-wrap">'
            f'<div><div class="rb-title">{esc(title)}</div><div class="rb-sub">{len(entries)} records · {esc(datetime.now().strftime("%Y-%m-%d %H:%M"))}{esc(took)}</div></div>'
            f'<div class="rb-stats">{stats}</div>{"".join(body)}</main></body></html>')


def write_summary(revs, out=None, seconds=None):
    entries = [e for e in (load(r) for r in revs) if e]
    if not entries:
        return None
    os.makedirs(WORK, exist_ok=True)
    out = out or os.path.join(WORK, f'summary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html')
    text = page(entries, seconds=seconds)
    open(out, 'w', encoding='utf8').write(text)
    open(os.path.join(WORK, 'summary_latest.html'), 'w', encoding='utf8').write(text)
    return out


if __name__ == '__main__':
    a = sys.argv[1:]
    out = a[a.index('--out') + 1] if '--out' in a else None
    revs = [x for x in a if x.startswith('rev_')]
    if not revs:
        revs = sorted(x for x in os.listdir(RUNS) if os.path.exists(os.path.join(RUNS, x, 'auto.json')))
    print(write_summary(revs, out))
