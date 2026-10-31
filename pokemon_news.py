"""KKS - sorties futures officielles FR/JP (version 4).

Lance avec: python pokemon_news.py
Dépendances: requests, beautifulsoup4 (workflow GitHub existant).
Les dates proviennent de phrases de commercialisation; jamais de la date de publication.
"""
import json
import re
import unicodedata
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

OUT = Path('pokemon_news.json')
SOURCES = {
 'FR': ['https://www.pokemon.com/fr/actualites', 'https://pokemon.gamespress.com/fr/'],
 'JP': ['https://www.pokemon-card.com/info/'],
}
# Cette annonce officielle constitue un contrôle de régression : Règne Delta, 6 nov. 2026.
SEEDS = {'FR': ['https://pokemon.gamespress.com/fr/AVIS-MEDIAS-la-nouvelle-extension-du-Jeu-de-Cartes-a-Collectionn-71882'], 'JP': []}
S = requests.Session()
S.headers.update({'User-Agent':'Mozilla/5.0 (compatible; KKSReleaseCalendar/4.0)'})
MONTHS = {'janvier':1,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'aout':8,'septembre':9,'octobre':10,'novembre':11,'decembre':12}
FR_DATE = re.compile(r'\b(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+(20\d{2})\b', re.I)
JP_DATE = re.compile(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日')
JP_SHORT = re.compile(r'(\d{1,2})月\s*(\d{1,2})日')
FR_SALE = re.compile(r'(?:sortir(?:a|ont)|sortie\s+(?:officielle|pr[eé]vue)|date de sortie|disponible(?:s)?|commercialis[eé]|en vente|mis(?:e)?s? en vente|sera(?:ont)? lanc[eé]s?|d[eé]barque(?:nt)?|sera(?:ont)? propos[eé]s?)',re.I)
JP_SALE = re.compile(r'(?:発売|販売開始|発売日)')
FR_TOPIC = re.compile(r'(?:JCC\s*Pok[eé]mon|jeu de cartes|cartes\s+[àa]\s+collectionner|m[eé]ga[- ]?[eé]volution|extension|coffret|booster|deck|dresseur d.[eé]lite)',re.I)
JP_TOPIC = re.compile(r'(?:商品|発売|拡張パック|強化拡張パック|デッキ|セット|ボックス|ハイクラスパック)')
BAD = re.compile(r'(?:Pok[eé]mon Pocket|Pok[eé]mon GO|jeu vid[eé]o|tournoi|championnat|concours|ポケポケ|大会|キャンペーン|再販|お詫び|抽選)',re.I)
GENERIC_IMAGE = re.compile(r'(?:/assets/images/og\.png|/logo|placeholder|default)',re.I)

def get(url):
 r=S.get(url,timeout=25); r.raise_for_status(); return BeautifulSoup(r.content,'html.parser')

def norm(s):
 return ''.join(c for c in unicodedata.normalize('NFD',s.lower()) if unicodedata.category(c)!='Mn')

def make_date(y,m,d):
 try:return date(int(y),int(m),int(d))
 except ValueError:return None

def fr_dates(body):
 # Découpage par phrase, pour éviter d'attribuer la date d'un événement au produit.
 for sentence in re.split(r'(?<=[.!?。])\s+|\n+',body):
  if not FR_SALE.search(sentence):continue
  for m in FR_DATE.finditer(sentence):
   before=sentence[max(0,m.start()-140):m.start()]
   after=sentence[m.end():m.end()+90]
   if not FR_SALE.search(before) and not re.search(r'(?:date de sortie|sortie officielle)',after,re.I):continue
   result=make_date(m.group(3),MONTHS[norm(m.group(2))],m.group(1))
   if result:yield result

def jp_dates(body, headline, page):
 for m in JP_DATE.finditer(body):
  around=body[max(0,m.start()-65):m.end()+65]
  if JP_SALE.search(around):
   result=make_date(*m.groups())
   if result:yield result
 # Les titres japonais utilisent souvent mois/jour avec année de publication.
 if not JP_SALE.search(headline):return
 match=JP_SHORT.search(headline)
 if not match:return
 year=re.search(r'20\d{2}',headline)
 if not year:
  tag=page.select_one('meta[property="article:published_time"],meta[name="date"],time[datetime]')
  year=re.search(r'20\d{2}',str(tag)) if tag else None
 if not year:return
 result=make_date(year.group(),match.group(1),match.group(2))
 if result:yield result

def photo(page,url):
 for selector,attribute in [('meta[property="og:image"]','content'),('meta[name="twitter:image"]','content')]:
  tag=page.select_one(selector)
  if tag and tag.get(attribute):
   link=urljoin(url,tag[attribute])
   if link.startswith('https://') and not GENERIC_IMAGE.search(link):return link
 return None

def classify(title):
 for kind,pat in [('ETB',r'ETB|dresseur d.[eé]lite|elite trainer'),('Display',r'display|bo[iî]te de boosters'),('Deck',r'deck|デッキ'),('Booster',r'booster|拡張パック|ハイクラスパック'),('Coffret',r'coffret|collection|セット|box')]:
  if re.search(pat,title,re.I):return kind
 return 'Produit JCC'

def candidates(page,base,country):
 for a in page.select('a[href]'):
  title=a.get_text(' ',strip=True)
  url=urljoin(base,a['href']).split('#')[0]
  host=urlparse(url).hostname or ''
  path=urlparse(url).path
  if not title or len(title)<14 or BAD.search(title):continue
  if country=='FR':
   if host in ('pokemon.com','www.pokemon.com') and '/fr/actualites/' in path and FR_TOPIC.search(title):yield title,url
   elif host=='pokemon.gamespress.com' and '/fr/' in path and FR_TOPIC.search(title):yield title,url
  else:
   if host in ('pokemon-card.com','www.pokemon-card.com') and re.search(r'/(?:info/\d+|products/|ex/)',path) and JP_TOPIC.search(title):yield title,url

def main():
 today=datetime.now(timezone.utc).date()
 results={};errors={};ok=set();visited=set()
 for country,urls in SOURCES.items():
  links=[('',u) for u in SEEDS[country]]
  for source in urls:
   try:
    page=get(source);ok.add(country)
    links.extend(list(candidates(page,source,country))[:120])
   except requests.RequestException as e:errors[source]=str(e)
  for hinted_title,url in links:
   if url in visited:continue
   visited.add(url)
   try:page=get(url)
   except requests.RequestException:continue
   main_area=page.select_one('article,main,.news-detail,.contents') or page
   body=main_area.get_text(' ',strip=True)
   title_tag=page.select_one('h1')
   title=(title_tag.get_text(' ',strip=True) if title_tag else hinted_title).strip() or hinted_title
   if BAD.search(title) or (country=='FR' and not FR_TOPIC.search(title+' '+body[:350])):continue
   if country=='JP' and not JP_TOPIC.search(title+' '+body[:350]):continue
   dates=fr_dates(body[:16000]) if country=='FR' else jp_dates(body[:16000],title+' '+hinted_title,page)
   future=sorted(set(d for d in dates if today<=d<=date(today.year+3,12,31)))
   if not future:continue
   # Une fiche par annonce : première date future explicitement mentionnée.
   released=future[0]
   img=photo(page,url)
   results[url]={'country':country,'title':title[:260],'url':url,'type':classify(title),'release_date':released.isoformat(),'status':'date_extraite_a_verifier','source':'Pokémon officiel FR' if country=='FR' else 'Pokémon Card officiel JP','image':img,'image_url':img}
 if not ok:raise RuntimeError('Toutes les sources sont indisponibles : ancien fichier préservé')
 # En cas d'échec d'une source, conserver ses fiches futures précédentes.
 if OUT.exists():
  try:
   old=json.loads(OUT.read_text(encoding='utf-8'))
   for item in old.get('items',[]):
    if item.get('country') not in ok and item.get('release_date','')>=today.isoformat():results.setdefault(item['url'],item)
  except (OSError,ValueError,TypeError):pass
 items=sorted(results.values(),key=lambda i:(i['release_date'],i['country'],i['title']))
 OUT.write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat(),'sources_ok':sorted(ok),'source_errors':errors,'items':items},ensure_ascii=False,indent=2),encoding='utf-8')
 print(f'KKS: {len(items)} sorties; FR={sum(i["country"]=="FR" for i in items)}, JP={sum(i["country"]=="JP" for i in items)}')
 print('Dates candidates issues de phrases de vente : vérification officielle recommandée.')

if __name__=='__main__':main()
