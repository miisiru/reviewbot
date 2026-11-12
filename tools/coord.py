"""여러 대가 같은 대기열을 검토할 때 서로 겹치지 않게 하는 약속(한 대에서 여러 건을 돌릴 때도 같은 규칙).

서버의 「검토 중」 표시가 잠금이다. 다만 두 쪽이 거의 동시에 걸 수 있으므로(표시는 키마다 따로 걸리고 거는 쪽이 거부당하지 않는다) 이렇게 한다.
  1. 같은 컴퓨터: work/locks/<rev>.lock 파일 잠금(프로세스가 죽으면 풀림). 두 번 띄운 run_queue 가 같은 건을 잡지 않는다.
  2. 표시를 건다(영상을 받기 전에). 응답이 404 면 이미 결정되어 사라진 건 → 포기.
  3. 응답의 claimed_by_name 이 내 이름이 아니면 남이 잡은 건 → 내 표시를 풀고 포기.
  4. 1.5~3.5초 무작위로 기다렸다 다시 건다. 그 사이 다른 쪽이 걸었으면 이름이 바뀌어 보이므로 둘 다 물러난다(서로 포기해도 건은 남으니 나중에 다시 잡힌다).
  5. 판정하는 동안 4분마다 다시 건다(ttl 최대 10분). 다시 걸 때 404 거나 남의 이름이 보이면 「잃음」으로 적어 둔다.
  6. 승인 · 거절을 보내기 직전에 한 번 더 확인한다(ok()). 잃었거나 사라졌으면 결정을 보내지 않는다. 결정이 먼저 나 있으면 서버가 404 로 막는다.
같은 키를 두 컴퓨터가 함께 쓰면 이름이 같아 서로를 못 알아본다(키는 컴퓨터마다 따로 받는다: 봇 문서 「One key per bot or machine」).
그런 경우에는 config.json 의 "shard": "0/2" (이 컴퓨터는 0번, 모두 2대) 또는 run_queue --shard 0/2 로 건 아이디 해시로 몫을 나눈다 — 한 건은 항상 한 컴퓨터만 맡으므로 겹치지 않는다."""
import os, sys, time, random, hashlib, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORK, config   # noqa: E402
import mod_api                    # noqa: E402

LOCKS = os.path.join(WORK, 'locks')
RENEW = 240          # 초: 봇 표시 ttl(최대 600)보다 한참 짧게


def in_shard(rev, spec):
    """spec = 'i/n' (예 '0/2'). 없으면 모두 내 몫. 건 아이디 해시로 정하므로 컴퓨터끼리 따로 정해도 같은 결과."""
    if not spec:
        return True
    try:
        i, n = (int(x) for x in str(spec).split('/'))
    except ValueError:
        raise SystemExit(f'shard 는 「0/2」 꼴이다: {spec!r}')
    return int(hashlib.sha1(rev.encode()).hexdigest()[:8], 16) % n == i


NAME_FILE = os.path.join(WORK, 'bot_name.txt')


def my_name():
    """이 키가 카드에 보이는 이름(「<키 이름> (bot)」). config.json 의 bot_name, 아니면 처음 알아낸 것을 적어 둔 파일."""
    if config().get('bot_name'):
        return config()['bot_name']
    try:
        return open(NAME_FILE, encoding='utf8').read().strip() or None
    except OSError:
        return None


def learn_name(name):
    os.makedirs(WORK, exist_ok=True)
    open(NAME_FILE, 'w', encoding='utf8').write(name)
    return name


def names_of(s):
    """claimed_by_name 은 건 사람이 여럿이면 「a (bot), b (bot)」 꼴로 이어 붙어 온다(서버 실측)."""
    return {x.strip() for x in (s or '').split(', ') if x.strip()}


def _holder(resp):
    """claim 응답에서 (잡은 이름, 사라짐 여부). 세션 방식 등 모양이 다르면 (None, False)."""
    rv = (resp or {}).get('review') if isinstance(resp, dict) else None
    return (rv.get('claimed_by_name') if isinstance(rv, dict) else None), False


def _claim(rev, ttl):
    """(응답, 사라짐). 404(이미 결정됨)는 사라짐으로 돌려준다 — mod_api.call 이 SystemExit 로 내므로 여기서 잡는다."""
    try:
        return mod_api.claim(rev, ttl), False
    except SystemExit as e:
        if 'HTTP 404' in str(e):
            return None, True
        raise


class Lease:
    def __init__(self, rev, enabled=True):
        self.rev, self.enabled = rev, enabled
        self.me = None
        self.lost = False
        self.stop = threading.Event()
        self.thread = None
        self.fh = None

    # --- 같은 컴퓨터 잠금 ---
    def _lock_file(self):
        os.makedirs(LOCKS, exist_ok=True)
        path = os.path.join(LOCKS, self.rev + '.lock')
        fh = open(path, 'a+')
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self.fh = fh
        return True

    def acquire(self, listed_free=True):
        """잡았으면 True. 남이 잡았거나 사라졌으면 False(이유는 self.why). listed_free: 받아 둔 대기열에서 아무도 안 잡은 건이었는가."""
        self.why = None
        self.me = my_name()
        if not self._lock_file():
            self.why = 'another process on this machine is working on it'
            return False
        if not self.enabled:
            return True
        resp, gone = _claim(self.rev, 600)
        if gone:
            return self._fail('already decided or gone')
        name, _ = _holder(resp)
        if self.me is None and name is not None and listed_free and len(names_of(name)) == 1:
            self.me = learn_name(name)          # 아무도 안 잡은 건에 내가 걸었으니 보이는 이름이 내 이름
        if name is not None and (self.me is None or names_of(name) - {self.me}):
            return self._fail(f'claimed by {name}')
        time.sleep(random.uniform(1.5, 3.5))
        resp, gone = _claim(self.rev, 600)
        if gone:
            return self._fail('already decided or gone')
        name, _ = _holder(resp)
        if name is not None and names_of(name) - {self.me}:
            return self._fail(f'claimed by {name}')
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True

    def _fail(self, why):
        self.why = why
        self.release()
        return False

    def _loop(self):
        while not self.stop.wait(RENEW):
            self.ok(quiet=True)

    def ok(self, quiet=False):
        """아직 내 건인가(다시 걸어 보며 확인). 아니면 lost 로 적고 False."""
        self.me = self.me or my_name()
        if not self.enabled:
            return True
        if self.lost:
            return False
        try:
            resp, gone = _claim(self.rev, 600)
        except SystemExit as e:        # 네트워크 · 서버 오류는 잃은 것으로 치지 않는다(다음에 다시)
            if not quiet:
                print(f'{self.rev}: claim refresh failed: {e}', flush=True)
            return True
        name, _ = _holder(resp)
        if gone or (name is not None and self.me is not None and names_of(name) - {self.me}):
            self.lost = True
            self.why = 'already decided or gone' if gone else f'claimed by {name}'
            return False
        return True

    def release(self):
        self.stop.set()
        if self.enabled and not self.lost:
            try:
                mod_api.release(self.rev)
            except SystemExit:
                pass
        if self.fh:
            try:
                self.fh.close()
            except OSError:
                pass
            self.fh = None
