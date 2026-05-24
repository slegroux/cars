"""Haversine distance + offline LA-area zip/city coordinate lookup."""
from __future__ import annotations

import math

# (lat, lon) for common SoCal zip codes
_ZIP_COORDS: dict[str, tuple[float, float]] = {
    # Santa Monica
    "90401": (34.0118, -118.4910),
    "90402": (34.0341, -118.4952),
    "90403": (34.0262, -118.4928),
    "90404": (34.0236, -118.4729),
    "90405": (34.0025, -118.4751),
    # West LA / Westside
    "90025": (34.0432, -118.4465),  # West LA
    "90034": (34.0241, -118.4007),  # Palms
    "90035": (34.0536, -118.3803),  # Mid-City
    "90049": (34.0700, -118.4703),  # Brentwood
    "90064": (34.0340, -118.4313),  # West LA
    "90066": (33.9977, -118.4290),  # Mar Vista
    "90291": (33.9924, -118.4691),  # Venice
    "90292": (33.9826, -118.4406),  # Marina del Rey
    "90272": (34.0460, -118.5264),  # Pacific Palisades
    # Beverly Hills / Culver City
    "90210": (34.0901, -118.4065),  # Beverly Hills
    "90211": (34.0742, -118.3951),
    "90212": (34.0620, -118.3966),
    "90230": (34.0108, -118.3962),  # Culver City
    "90232": (34.0257, -118.3921),
    # South Bay
    "90245": (33.9164, -118.4165),  # El Segundo
    "90254": (33.8648, -118.3987),  # Hermosa Beach
    "90266": (33.8845, -118.3978),  # Manhattan Beach
    "90277": (33.8453, -118.3887),  # Redondo Beach
    "90278": (33.8659, -118.3701),
    "90501": (33.8346, -118.3290),  # Torrance
    "90502": (33.8277, -118.3052),
    "90503": (33.8340, -118.3603),
    "90504": (33.8671, -118.3453),
    "90505": (33.8117, -118.3600),
    # Inglewood / Hawthorne / Lawndale
    "90301": (33.9598, -118.3526),  # Inglewood
    "90302": (33.9743, -118.3549),
    "90303": (33.9440, -118.3448),
    "90250": (33.9161, -118.3451),  # Hawthorne
    "90260": (33.8879, -118.3523),  # Lawndale
    # Compton / Gardena / Carson
    "90220": (33.8958, -118.2196),  # Compton
    "90247": (33.8915, -118.3068),  # Gardena
    "90746": (33.8534, -118.2630),  # Carson
    # Long Beach
    "90802": (33.7701, -118.1937),
    "90803": (33.7614, -118.1401),
    "90804": (33.7887, -118.1664),
    "90805": (33.8650, -118.1711),
    "90806": (33.7960, -118.1897),
    # Downtown LA / Hollywood
    "90001": (33.9731, -118.2479),
    "90002": (33.9496, -118.2463),
    "90010": (34.0620, -118.3108),
    "90012": (34.0561, -118.2390),  # Downtown
    "90015": (34.0353, -118.2686),
    "90017": (34.0511, -118.2688),
    "90028": (34.1019, -118.3267),  # Hollywood
    "90029": (34.0893, -118.3008),
    "90038": (34.0882, -118.3388),
    "90046": (34.1070, -118.3676),  # West Hollywood
    "90069": (34.0905, -118.3806),  # West Hollywood
    # Koreatown / Silver Lake / Los Feliz / Echo Park
    "90004": (34.0746, -118.3027),
    "90005": (34.0576, -118.3019),
    "90026": (34.0776, -118.2607),  # Echo Park
    "90027": (34.1092, -118.2971),  # Los Feliz
    "90039": (34.1153, -118.2618),  # Atwater Village
    # Burbank / Glendale / Pasadena
    "91501": (34.1895, -118.3118),  # Burbank
    "91502": (34.1725, -118.3162),
    "91505": (34.1795, -118.3528),
    "91201": (34.1670, -118.2560),  # Glendale
    "91202": (34.1713, -118.2762),
    "91203": (34.1476, -118.2557),
    "91101": (34.1478, -118.1445),  # Pasadena
    "91103": (34.1648, -118.1564),
    "91104": (34.1607, -118.1129),
    "91105": (34.1378, -118.1622),
    # San Fernando Valley
    "91316": (34.1847, -118.5340),  # Encino
    "91335": (34.2006, -118.5476),  # Reseda
    "91340": (34.2856, -118.4323),  # San Fernando
    "91343": (34.2411, -118.4828),  # North Hills
    "91344": (34.2723, -118.4952),  # Granada Hills
    "91345": (34.2565, -118.4542),  # Mission Hills
    "91352": (34.2292, -118.3888),  # Sun Valley
    "91356": (34.1740, -118.5623),  # Tarzana
    "91364": (34.1776, -118.5924),  # Woodland Hills
    "91367": (34.1810, -118.6167),
    "91401": (34.1871, -118.4006),  # Van Nuys
    "91402": (34.2158, -118.4096),
    "91403": (34.1582, -118.4629),  # Sherman Oaks
    "91405": (34.2079, -118.4349),
    "91406": (34.2079, -118.4724),
    "91411": (34.1793, -118.4461),  # Sherman Oaks
    "91423": (34.1522, -118.4198),  # Sherman Oaks
    "91436": (34.1516, -118.4783),  # Encino
    "91601": (34.1747, -118.3765),  # North Hollywood
    "91602": (34.1705, -118.3994),
    "91604": (34.1668, -118.4149),  # Studio City
    "91605": (34.2076, -118.3906),
    "91606": (34.1881, -118.3862),
    "91607": (34.1666, -118.3991),  # Valley Village
    # Canoga Park / Chatsworth / Northridge / Reseda
    "91303": (34.2011, -118.5984),  # Canoga Park
    "91304": (34.2322, -118.6002),
    "91306": (34.2185, -118.5702),  # Winnetka
    "91307": (34.2019, -118.6298),
    "91311": (34.2574, -118.6026),  # Chatsworth
    "91324": (34.2313, -118.5410),  # Northridge
    "91325": (34.2435, -118.5147),
    "91326": (34.2659, -118.5370),
    "91330": (34.2413, -118.5290),
    # East LA / Boyle Heights / Commerce
    "90022": (34.0233, -118.1565),  # East LA
    "90023": (34.0250, -118.2014),
    "90063": (34.0510, -118.1852),
    "90040": (33.9989, -118.1540),  # Commerce
    # Oxnard / Ventura County
    "93030": (34.1975, -119.1771),  # Oxnard
    "93033": (34.1681, -119.1505),
    "93036": (34.2372, -119.1705),
    # Buena Park / Orange County border
    "90620": (33.8688, -117.9981),  # Buena Park
    "90621": (33.8879, -117.9940),
    "92841": (33.7742, -117.9920),  # Garden Grove
}

# City name → (lat, lon) for Craigslist free-text location strings
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "santa monica": (34.0195, -118.4912),
    "venice": (33.9924, -118.4691),
    "marina del rey": (33.9826, -118.4406),
    "pacific palisades": (34.0460, -118.5264),
    "brentwood": (34.0700, -118.4703),
    "west la": (34.0432, -118.4465),
    "west los angeles": (34.0432, -118.4465),
    "culver city": (34.0108, -118.3962),
    "mar vista": (33.9977, -118.4290),
    "inglewood": (33.9598, -118.3526),
    "hawthorne": (33.9161, -118.3451),
    "el segundo": (33.9164, -118.4165),
    "manhattan beach": (33.8845, -118.3978),
    "hermosa beach": (33.8648, -118.3987),
    "redondo beach": (33.8453, -118.3887),
    "torrance": (33.8346, -118.3290),
    "gardena": (33.8915, -118.3068),
    "carson": (33.8534, -118.2630),
    "compton": (33.8958, -118.2196),
    "lawndale": (33.8879, -118.3523),
    "beverly hills": (34.0901, -118.4065),
    "west hollywood": (34.0905, -118.3806),
    "los angeles": (34.0522, -118.2437),
    "la": (34.0522, -118.2437),
    "downtown la": (34.0561, -118.2390),
    "downtown": (34.0561, -118.2390),
    "hollywood": (34.1019, -118.3267),
    "silver lake": (34.0893, -118.2700),
    "silverlake": (34.0893, -118.2700),
    "los feliz": (34.1092, -118.2971),
    "echo park": (34.0776, -118.2607),
    "atwater village": (34.1153, -118.2618),
    "koreatown": (34.0576, -118.3019),
    "mid-city": (34.0536, -118.3803),
    "palms": (34.0241, -118.4007),
    "burbank": (34.1895, -118.3118),
    "glendale": (34.1476, -118.2557),
    "pasadena": (34.1478, -118.1445),
    "arcadia": (34.1397, -118.0353),
    "monrovia": (34.1470, -117.9995),
    "el monte": (34.0686, -118.0276),
    "alhambra": (34.0953, -118.1270),
    "san gabriel": (34.0961, -118.1058),
    "temple city": (34.1063, -118.0580),
    "san fernando valley": (34.2000, -118.4500),
    "valley village": (34.1666, -118.3991),
    "north hollywood": (34.1747, -118.3765),
    "studio city": (34.1668, -118.4149),
    "sherman oaks": (34.1522, -118.4198),
    "van nuys": (34.1871, -118.4006),
    "encino": (34.1847, -118.5340),
    "tarzana": (34.1740, -118.5623),
    "woodland hills": (34.1776, -118.5924),
    "reseda": (34.2006, -118.5476),
    "northridge": (34.2313, -118.5410),
    "canoga park": (34.2011, -118.5984),
    "chatsworth": (34.2574, -118.6026),
    "winnetka": (34.2185, -118.5702),
    "granada hills": (34.2723, -118.4952),
    "mission hills": (34.2565, -118.4542),
    "sun valley": (34.2292, -118.3888),
    "san fernando": (34.2856, -118.4323),
    "oxnard": (34.1975, -119.1771),
    "ventura": (34.2747, -119.2290),
    "thousand oaks": (34.1706, -118.8376),
    "camarillo": (34.2164, -119.0376),
    "simi valley": (34.2694, -118.7815),
    "buena park": (33.8688, -117.9981),
    "long beach": (33.7701, -118.1937),
    "compton ca": (33.8958, -118.2196),
}

# Default home coordinates (Santa Monica 90405)
_SANTA_MONICA = (34.0195, -118.4912)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two lat/lon points."""
    r = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def home_coords(zip_code: str) -> tuple[float, float]:
    """Return (lat, lon) for the given zip code, defaulting to Santa Monica."""
    return _ZIP_COORDS.get(zip_code.strip(), _SANTA_MONICA)


def distance_from_location(location: str | None, home_zip: str) -> float | None:
    """Compute distance in miles from a location string to the home zip.

    Accepts either a zip code string or a city name (case-insensitive).
    Returns None if the location cannot be resolved.
    """
    if not location:
        return None

    loc = location.strip()

    # Try as a zip code first (5-digit number)
    if loc.isdigit() and len(loc) == 5:
        coords = _ZIP_COORDS.get(loc)
        if coords:
            hlat, hlon = home_coords(home_zip)
            return round(haversine_miles(hlat, hlon, *coords), 1)
        return None

    # Try city name lookup (normalise: lowercase, strip trailing state ", CA")
    city = loc.lower()
    for suffix in (", ca", ", california"):
        if city.endswith(suffix):
            city = city[: -len(suffix)].strip()
            break

    coords = _CITY_COORDS.get(city)
    if coords:
        hlat, hlon = home_coords(home_zip)
        return round(haversine_miles(hlat, hlon, *coords), 1)

    return None
