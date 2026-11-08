from math import asin, atan2, cos, degrees, radians, sin, sqrt

EARTH_RADIUS_NM = 3440.065


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * asin(sqrt(a))


def heading_change(a: float, b: float) -> float:
    """Signed smallest change from heading a to b, in (-180, 180]."""
    return (b - a + 180) % 360 - 180


def altitude(sample: dict) -> int | None:
    """Barometric altitude in ft, None when on the ground or unknown."""
    alt = sample.get("alt_baro")
    return alt if isinstance(alt, (int, float)) else None


def on_ground(sample: dict) -> bool:
    return sample.get("alt_baro") == "ground"


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, 0-360."""
    p1, p2, dlon = radians(lat1), radians(lat2), radians(lon2 - lon1)
    y = sin(dlon) * cos(p2)
    x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dlon)
    return degrees(atan2(y, x)) % 360


def mean_heading(headings: list[float]) -> float:
    """Circular mean, so that 350 and 10 average to 0, not 180."""
    s = sum(sin(radians(h)) for h in headings)
    c = sum(cos(radians(h)) for h in headings)
    return degrees(atan2(s, c)) % 360


def nearest_airport(sample: dict, airports: list[dict]) -> tuple[dict, float]:
    """(airport, distance_nm) of the airport closest to the sample's position."""
    return min(
        ((a, distance_nm(a["lat"], a["lon"], sample["lat"], sample["lon"])) for a in airports),
        key=lambda x: x[1],
    )
