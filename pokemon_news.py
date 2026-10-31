
import json
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "FR": "https://www.pokemon.com/fr/actualites",
    "JP": "https://www.pokemon-card.com/info/"
}

results = []

for country, url in SOURCES.items():
    try:
        response = requests.get(
            url,
            timeout=25,
            headers={"User-Agent": "KKS-Pokemon-News/1.0"}
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for link in soup.select("a[href]"):
            title = link.get_text(" ", strip=True)
            href = urljoin(url, link["href"])

            if len(title) < 12:
                continue

            if country == "FR" and "/fr/" not in href:
                continue
            if country == "JP" and "pokemon-card.com" not in href:
                continue

            results.append({
                "country": country,
                "title": title,
                "url": href,
                "release_date": None,
                "status": "date_a_verifier"
            })
    except requests.RequestException as error:
        print(f"Erreur {country}: {error}")

unique = {item["url"]: item for item in results}

data = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "items": list(unique.values())
}

with open("pokemon_news.json", "w", encoding="utf-8") as file:
    json.dump(data, file, ensure_ascii=False, indent=2)

print(f"{len(unique)} liens récupérés.")
