import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from historical_appearances_backfill import (
    PlayerCandidate,
    parse_lineups,
    resolve_player,
)


def test_parse_wrapped_historical_lineups():
    text = """= World Cup 1930

» Group stage - Group 1
Sun Jul/13 1930 @ Estadio Pocitos › Montevideo, Uruguay
  France v Mexico  4-1
    Lucien Laurent 19'

France: Alex Thépot, Marcel Capelle, Étienne Mattler, Alexandre Villaplane,
   Augustin Chantrel, Marcel Pinel, Edmond Delfour, Marcel Langiller,
   Lucien Laurent, Ernest Libérati, André Maschinot
Mexico: Oscar Bonfiglio, Rafael Garza Gutiérrez, Manuel Rosas,
   Efraín Amézcua, Felipe Rosas, Alfredo Viejo Sánchez, Juan Carreño,
   Hilario López, Dionisio Mejía, José Ruíz, Luis Pérez
"""

    rows = parse_lineups(text, 1930)

    assert len(rows) == 1
    assert rows[0].match_date == "1930-07-13"
    assert len(rows[0].lineups["France"]) == 11
    assert len(rows[0].lineups["Mexico"]) == 11


def test_parse_canonical_team_alias():
    text = """= World Cup 1958
Sun Jun/8 1958 @ Råsunda Stadium › Solna, Sweden
  Argentina v West Germany  1-3
Argentina: A One, A Two, A Three, A Four, A Five, A Six, A Seven, A Eight, A Nine, A Ten, A Eleven
West Germany: B One, B Two, B Three, B Four, B Five, B Six, B Seven, B Eight, B Nine, B Ten, B Eleven
"""

    rows = parse_lineups(text, 1958)

    assert rows[0].away == "Germany"
    assert len(rows[0].lineups["Germany"]) == 11


def test_resolve_player_exact_and_safe_fuzzy_rules():
    candidates = [
        PlayerCandidate(1, ("just fontaine",)),
        PlayerCandidate(2, ("jean vincent",)),
    ]

    assert resolve_player("Just Fontaine", candidates) == (1, "exact")
    assert resolve_player("Just Fontain", candidates) == (1, "fuzzy")
    assert resolve_player("Fontain", candidates) == (None, "unmatched_single")
