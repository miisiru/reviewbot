// 캐릭터별 성혼 이름 6개를 13개 언어로 → tools/eidolon_names.json
// 성혼 화면 머리글이 워터마크에 덮여도 성혼 이름(「空白，在诗篇的起点」)으로 누구 화면인지 안다.
// 자료: Dimbreath TurnBasedGameData(정식 판) 의 ExcelOutput(AvatarConfig · AvatarRankConfig) + TextMap(XXH64 열쇠)
// node tools/build_eidolon_names.mjs   (HSR_EXCEL · HSR_TEXTMAP 으로 폴더를 바꿀 수 있다. 기본 data/ExcelOutput · data/TextMap)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const EX = process.env.HSR_EXCEL || path.join(ROOT, 'data', 'ExcelOutput');
const TM = process.env.HSR_TEXTMAP || path.join(ROOT, 'data', 'TextMap');

// XXH64(시드 0): 「AvatarRankName_100101」 같은 평문 열쇠를 TextMap 열쇠로 바꾼다
const xxh64 = (text) => {
  const data = Buffer.from(text, 'utf-8');
  const M = (1n << 64n) - 1n;
  const P1 = 11400714785074694791n; const P2 = 14029467366897019727n;
  const P3 = 1609587929392839161n; const P4 = 9650029242287828579n;
  const P5 = 2870177450012600261n;
  const rotl = (x, r) => ((x << r) | (x >> (64n - r))) & M;
  const u64 = (off) => data.readBigUInt64LE(off);
  const u32 = (off) => BigInt(data.readUInt32LE(off));
  const n = data.length;
  let i = 0;
  let h;
  if (n >= 32) {
    let v1 = (P1 + P2) & M; let v2 = P2; let v3 = 0n; let v4 = (0n - P1) & M;
    const round = (v, off) => ((rotl((v + u64(off) * P2) & M, 31n)) * P1) & M;
    while (i <= n - 32) {
      v1 = round(v1, i); v2 = round(v2, i + 8); v3 = round(v3, i + 16); v4 = round(v4, i + 24);
      i += 32;
    }
    h = (rotl(v1, 1n) + rotl(v2, 7n) + rotl(v3, 12n) + rotl(v4, 18n)) & M;
    for (const v of [v1, v2, v3, v4]) {
      let k = (v * P2) & M; k = rotl(k, 31n); k = (k * P1) & M;
      h = ((h ^ k) * P1 + P4) & M;
    }
  } else {
    h = P5;
  }
  h = (h + BigInt(n)) & M;
  while (i <= n - 8) {
    let k = (u64(i) * P2) & M; k = rotl(k, 31n); k = (k * P1) & M;
    h ^= k; h = (rotl(h, 27n) * P1 + P4) & M; i += 8;
  }
  if (i <= n - 4) {
    h ^= (u32(i) * P1) & M; h = (rotl(h, 23n) * P2 + P3) & M; i += 4;
  }
  while (i < n) {
    h ^= (BigInt(data[i]) * P5) & M; h = (rotl(h, 11n) * P1) & M; i += 1;
  }
  h ^= h >> 33n; h = (h * P2) & M;
  h ^= h >> 29n; h = (h * P3) & M;
  h ^= h >> 32n;
  return h.toString();
};
const LANGS = ['EN', 'CHS', 'CHT', 'KR', 'JP', 'VI', 'TH', 'RU', 'ES', 'PT', 'FR', 'DE', 'ID'];
const clean = (s) => String(s || '').replace(/<[^>]+>|\{RUBY_[BE]#[^}]*\}/g, '').replace(/\u00a0/g, ' ').trim();

const load = (l) => {
  const out = {};
  for (const f of fs.readdirSync(TM)) {
    if (new RegExp(`^TextMap(Main)?${l}(_\\d)?\\.json$`).test(f)) Object.assign(out, JSON.parse(fs.readFileSync(path.join(TM, f), 'utf8')));
  }
  return out;
};
const rd = (f) => JSON.parse(fs.readFileSync(path.join(EX, f), "utf8").replace(/"Hash": *(-?\d+)/g, (_, n) => `"Hash": "${n}"`));    // 64비트 해시는 글로 읽는다
const avatars = rd('AvatarConfig.json');
const ranks = Object.fromEntries(rd('AvatarRankConfig.json').map((r) => [r.RankID, r]));
const maps = Object.fromEntries(LANGS.map((l) => [l, load(l)]));

const out = {};
for (const a of avatars) {
  // 개척자(8001~)는 이름이 플레이어 이름이라 제출 이름 「Trailblazer (길)」로
  const PATH = { Warrior: 'Destruction', Knight: 'Preservation', Shaman: 'Harmony', Memory: 'Remembrance', Elation: 'Elation' };
  const en = a.AvatarID >= 8000 ? `Trailblazer (${PATH[a.AvatarBaseType]})` : clean(maps.EN[String(a.AvatarName.Hash)]);
  if (!en || en === 'N/A') continue;
  const per = {};
  for (const l of LANGS) {
    per[l] = (a.RankIDList || []).map((id) => clean(maps[l][xxh64(ranks[id]?.Name || '')] || ''));
  }
  if (!per.EN.some(Boolean)) continue;
  // 같은 EN 이름(개척자 남녀 · 길 여럿)은 길마다 다르므로 아이디로도 남긴다
  out[`${en}#${a.AvatarID}`] = per;
}
fs.writeFileSync(new URL('./eidolon_names.json', import.meta.url), JSON.stringify(out, null, 0));
console.log(Object.keys(out).length, 'avatars');
console.log(JSON.stringify(Object.entries(out).find(([k]) => k.startsWith('Cyrene'))));
