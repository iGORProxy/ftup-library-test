"""Новини для вкладки «Новини»: свіжі статті з журналів і баз за фільтром дитячої ФТ (власник 26.11.2026).
Джерела й фільтр — data/news-sources.json. Результат — data/news.json (застосунок вбудовує його при збиранні, app/build.mjs).
Мережа: Europe PMC REST (журнали за ISSN, пошукові запити) і RSS напряму. Повних текстів не копіюємо — лише назва, журнал, дата, посилання.
Наявні записи зберігаються (дата першої появи), старші за `days` відкидаються.
Запуск: python3 -I tools/news_fetch.py   (щодня/щотижня; далі — npm run build і деплой за командою власника)
Тестова копія (GitHub Action у ftup-library-test, щодня; власник 26.11.2026): NEWS_CFG=… NEWS_LIB=data/library.json —
тоді новини читаються з поля `news` готового library.json і записуються туди ж, а відбиток lib-ver в index.html поруч оновлюється."""
import json, os, re, sys, time, datetime, urllib.request, urllib.parse, xml.etree.ElementTree as ET, html

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
CFG = json.load(open(os.environ.get('NEWS_CFG') or os.path.join(DATA, 'news-sources.json'), encoding='utf-8'))
OUT = os.path.join(DATA, 'news.json')
LIB = os.environ.get('NEWS_LIB')   # шлях до зібраного data/library.json (режим Action)
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
TODAY = datetime.date.today()
SINCE = TODAY - datetime.timedelta(days=CFG['days'])
CHILD, MOTOR, EXCL = (re.compile(CFG[k], re.I) for k in ('child', 'motor', 'exclude'))
MOTOR_T = re.compile(CFG['motor_title'], re.I)
TAGS = [(t, re.compile(rx, re.I)) for t, rx in CFG['tags']]
log = lambda *a: print(*a, file=sys.stderr)


def get(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception as e:   # Europe PMC подеколи віддає порожню відповідь — повторити
            if k == tries - 1: log('  не вдалося:', url[:100], type(e).__name__, e)
            time.sleep(2 + 3 * k)
    return b''


def epmc(query):
    """Усі результати запиту за період (сторінками по 200, курсором)."""
    q = f'({query}) AND FIRST_PDATE:[{SINCE} TO {TODAY}]'
    cursor, out = '*', []
    while True:
        u = EPMC + '?' + urllib.parse.urlencode({'query': q, 'format': 'json', 'pageSize': 200, 'resultType': 'core', 'cursorMark': cursor})
        raw = get(u)
        try: d = json.loads(raw)
        except ValueError: break
        res = d.get('resultList', {}).get('result', [])
        out += res
        nxt = d.get('nextCursorMark')
        if not res or not nxt or nxt == cursor or len(out) >= 1000: break
        cursor = nxt
    return out


def from_epmc(r, src):
    doi, pmcid, pmid = r.get('doi'), r.get('pmcid'), r.get('pmid')
    url = ('https://doi.org/' + doi) if doi else ('https://europepmc.org/article/PMC/' + pmcid) if pmcid else ('https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/') if pmid else ''
    types = ' '.join((r.get('pubTypeList') or {}).get('pubType', [])).lower()
    j = (r.get('journalInfo') or {}).get('journal', {}).get('title') or r.get('journalTitle') or src
    au = r.get('authorString') or ''
    au = (au.split(',')[0] + (' et al.' if ',' in au else '')).strip().rstrip('.') + ('.' if au and ',' in au else '')
    return {
        't': html.unescape(re.sub(r'<[^>]+>', '', r.get('title') or '')).strip().rstrip('.'),
        'ab': re.sub(r'<[^>]+>', ' ', r.get('abstractText') or ''),
        'j': src or j, 'd': (r.get('firstPublicationDate') or '')[:10], 'u': url,
        'oa': r.get('isOpenAccess') == 'Y', 'au': au,
        'k': 'настанова' if 'guideline' in types else 'огляд' if ('review' in types or 'systematic review' in (r.get('title') or '').lower()) else '',
        'id': (doi or pmcid or pmid or url).lower(),
    }


def from_rss(raw, src):
    out = []
    try: root = ET.fromstring(raw)
    except ET.ParseError: return out
    for it in root.iter():
        if it.tag.split('}')[-1] not in ('item', 'entry'): continue
        f = {c.tag.split('}')[-1]: (c.text or c.get('href') or '') for c in it}
        d = f.get('pubDate') or f.get('date') or f.get('published') or f.get('updated') or ''
        try: dd = datetime.datetime.strptime(d[:16].strip(), '%a, %d %b %Y').date().isoformat()
        except ValueError: dd = d[:10] if re.match(r'\d{4}-\d\d-\d\d', d) else TODAY.isoformat()
        desc = html.unescape(re.sub(r'<[^>]+>', ' ', f.get('description') or f.get('summary') or ''))
        m = re.search(r'Publication date:\s*([A-Z][a-z]+ \d{4}|\d+ [A-Z][a-z]+ \d{4})', desc)   # ScienceDirect: дата в описі
        if m:
            for fmt in ('%d %B %Y', '%B %Y'):
                try: dd = datetime.datetime.strptime(m.group(1), fmt).date().isoformat(); break
                except ValueError: pass
        link = f.get('link') or ''
        out.append({'t': html.unescape(f.get('title') or '').strip().rstrip('.'), 'ab': desc, 'j': src, 'd': dd, 'u': link,
                    'oa': False, 'au': '', 'k': '', 'id': link.lower()})
    return out


def keep(x, level):
    text = x['t'] + ' ' + x['ab']
    if not x['t'] or EXCL.search(text): return False
    if level == 'pt': return True
    if level == 'peds': return bool(MOTOR_T.search(x['t']))   # у загальнодитячих журналах — лише коли про рух/ФТ сказано в назві
    if level == 'rehab': return bool(CHILD.search(x['t']) or (CHILD.search(text) and len(CHILD.findall(text)) >= 2))
    return bool(CHILD.search(text) and MOTOR.search(text))   # query


MM = 'https://api.mymemory.translated.net/get'
BUDGET = [4500]   # безкоштовний MyMemory без ключа — ~5000 знаків на день з однієї адреси; решта — наступного запуску
def term_fix(t):
    """Терміни ФТуП: «ЦП», «передчасно народжені» (виняток — «ретинопатія недоношених»)."""
    t = re.sub(r'(?i)(дитяч\w* )?церебральн\w* паралі\w*', 'ЦП', t)
    t = re.sub(r'(?i)(ретинопаті\w*) недоношених', r'\1 НЕДОНОШ', t)
    t = re.sub(r'недоношен(\w*)', r'передчасно народжен\1', t).replace('Недоношен', 'Передчасно народжен')
    return t.replace('НЕДОНОШ', 'недоношених')
def translate(t):
    """Назва українською (машинний переклад для орієнтації; в застосунку позначено «переклад»)."""
    if BUDGET[0] < len(t): return ''
    try:
        d = json.loads(get(MM + '?' + urllib.parse.urlencode({'q': t[:480], 'langpair': 'en|uk'}), tries=2) or b'{}')
    except ValueError: return ''
    if d.get('quotaFinished') or d.get('responseStatus') != 200: BUDGET[0] = 0; return ''
    BUDGET[0] -= len(t)
    u = html.unescape((d.get('responseData') or {}).get('translatedText') or '').strip()
    return term_fix(u) if u and u.upper() != u else ''


def norm_title(t): return re.sub(r'[^a-z0-9]+', ' ', t.lower()).strip()


def main():
    old = {}
    prev = (json.load(open(LIB, encoding='utf-8')).get('news') or {}) if LIB else json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    for x in prev.get('items', []): old[x['id']] = x
    got, stat = [], []
    for s in CFG['journals']:
        res = [from_epmc(r, s['name']) for r in epmc(f'ISSN:"{s["issn"]}"')]
        ok = [x for x in res if keep(x, s['level'])]
        stat.append((s['name'], len(res), len(ok))); got += ok
        log(f"{s['name']}: {len(res)} → {len(ok)}")
    for s in CFG['queries']:
        res = [from_epmc(r, '') for r in epmc(s['query'])]
        ok = [x for x in res if keep(x, s['level'])]
        stat.append((s['name'], len(res), len(ok))); got += ok
        log(f"{s['name']}: {len(res)} → {len(ok)}")
    for s in CFG.get('rss', []):
        res = [x for x in from_rss(get(s['url']), s['name']) if x['d'] >= SINCE.isoformat()]
        ok = [x for x in res if keep(x, s['level'])]
        stat.append((s['name'], len(res), len(ok))); got += ok
        log(f"{s['name']} (RSS): {len(res)} → {len(ok)}")
    items, seen_t = {}, set()
    for x in got:
        nt = norm_title(x['t'])
        if x['id'] in items or nt in seen_t: continue
        seen_t.add(nt)
        text = x['t'] + ' ' + x['ab']
        x['tg'] = [t for t, rx in TAGS if rx.search(x['t'])][:3] or [t for t, rx in TAGS if len(rx.findall(x['ab'])) >= 2][:2]   # спершу за назвою
        x['seen'] = old.get(x['id'], {}).get('seen') or TODAY.isoformat()
        x['tu'] = old.get(x['id'], {}).get('tu') or ''
        x.pop('ab')
        items[x['id']] = x
    # те, що вже показували, але цього разу джерело не віддало (збій мережі), — лишається до кінця періоду
    for i, x in old.items():
        if i not in items and x['d'] >= SINCE.isoformat() and norm_title(x['t']) not in seen_t: items[i] = x
    lst = sorted(items.values(), key=lambda x: (x['d'], x['seen']), reverse=True)[:CFG['max']]
    for x in lst:   # переклад назв — спершу найсвіжіші; що не вмістилось у денний ліміт — наступного разу
        if not x.get('tu'): x['tu'] = translate(x['t'])
    log('перекладено назв:', sum(1 for x in lst if x.get('tu')), 'з', len(lst))
    news = {'built': TODAY.isoformat(), 'days': CFG['days'], 'sources': [{'n': n, 'all': a, 'kept': k} for n, a, k in stat], 'items': lst}
    if sum(k for _, _, k in stat) == 0 and old:   # усі джерела мовчать — збій мережі, нічого не міняти
        sys.exit('жодне джерело не відповіло — новини не оновлено')
    if LIB:
        lib = json.load(open(LIB, encoding='utf-8')); lib['news'] = news
        raw = json.dumps(lib, ensure_ascii=False, separators=(',', ':'))
        open(LIB, 'w', encoding='utf-8').write(raw)
        import hashlib
        idx = os.path.join(os.path.dirname(os.path.abspath(LIB)), '..', 'index.html')   # той самий відбиток, що й у app/build.mjs
        h = open(idx, encoding='utf-8').read()
        open(idx, 'w', encoding='utf-8').write(re.sub(r'(<meta name="lib-ver" content=")[0-9a-f]+', lambda m: m.group(1) + hashlib.sha1(raw.encode()).hexdigest()[:8], h))
    else:
        json.dump(news, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'{LIB or "data/news.json"}: {len(lst)} новин за {CFG["days"]} днів (з {len(got)} відібраних)')


if __name__ == '__main__':
    main()
