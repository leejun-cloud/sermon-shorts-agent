from dataclasses import dataclass, asdict, field
from typing import List, Dict


@dataclass
class Segment:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Highlight:
    start: float
    end: float
    score: float = 0.0
    peak_db: float = 0.0


@dataclass
class Candidate:
    rank: int
    start: float
    end: float
    score: float
    category: str
    title: str
    summary: str
    hook: str
    transcript: str
    reasons: List[str]
    hashtags: List[str]
    segments: List[Segment]
    score_breakdown: List[str] = field(default_factory=list)
    match_summary: str = ''
    recommendation_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['segments'] = [asdict(s) for s in self.segments]
        return data
