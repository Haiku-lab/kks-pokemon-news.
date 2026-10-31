"""Kuro Kitsune Shop — veille des annonces officielles JCC Pokémon FR/JP.
Dépendances : requests, beautifulsoup4. Exécution : python pokemon_news.py
Les dates non explicitement confirmées restent null. Ne remplace pas une date
existante par une date déduite de la publication de l'article.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUTPUT = Path('pokemon_news.json')
SOURCES = {
    'FR': 'https://www.pokemon.com/fr/actualites',
    'JP': 'https://www.pokemon-card.com/info/',
}
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; KKSNews/2.0; official-product-monitor)'}
TIMEOUT = 25
MAX_ARTICLES = {'FR': 30, 'JP': 35}
FR_MONTHS = {'janvier':1,'février':2,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'août':8,'aout':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12,'decembre':12}
FR_DATE = re.compile(r'\b(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(20\d{2})\b', re.I)
JP_DATE = re.compile(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日')
FR_RELEASE = re.compile(r'(?:sortira|sortiront|sortie(?:\s+officielle)?|disponible(?:s)?(?:\s+dès|\s+à partir du|\s+le)?|en vente(?:\s+dès|\s+le)?|date de sortie|commercialis[ée]s?\s+le)', re.I)
JP_RELEASE = re.compile(r'(?:発売日|販売日|発売|販売開始)')
FR_PRODUCT = re.compile(r'\b(?:JCC|cartes? Pokémon|boosters?|coffrets?|collection|extension|dresseur|deck|bo[iî]tes?|blisters?|produits?|Méga-Évolution)\b', re.I)
JP_PRODUCT = re.compile(r'(?:商品|発売|拡張パック|強化拡張パック|デッキ|ボックス|パック|グッズ|サプライ|シールド|ケース|プレイマット|ファイル)')
EXCLUDE_FR = re.compile(r'(?:Pokémon Pocket|JCC Pokémon Pocket|Pokémon GO|jeu vidéo|Championnats|tournoi|évènement|avant-première)', re.I)

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url):
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return BeautifulSoup(response.content, 'html.parser')


def iso_date(y, m, d):
    try:
        return datetime(int(y), int(m), int(d)).strftime('%Y-%m-%d')
    except ValueError:
        return None


def release_date(text, country):
    """Only accept dates near release wording, never generic article timestamps."""
    if country == 'FR':
        for match in FR_DATE.finditer(text):
            before = text[max(0, match.start()-135):match.start()]
            if FR_RELEASE.search(before):
                return iso_date(match.group(3), FR_MONTHS[match.group(2).lower()], match.group(1))
    else:
        for match in JP_DATE.finditer(text):
            before = text[max(0, match.start()-100):match.start()]
            after = text[match.end():match.end()+35]
            if JP_RELEASE.search(before) or JP_RELEASE.search(after):
                return iso_date(match.group(1), match.group(2), match.group(3))
        # e.g. 「11月27日（金）に発売！」: year must be corroborated on page.
        partial = re.search(r'(\d{1,2})月\s*(\d{1,2})日(?:（[^）]*）)?\s*に発売', text)
        years = re.findall(r'20\d{2}年', text)
        if partial and years:
            return iso_date(years[0][:4], partial.group(1), partial.group(2))
    return None


def classify(title, country):
    checks = [('ETB',r'ETB|Coffret Dresseur|Elite Trainer'),('Display',r'display|boîte de boosters|ボックス'),('Booster',r'boosters?|拡張パック|パック'),('Deck',r'decks?|デッキ'),('Coffret',r'coffrets?|collections?|セット|BOX'),('Accessoire',r'accessoires?|スリーブ|シールド|ケース|プレイマット|ファイル')]
    for label, pattern in checks:
        if re.search(pattern, title, re.I):
            return label
    return 'Produit JCC'


def candidates(soup, country, base):
    seen = set()
    for a in soup.select('a[href]'):
        href = urljoin(base, a.get('href', ''))
        host = urlparse(href).netloc.lower()
        title = ' '.join(a.stripped_strings)
        if not title or href in seen:
            continue
        if country == 'FR':
            if host not in ('www.pokemon.com', 'pokemon.com') or '/fr/actualites/' not in urlparse(href).path:
                continue
            if not FR_PRODUCT.search(title) or EXCLUDE_FR.search(title):
                continue
        else:
            if host not in ('www.pokemon-card.com', 'pokemon-card.com'):
                continue
            if not re.search(r'/(?:info/\d+|products/|ex/)', urlparse(href).path):
                continue
            if not JP_PRODUCT.search(title):
                continue
            # Prefer product announcements, not event notices.
            if any(x in title for x in ('イベント','チャンピオンズリーグ','シティリーグ')):
                continue
        seen.add(href)
        yield title[:220], href


def existing_items():
    if not OUTPUT.exists():
        return {}
    try:
        data = json.loads(OUTPUT.read_text(encoding='utf-8'))
        return {x['url']: x for x in data.get('items', []) if x.get('url')}
    except (ValueError, OSError, KeyError, TypeError):
        return {}


def main():
    previous = existing_items()
    merged = dict(previous)
    successes = []
    errors = {}
    for country, source in SOURCES.items():
        try:
            soup = fetch(source)
            links = list(candidates(soup, country, source))[:MAX_ARTICLES[country]]
            successes.append(country)
            print(f'{country}: {len(links)} annonces candidates')
        except requests.RequestException as exc:
            errors[country] = str(exc)
            print(f'{country}: impossible de consulter la source : {exc}')
            continue
        for title, url in links:
            previous_item = merged.get(url, {})
            date = previous_item.get('release_date')
            try:
                article = fetch(url)
                # Main article text; avoid footer dates and unrelated sidebars.
                main_content = article.select_one('main, article, .news-detail, .contents') or article
                content = main_content.get_text(' ', strip=True)
                found = release_date(content, country)
                if found:
                    date = found
            except requests.RequestException as exc:
                print(f'  Article inaccessible : {url} ({exc})')
            merged[url] = {
                'country': country,
                'title': title,
                'url': url,
                'type': classify(title, country),
                'release_date': date,
                'status': 'date_confirmee_sur_source' if date else 'date_non_confirmee',
                'source': 'Pokémon officiel FR' if country == 'FR' else 'Pokémon Card officiel JP',
            }
    if not successes:
        raise RuntimeError('Aucune source officielle accessible : fichier conservé, mise à jour annulée.')
    data = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'sources_ok': successes,
        'source_errors': errors,
        'items': sorted(merged.values(), key=lambda x: (x.get('release_date') is None, x.get('release_date') or '9999-12-31', x['country'], x['title'])),
    }
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    confirmed = sum(bool(x.get('release_date')) for x in data['items'])
    print(f"{len(data['items'])} fiches enregistrées, {confirmed} dates confirmées dans les pages consultées.")
    print('Les fiches sans date restent à vérifier. Une annonce ne vaut pas toujours fiche produit.')


if __name__ == '__main__':
    main()
