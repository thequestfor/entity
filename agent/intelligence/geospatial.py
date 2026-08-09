"""Conservative, evidence-backed geographic reconciliation for situations."""

import json
import math
from collections import Counter

from agent.intelligence.store import utc_now


COUNTRY_CODES = {
    "US": "United States", "USA": "United States", "GB": "United Kingdom",
    "UK": "United Kingdom", "GBR": "United Kingdom", "UA": "Ukraine",
    "UKR": "Ukraine", "IL": "Israel", "ISR": "Israel", "IR": "Iran",
    "IRN": "Iran", "RU": "Russia", "RUS": "Russia", "CN": "China",
    "CHN": "China", "TW": "Taiwan", "TWN": "Taiwan", "SY": "Syria",
    "SYR": "Syria", "LB": "Lebanon", "LBN": "Lebanon", "PS": "Palestine",
    "PSN": "Palestine", "YE": "Yemen", "YEM": "Yemen", "SD": "Sudan",
    "SDN": "Sudan", "ET": "Ethiopia", "ETH": "Ethiopia", "SO": "Somalia",
    "SOM": "Somalia", "CD": "Democratic Republic of the Congo", "COD": "Democratic Republic of the Congo",
    "CG": "Republic of the Congo", "COG": "Republic of the Congo", "IN": "India",
    "IND": "India", "PK": "Pakistan", "PAK": "Pakistan", "AF": "Afghanistan",
    "AFG": "Afghanistan", "TR": "Türkiye", "TUR": "Türkiye", "DE": "Germany",
    "DEU": "Germany", "FR": "France", "FRA": "France", "JP": "Japan",
    "JPN": "Japan", "AU": "Australia", "AUS": "Australia", "CA": "Canada",
    "CAN": "Canada", "BR": "Brazil", "BRA": "Brazil", "MX": "Mexico",
    "MEX": "Mexico", "KR": "South Korea", "KOR": "South Korea", "KP": "North Korea",
    "PRK": "North Korea", "SA": "Saudi Arabia", "SAU": "Saudi Arabia", "EG": "Egypt",
    "EGY": "Egypt", "IQ": "Iraq", "IRQ": "Iraq", "JO": "Jordan", "JOR": "Jordan",
    "OM": "Oman", "OMN": "Oman", "AE": "United Arab Emirates",
    "ARE": "United Arab Emirates", "QA": "Qatar", "QAT": "Qatar",
    "BH": "Bahrain", "BHR": "Bahrain", "KW": "Kuwait", "KWT": "Kuwait",
    "AZ": "Azerbaijan", "AZE": "Azerbaijan", "AM": "Armenia", "ARM": "Armenia",
    "GE": "Georgia", "GEO": "Georgia", "LY": "Libya", "LBY": "Libya",
    "TN": "Tunisia", "TUN": "Tunisia", "DZ": "Algeria", "DZA": "Algeria",
    "MA": "Morocco", "MAR": "Morocco", "VE": "Venezuela", "VEN": "Venezuela",
    "CO": "Colombia", "COL": "Colombia", "MM": "Myanmar", "MMR": "Myanmar",
    "BD": "Bangladesh", "BGD": "Bangladesh", "TH": "Thailand", "THA": "Thailand",
    "PH": "Philippines", "PHL": "Philippines", "ID": "Indonesia", "IDN": "Indonesia",
}


def _number(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


def _distance_km(first, second):
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    a = math.sin((lat2-lat1)/2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2-lon1)/2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(a)))


def _country(value):
    text = str(value or "").strip()
    if not text:
        return "", ""
    normalized = COUNTRY_CODES.get(text.upper())
    if normalized:
        code = text.upper() if len(text) == 2 else ""
        return code, normalized
    # Country names are retained only when directly supplied by source metadata.
    return "", text[:120]


class SituationGeography:
    """Use a weighted medoid; never average points across a disputed border."""

    def reconcile(self, connection, situation_id):
        rows = connection.execute(
            """
            SELECT documents.latitude,documents.longitude,documents.metadata,
                   documents.retrieved_at,documents.published_at,
                   COALESCE(publisher_reputation.learned_credibility,sources.credibility) AS credibility
            FROM situation_documents
            JOIN documents ON documents.id=situation_documents.document_id
            JOIN sources ON sources.id=documents.source_id
            LEFT JOIN publisher_reputation ON publisher_reputation.publisher_key=documents.publisher_key
            WHERE situation_documents.situation_id=?
            """, (situation_id,)
        ).fetchall()
        points, countries, labels = [], [], []
        for row in rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            lat, lon = _number(row["latitude"], -90, 90), _number(row["longitude"], -180, 180)
            weight = max(.1, min(1., float(row["credibility"] or .5)))
            if lat is not None and lon is not None:
                points.append(((lat, lon), weight))
            raw_countries = metadata.get("countries") or metadata.get("country") or metadata.get("country_code") or metadata.get("affected_country")
            if not isinstance(raw_countries, (list, tuple)):
                raw_countries = [raw_countries]
            for value in raw_countries:
                code, name = _country(value)
                if name:
                    countries.append((code, name, weight))
            for key in ("locality", "place", "location_name", "city"):
                value = str(metadata.get(key) or "").strip()
                if value:
                    labels.append((value[:120], weight))
                    break
        # Structured claims preserve the source's country assertion even when
        # a connector did not retain it in document metadata.
        claim_rows = connection.execute(
            """SELECT object,confidence FROM claims WHERE situation_id=?
               AND predicate='event.affected_country' AND status!='superseded'""",
            (situation_id,)
        ).fetchall()
        for row in claim_rows:
            code, name = _country(row["object"])
            if name:
                countries.append((code, name, max(.1, float(row["confidence"] or .5))))
        if not points and not countries:
            # Mark the absence of geographic evidence so the resumable repair
            # can advance instead of repeatedly selecting the same records.
            connection.execute(
                """UPDATE situations SET location_method='no-geographic-evidence-v1',
                   location_updated_at=? WHERE id=?""",
                (utc_now(), situation_id)
            )
            return False
        chosen, spread = (None, 0.0)
        if points:
            chosen = min(points, key=lambda item: sum(_distance_km(item[0], other[0]) * other[1] for other in points))[0]
            spread = max((_distance_km(chosen, item[0]) for item in points), default=0.0)
        if countries:
            names = Counter(name for _, name, _ in countries)
            country_name = names.most_common(1)[0][0]
            country_code = next((code for code, name, _ in countries if name == country_name and code), "")
        else:
            country_name = country_code = ""
        label = Counter(value for value, _ in labels).most_common(1)
        label = label[0][0] if label else country_name
        evidence_count = len(points) + len(countries)
        confidence = min(.95, .35 + .1 * min(5, evidence_count) + (.2 if points and countries else 0) - (.25 if spread > 500 else 0))
        precision = max(5.0, min(1000.0, spread if len(points) > 1 else 100.0)) if points else None
        connection.execute(
            """UPDATE situations SET latitude=?,longitude=?,location_country_code=?,location_country_name=?,
              location_label=?,location_precision_km=?,location_confidence=?,location_evidence_count=?,
              location_disagreement_km=?,location_method=?,location_updated_at=? WHERE id=?""",
            (chosen[0] if chosen else None, chosen[1] if chosen else None, country_code, country_name,
             label, precision, round(confidence, 4), evidence_count, round(spread, 2),
             "evidence-weighted-medoid-v1" if chosen else "source-country-metadata-v1", utc_now(), situation_id)
        )
        return True

    def reconcile_batch(self, store, limit=50):
        """Resumable historical repair; one short transaction per worker cycle."""
        with store._connect() as connection:
            rows = connection.execute(
                """SELECT id FROM situations
                   WHERE location_updated_at IS NULL OR location_updated_at < updated_at
                   ORDER BY updated_at DESC LIMIT ?""", (max(1, min(500, int(limit))),)
            ).fetchall()
            for row in rows:
                self.reconcile(connection, row["id"])
        return len(rows)
