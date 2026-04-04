from dataclasses import dataclass


@dataclass(frozen=True)
class CandidatePoint:
    point_id: str
    country: str
    lat: float
    lon: float

