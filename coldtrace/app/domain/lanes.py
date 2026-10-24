"""Freight lanes between REAL markets that appear in the bundled Agmarknet snapshot.

Coordinates are city/market-level (accurate to a few km) - good for weather sampling and map display,
not for turn-by-turn navigation. Road geometry is fetched from OSRM at start-up; if OSRM is
unreachable the waypoint polyline below is used (flagged as route_source='waypoints').
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Lane:
    id: str
    name: str
    origin: Place
    dest: Place
    via: tuple[Place, ...] = ()
    origin_market: str | None = None    # exact Agmarknet market name
    origin_state: str | None = None
    commodities: tuple[str, ...] = ()
    shipper: str = "Farmer producer company"
    receiver: str = "Wholesale buyer"
    carrier: str = "Regional reefer carrier"

    @property
    def path(self) -> list[Place]:
        return [self.origin, *self.via, self.dest]


P = Place
LANES: list[Lane] = [
    Lane("JUN-PAN", "Junnar to Panvel (Mumbai)", P("Junnar (Alephata)", 19.2087, 73.8756), P("Panvel APMC", 18.9894, 73.1175),
         via=(P("Kalyan", 19.2437, 73.1355),), origin_market="Junnar(Alephata) APMC", origin_state="Maharashtra",
         commodities=("tomato", "onion", "green_chilli")),
    Lane("SAT-PUN", "Satara to Pune", P("Satara", 17.6805, 74.0183), P("Pune APMC (Gultekdi)", 18.4867, 73.8687),
         via=(P("Khed Shivapur", 18.3130, 73.9500),), origin_market="Satara APMC", origin_state="Maharashtra",
         commodities=("potato", "ginger", "brinjal")),
    Lane("BHU-PIM", "Bhusaval to Pune (Pimpri)", P("Bhusaval", 21.0450, 75.7850), P("Pune (Pimpri) APMC", 18.6298, 73.7997),
         via=(P("Jalgaon", 21.0077, 75.5626), P("Chh. Sambhajinagar", 19.8762, 75.3433), P("Ahilyanagar", 19.0952, 74.7496)),
         origin_market="Bhusaval APMC", origin_state="Maharashtra", commodities=("banana", "tomato", "brinjal")),
    Lane("SBN-MOS", "Chh. Sambhajinagar to Pune (Moshi)", P("Chh. Sambhajinagar", 19.8762, 75.3433), P("Pune (Moshi) APMC", 18.6768, 73.8438),
         via=(P("Ahilyanagar", 19.0952, 74.7496),), origin_market="Chattrapati Sambhajinagar APMC", origin_state="Maharashtra",
         commodities=("tomato", "potato", "okra")),
    Lane("UJJ-MOS", "Ujjain to Pune (Moshi), long haul", P("Ujjain", 23.1765, 75.7885), P("Pune (Moshi) APMC", 18.6768, 73.8438),
         via=(P("Indore", 22.7196, 75.8577), P("Dhule", 20.9042, 74.7749), P("Nashik", 19.9975, 73.7898)),
         origin_market="Ujjain(F&V) APMC", origin_state="Madhya Pradesh", commodities=("potato", "onion", "cauliflower")),
    Lane("HOS-CBE", "Hosur to Coimbatore", P("Hosur", 12.7409, 77.8253), P("RS Puram, Coimbatore", 11.0075, 76.9503),
         via=(P("Krishnagiri", 12.5186, 78.2138), P("Salem", 11.6643, 78.1460), P("Erode", 11.3410, 77.7172)),
         origin_market="Hosur(Uzhavar Sandhai )", origin_state="Tamil Nadu", commodities=("tomato", "carrot", "cabbage")),
    Lane("WGL-HYD", "Warangal to Hyderabad", P("Warangal", 17.9689, 79.5941), P("Mehdipatnam Rythu Bazar", 17.3950, 78.4400),
         via=(P("Jangaon", 17.7239, 79.1518),), origin_market="Warangal APMC", origin_state="Telangana",
         commodities=("green_chilli", "tomato", "okra")),
    Lane("PAL-PER", "Palakkad to Perumbavoor", P("Palakkad", 10.7867, 76.6548), P("Perumbavoor", 10.1140, 76.4780),
         via=(P("Thrissur", 10.5276, 76.2144),), origin_market="Palakkad Market", origin_state="Kerala",
         commodities=("banana", "bitter_gourd", "bottle_gourd")),
    Lane("PUN-HYD", "Pune to Hyderabad (biologics)", P("Pune", 18.5204, 73.8567), P("Hyderabad", 17.3850, 78.4867),
         via=(P("Solapur", 17.6599, 75.9064),), commodities=("biologics",),
         shipper="Pharma manufacturer", receiver="Hospital distributor", carrier="Pharma cold-chain carrier"),
]
LANE_BY_ID = {l.id: l for l in LANES}

# Diversion candidates. City-level positions; verified=False means "replace with your contracted facilities".
HUBS: list[Place] = [
    P("Nashik", 19.9975, 73.7898), P("Pune", 18.5204, 73.8567), P("Kalyan", 19.2437, 73.1355),
    P("Ahilyanagar", 19.0952, 74.7496), P("Chh. Sambhajinagar", 19.8762, 75.3433), P("Solapur", 17.6599, 75.9064),
    P("Dhule", 20.9042, 74.7749), P("Jalgaon", 21.0077, 75.5626), P("Indore", 22.7196, 75.8577),
    P("Krishnagiri", 12.5186, 78.2138), P("Salem", 11.6643, 78.1460), P("Erode", 11.3410, 77.7172),
    P("Coimbatore", 11.0168, 76.9558), P("Jangaon", 17.7239, 79.1518), P("Hyderabad", 17.3850, 78.4867),
    P("Thrissur", 10.5276, 76.2144), P("Satara", 17.6805, 74.0183), P("Mumbai (Vashi)", 19.0771, 72.9986),
]
