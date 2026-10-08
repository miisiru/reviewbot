"""경로와 실행 파일. 모든 도구가 여기서 가져간다. 환경 변수로 바꿀 수 있다.
  REVIEWBOT_ROOT  저장소 폴더(기본: 이 파일의 위 폴더)
  HSR_TEXTMAP     게임 TextMap 폴더(기본: <ROOT>/data/TextMap)
  FFMPEG          ffmpeg 실행 파일(기본: imageio-ffmpeg 가 가진 것, 없으면 PATH 의 ffmpeg)
  YTDLP           yt-dlp 실행 파일(기본: PATH 의 yt-dlp, 없으면 사용자 Python Scripts 폴더의 것)"""
import os, sys, shutil, sysconfig

ROOT = os.environ.get('REVIEWBOT_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, 'runs')          # 건마다 영상 · 중간 결과 · 판정
WORK = os.path.join(ROOT, 'work')          # 대기열 파일 등
CONFIG = os.path.join(ROOT, 'config.json')  # 웹후크 · 토큰(깃에 올리지 않는다)
TEXTMAP = os.environ.get('HSR_TEXTMAP') or os.path.join(ROOT, 'data', 'TextMap')
PY = sys.executable


def _ffmpeg():
    if os.environ.get('FFMPEG'):
        return os.environ['FFMPEG']
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which('ffmpeg') or 'ffmpeg'


def _ytdlp():
    if os.environ.get('YTDLP'):
        return os.environ['YTDLP']
    found = shutil.which('yt-dlp')
    if found:
        return found
    for scheme in (f'{os.name}_user', None):
        try:
            d = sysconfig.get_path('scripts', scheme) if scheme else sysconfig.get_path('scripts')
        except KeyError:
            continue
        for name in ('yt-dlp.exe', 'yt-dlp'):
            if d and os.path.exists(os.path.join(d, name)):
                return os.path.join(d, name)
    return 'yt-dlp'


FF = _ffmpeg()
YT = _ytdlp()


def config():
    import json
    return json.load(open(CONFIG, encoding='utf8')) if os.path.exists(CONFIG) else {}
