// 브라우저 개발자 도구 콘솔에 붙여 넣는 스크립트: 지금 보고 있는 페이지(예: https://theherta.com/archive)의 HTML · CSS · JS · 글꼴 · CSS 변수와
// 기록 카드 · 묶음 머리글의 계산된 스타일을 theherta-ui-dump.json 하나로 내려받는다(쿠키 · localStorage 는 읽지 않는다).
// 받은 파일로 `python tools/extract_ui_theme.py <theherta-ui-dump.json>` 을 돌리면 data/ui_theme/site.css 가 만들어진다.
// 로그인한 상태의 HTML 이라 계정 이름 · 아바타 주소가 들어 있을 수 있으니 남에게 보내기 전에 열어 볼 것.
(async () => {
  const INCLUDE_JS = true;                 // false 로 바꾸면 JS 는 주소만 저장
  const out = { url: location.href, when: new Date().toISOString(),
                viewport: [innerWidth, innerHeight, devicePixelRatio], ua: navigator.userAgent };
  const get = async (u) => {
    try { const r = await fetch(u, { credentials: 'same-origin' });
          return { url: u, status: r.status, text: await r.text() }; }
    catch (e) { return { url: u, error: String(e) }; }
  };

  // 1) HTML (렌더링이 끝난 현재 DOM)
  out.html = document.documentElement.outerHTML;

  // 2) CSS: 링크 · 인라인 · adoptedStyleSheets
  const css = [];
  for (const l of document.querySelectorAll('link[rel~=stylesheet]')) css.push(await get(l.href));
  document.querySelectorAll('style').forEach((s, i) => css.push({ url: 'inline-style-' + i, text: s.textContent }));
  (document.adoptedStyleSheets || []).forEach((s, i) => {
    try { css.push({ url: 'adopted-' + i, text: [...s.cssRules].map(r => r.cssText).join('\n') }); } catch (e) {}
  });
  out.css = css;

  // 3) JS
  const js = [];
  for (const s of document.querySelectorAll('script')) {
    if (s.src) js.push(INCLUDE_JS ? await get(s.src) : { url: s.src });
    else js.push({ url: 'inline', text: s.textContent.slice(0, 200000) });
  }
  out.js = js;
  out.modulepreload = [...document.querySelectorAll('link[rel=modulepreload]')].map(l => l.href);

  // 4) 글꼴과 :root 의 CSS 변수
  out.fonts = [...document.fonts].map(f => ({ family: f.family, weight: f.weight, style: f.style, status: f.status }));
  const vars = {};
  for (const sh of document.styleSheets) {
    let rules; try { rules = sh.cssRules; } catch (e) { continue; }
    for (const r of rules) {
      if (r.selectorText && /(^|,)\s*(:root|html|body)\b/.test(r.selectorText))
        for (const p of r.style) if (p.startsWith('--')) vars[p] = r.style.getPropertyValue(p).trim();
    }
  }
  out.rootVars = vars;

  // 5) 카드 · 묶음 머리글의 실제 모양(계산된 스타일)
  const PROPS = ['display','position','flexDirection','alignItems','justifyContent','gap','gridTemplateColumns',
    'width','height','minWidth','padding','margin','color','backgroundColor','backgroundImage','border','borderRadius',
    'boxShadow','opacity','fontFamily','fontSize','fontWeight','letterSpacing','lineHeight','textTransform',
    'backdropFilter','filter','overflow','cursor','transition','outline'];
  const dump = (el, limit = 300) => {
    const arr = []; const walk = (n, depth) => {
      if (arr.length >= limit || depth > 8) return;
      const cs = getComputedStyle(n), st = {};
      for (const p of PROPS) st[p] = cs[p];
      arr.push({ tag: n.tagName, cls: n.className && n.className.toString(), text: (n.children.length ? '' : n.textContent.trim().slice(0, 40)),
                 rect: (b => [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)])(n.getBoundingClientRect()), style: st });
      for (const c of n.children) walk(c, depth + 1);
    };
    walk(el, 0); return arr;
  };
  const smallest = (re) => {
    let best = null;
    for (const el of document.body.querySelectorAll('*')) {
      const t = el.innerText || '';
      if (t.length < 600 && re.test(t) && (!best || t.length < best.innerText.length)) best = el;
    }
    return best;
  };
  // Elements 탭에서 기록 카드를 하나 선택해 두면($0) 그 카드를 쓰고, 아니면 LTD · STD 가 든 가장 작은 블록
  let card = (typeof $0 !== 'undefined' && $0) || smallest(/LTD[\s\S]*STD/);
  if (card && !/LTD/.test(card.innerText || '')) card = card.closest('[class]') || card;
  if (card) { out.card = { html: card.outerHTML.slice(0, 60000), nodes: dump(card) }; }
  const head = smallest(/\(\d+\s+entries\)/i);
  if (head) { const h = head.closest('[class]') || head; out.groupHeader = { html: h.outerHTML.slice(0, 30000), nodes: dump(h, 120) }; }
  out.body = { bg: getComputedStyle(document.body).background, font: getComputedStyle(document.body).fontFamily };

  // 6) 저장
  const blob = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'theherta-ui-dump.json'; a.click();
  console.log('저장:', 'theherta-ui-dump.json', (blob.size / 1e6).toFixed(1) + 'MB',
              'css', css.length, 'js', js.length, 'card', !!card, 'groupHeader', !!head);
})();
