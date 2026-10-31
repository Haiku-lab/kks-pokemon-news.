"""KKS — prochaines sorties officielles JCC Pokémon FR/JP.
Dépendances: requests beautifulsoup4. Compatible avec pokemon_news.json de KKS V19.
Une date n'est retenue que si le texte la lie explicitement à une mise en vente.
"""
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUTPUT = Path('pokemon_news.json')
SOURCES = {
    'FR': ['https://www.pokemon.com/fr/actualites'],
    'JP': ['https://www.pokemon-card.com/info/'],
}
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; KKSNews/3.0)'}
FR_MONTHS = {'janvier':1,'février':2,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'août':8,'aout':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12,'decembre':12}
FR_DATE = re.compile(r'\b(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(20\d{2})\b', re.I)
JP_DATE = re.compile(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日')
JP_SHORT = re.compile(r'(\d{1,2})月\s*(\d{1,2})日(?:\s*[（(][^）)]{0,8}[）)])?')
FR_SALE = re.compile(r'(?:disponible(?:s)?\s+(?:dès|à partir du|le)|(?:sortira|sortiront|sortie prévue|date de sortie)\s*(?:le|:)?|(?:en vente|commercialis[ée]s?)\s+(?:dès|le|à partir du))\s*', re.I)
JP_SALE = re.compile(r'(?:発売日\s*[：:]?\s*|(?:が|を|は|より|から|に)?\s*(?:発売|販売開始)(?:予定)?\s*[！!。]?)')
FR_PRODUCT = re.compile(r'(?:JCC Pokémon|cartes Pokémon|extension|boosters?|display|coffret|collection|deck|dresseur d’élite|dresseur d\'élite|ETB|blister|Méga-Évolution)', re.I)
JP_PRODUCT = re.compile(r'(?:商品|発売|拡張パック|強化拡張パック|スターターセット|デッキ|スペシャルセット|ボックス|パック|ハイクラスパック|コレクション|プレミアムトレーナーボックス)')
EXCLUDE = re.compile(r'(?:大会|イベント|リーグ|キャンペーン|抽選|当選|再販|販売終了|お詫び|交換|訂正|ランキング|プレイヤーズクラブ|ポケポケ|ポケモンカードゲーム ポケット|tournoi|championnat|événement|concours|Pocket|Pokémon GO|jeu vidéo|avant-première)', re.I)
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def soup_for(url):
    response = SESSION.get(url, timeout=25)
    response.raise_for_status()
    return BeautifulSoup(response.content, 'html.parser')


def valid_date(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def release_date(text, country):
    """Dates près de 'disponible/sortie' ou '発売', pas les horodatages d'article."""
    text = re.sub(r'\s+', ' ', text)
    if country == 'FR':
        for match in FR_DATE.finditer(text):
            context = text[max(0, match.start()-75):match.start()]
            if FR_SALE.search(context):
                found = valid_date(match.group(3), FR_MONTHS[match.group(2).lower()], match.group(1))
                if found:
                    return found
    else:
        # Japanese announcement: year can be implicit in a headline; require a dated
        # article (article metadata), and a sale word near the short date.
        for match in JP_DATE.finditer(text):
            context = text[max(0, match.start()-35):match.end()+45]
            if JP_SALE.search(context):
                found = valid_date(*match.groups())
                if found:
                    return found
    return None


def jp_headline_date(title, article):
    """Only infer year when the official article has a publication timestamp.
    Reject old dates and ambiguous year changes.
    """
    if not JP_SALE.search(title):
        return None
    match = JP_SHORT.search(title)
    if not match:
        return None
    meta = article.select_one('meta[property="article:published_time"], meta[name="date"], time[datetime]')
    stamp = (meta.get('content') or meta.get('datetime') or '') if meta else ''
    year_match = re.search(r'(20\d{2})', stamp)
    if not year_match:
        # Some official headlines explicitly include the year.
        year_match = re.search(r'(20\d{2})[.年/\-]', title)
    if not year_match:
        return None
    year = int(year_match.group(1))
    result = valid_date(year, match.group(1), match.group(2))
    if result and result < date.today() and result.month <= 2 and date.today().month >= 11:
        result = valid_date(year+1, match.group(1), match.group(2))
    return result


def image_url(soup, page_url):
    for selector, attr in [('meta[property="og:image"]','content'),('meta[name="twitter:image"]','content')]:
        element = soup.select_one(selector)
        if element and element.get(attr):
            result = urljoin(page_url, element[attr])
            if urlparse(result).scheme == 'https':
                return result
    return None


def classify(title):
    patterns = [('ETB',r'ETB|Dresseur d’élite|Dresseur d\'élite|Elite Trainer'),('Display',r'display|boîte de boosters|ボックス'),('Deck',r'decks?|デッキ'),('Booster',r'boosters?|拡張パック|ハイクラスパック'),('Coffret',r'coffrets?|collections?|セット|BOX')]
    for kind, pattern in patterns:
        if re.search(pattern, title, re.I):
            return kind
    return 'Produit JCC'


def links_from(soup, country, base):
    seen = set()
    for link in soup.select('a[href]'):
        url = urljoin(base, link['href']).split('#')[0]
        path = urlparse(url).path
        host = urlparse(url).hostname or ''
        title = ' '.join(link.stripped_strings).strip()
        if not title or url in seen or EXCLUDE.search(title):
            continue
        if country == 'FR':
            if host not in ('www.pokemon.com','pokemon.com') or '/fr/actualites/' not in path or not FR_PRODUCT.search(title):
                continue
        else:
            if host not in ('www.pokemon-card.com','pokemon-card.com') or not re.search(r'/(?:info/\d+|products/|ex/)',path) or not JP_PRODUCT.search(title):
                continue
        seen.add(url)
        yield title[:250], url


def main():
    today = datetime.now(timezone.utc).date()
    output = []
    errors = {}
    successes = []
    seen = set()
    for country, sources in SOURCES.items():
        for source in sources:
            try:
                listing = soup_for(source)
                successes.append(country)
            except requests.RequestException as exc:
                errors[source] = str(exc)
                continue
            for title, url in list(links_from(listing, country, source))[:80]:
                if url in seen:
                    continue
                seen.add(url)
                try:
                    article = soup_for(url)
                except requests.RequestException:
                    continue
                main = article.select_one('article, main, .news-detail, .contents') or article
                body = main.get_text(' ', strip=True)
                # A date in an article is not automatically a product release date.
                found = release_date(body[:7000], country)
                if not found and country == 'JP':
                    found = jp_headline_date(title, article)
                if not found or found < today or found > date(today.year+3,12,31):
                    continue
                if EXCLUDE.search(title):
                    continue
                output.append({
                    'country':country, 'title':title, 'url':url,
                    'type':classify(title), 'release_date':found.isoformat(),
                    'status':'date_extraite_a_verifier',
                    'source':'Pokémon officiel FR' if country=='FR' else 'Pokémon Card officiel JP',
                    'image':image_url(article,url),
                    'image_url':image_url(article,url),
                })
    if not successes:
        raise RuntimeError('Aucune source accessible. Ancien JSON conservé.')
    data = {'updated_at':datetime.now(timezone.utc).isoformat(),
            'sources_ok':sorted(set(successes)), 'source_errors':errors,
            'items':sorted(output,key=lambda x:(x['release_date'],x['country'],x['title']))}
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(output)} sorties futures candidates, FR={sum(x["country"]=="FR" for x in output)}, JP={sum(x["country"]=="JP" for x in output)}')
    print('Dates extraites automatiquement : vérifier la page officielle avant achat.')

if __name__ == '__main__':
    main()
