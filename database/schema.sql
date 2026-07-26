DROP TABLE IF EXISTS data_quality_sources CASCADE;
DROP TABLE IF EXISTS data_quality_metrics CASCADE;
DROP TABLE IF EXISTS data_quality_issues CASCADE;
DROP TABLE IF EXISTS source_metadata CASCADE;
DROP TABLE IF EXISTS player_events CASCADE;
DROP TABLE IF EXISTS player_external_ids CASCADE;
DROP TABLE IF EXISTS player_match_stats CASCADE;
DROP TABLE IF EXISTS substitutions CASCADE;
DROP TABLE IF EXISTS bookings CASCADE;
DROP TABLE IF EXISTS player_appearances CASCADE;
DROP TABLE IF EXISTS player_tournaments CASCADE;
DROP TABLE IF EXISTS player_aliases CASCADE;
DROP TABLE IF EXISTS goals CASCADE;
DROP TABLE IF EXISTS players CASCADE;
DROP TABLE IF EXISTS matches CASCADE;
DROP TABLE IF EXISTS stadiums CASCADE;
DROP TABLE IF EXISTS team_aliases CASCADE;
DROP TABLE IF EXISTS teams CASCADE;
DROP TABLE IF EXISTS tournaments CASCADE;

CREATE TABLE tournaments (
  tournament_id SERIAL PRIMARY KEY,
  year SMALLINT NOT NULL UNIQUE CHECK (year BETWEEN 1930 AND 2100),
  name VARCHAR(120) NOT NULL UNIQUE,
  host_country VARCHAR(100),
  source_file VARCHAR(160) NOT NULL UNIQUE
);

CREATE TABLE teams (
  team_id SERIAL PRIMARY KEY,
  canonical_name VARCHAR(120) NOT NULL UNIQUE,
  confederation VARCHAR(10),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (canonical_name <> '')
);

CREATE TABLE team_aliases (
  alias_id SERIAL PRIMARY KEY,
  alias VARCHAR(120) NOT NULL UNIQUE,
  team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
  source_name VARCHAR(120) NOT NULL,
  CHECK (alias <> ''),
  CHECK (source_name <> '')
);

CREATE TABLE stadiums (
  stadium_id SERIAL PRIMARY KEY,
  name VARCHAR(180) NOT NULL,
  city VARCHAR(120) NOT NULL,
  country VARCHAR(100),
  CHECK (name <> ''),
  CHECK (city <> '')
);

CREATE TABLE matches (
  match_id BIGSERIAL PRIMARY KEY,
  source_match_key VARCHAR(260) NOT NULL UNIQUE,
  tournament_id INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE RESTRICT,
  match_date DATE NOT NULL,
  kickoff_time VARCHAR(40),
  stage VARCHAR(100) NOT NULL,
  group_name VARCHAR(40),
  stadium_id INTEGER REFERENCES stadiums(stadium_id) ON DELETE SET NULL,
  home_team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  away_team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  home_score SMALLINT CHECK (home_score IS NULL OR home_score >= 0),
  away_score SMALLINT CHECK (away_score IS NULL OR away_score >= 0),
  data_source VARCHAR(100) NOT NULL,
  source_file VARCHAR(160) NOT NULL,
  external_fjelstul_id VARCHAR(80),
  external_statsbomb_id VARCHAR(80),
  CHECK (home_team_id <> away_team_id),
  CHECK (
    (home_score IS NULL AND away_score IS NULL)
    OR (home_score IS NOT NULL AND away_score IS NOT NULL)
  )
);

CREATE TABLE players (
  player_id BIGSERIAL PRIMARY KEY,
  canonical_name VARCHAR(180) NOT NULL,
  birth_date DATE,
  country_of_birth VARCHAR(120),
  preferred_position VARCHAR(80),
  external_fjelstul_id VARCHAR(80) UNIQUE,
  external_statsbomb_id VARCHAR(80) UNIQUE,
  CHECK (canonical_name <> '')
);

CREATE TABLE player_aliases (
  alias_id BIGSERIAL PRIMARY KEY,
  player_id BIGINT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  source_id VARCHAR(80) NOT NULL,
  original_name VARCHAR(180) NOT NULL,
  normalized_name VARCHAR(180) NOT NULL,
  CHECK (original_name <> ''),
  CHECK (normalized_name <> ''),
  UNIQUE (source_id, normalized_name, player_id)
);

CREATE TABLE player_external_ids (
  source_id VARCHAR(80) NOT NULL,
  external_player_id VARCHAR(120) NOT NULL,
  player_id BIGINT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  original_name VARCHAR(180),
  team_id INTEGER REFERENCES teams(team_id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (source_id, external_player_id)
);

CREATE TABLE player_tournaments (
  player_id BIGINT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  tournament_id INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  shirt_number SMALLINT,
  position VARCHAR(80),
  squad_status VARCHAR(40) NOT NULL DEFAULT 'squad',
  PRIMARY KEY (player_id, tournament_id, team_id)
);

CREATE TABLE player_appearances (
  appearance_id BIGSERIAL PRIMARY KEY,
  player_id BIGINT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  match_id BIGINT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  started BOOLEAN,
  entered_minute SMALLINT CHECK (entered_minute IS NULL OR entered_minute BETWEEN 0 AND 130),
  exited_minute SMALLINT CHECK (exited_minute IS NULL OR exited_minute BETWEEN 0 AND 130),
  minutes_played SMALLINT CHECK (minutes_played IS NULL OR minutes_played BETWEEN 0 AND 130),
  captain BOOLEAN,
  goalkeeper BOOLEAN,
  source_id VARCHAR(80) NOT NULL DEFAULT 'fjelstul',
  UNIQUE (player_id, match_id, team_id, source_id)
);

CREATE TABLE goals (
  goal_id BIGSERIAL PRIMARY KEY,
  source_goal_key VARCHAR(320) NOT NULL UNIQUE,
  match_id BIGINT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
  player_id BIGINT REFERENCES players(player_id) ON DELETE SET NULL,
  team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  tournament_id INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE RESTRICT,
  minute SMALLINT CHECK (minute IS NULL OR minute BETWEEN 0 AND 130),
  stoppage_minute SMALLINT CHECK (stoppage_minute IS NULL OR stoppage_minute BETWEEN 0 AND 30),
  is_penalty BOOLEAN NOT NULL DEFAULT FALSE,
  is_own_goal BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE player_match_stats (
  player_id BIGINT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  match_id BIGINT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
  minutes_played SMALLINT CHECK (minutes_played IS NULL OR minutes_played BETWEEN 0 AND 130),
  goals SMALLINT CHECK (goals IS NULL OR goals >= 0),
  penalties_scored SMALLINT CHECK (penalties_scored IS NULL OR penalties_scored >= 0),
  assists SMALLINT CHECK (assists IS NULL OR assists >= 0),
  shots SMALLINT CHECK (shots IS NULL OR shots >= 0),
  shots_on_target SMALLINT CHECK (shots_on_target IS NULL OR shots_on_target >= 0),
  passes_attempted INTEGER CHECK (passes_attempted IS NULL OR passes_attempted >= 0),
  passes_completed INTEGER CHECK (passes_completed IS NULL OR passes_completed >= 0),
  chances_created SMALLINT CHECK (chances_created IS NULL OR chances_created >= 0),
  tackles SMALLINT CHECK (tackles IS NULL OR tackles >= 0),
  interceptions SMALLINT CHECK (interceptions IS NULL OR interceptions >= 0),
  yellow_cards SMALLINT CHECK (yellow_cards IS NULL OR yellow_cards >= 0),
  red_cards SMALLINT CHECK (red_cards IS NULL OR red_cards >= 0),
  source_id VARCHAR(80) NOT NULL,
  PRIMARY KEY (player_id, match_id, source_id)
);

CREATE TABLE bookings (
  booking_id BIGSERIAL PRIMARY KEY,
  external_booking_id VARCHAR(120),
  match_id BIGINT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
  player_id BIGINT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  minute SMALLINT CHECK (minute IS NULL OR minute BETWEEN 0 AND 130),
  card_type VARCHAR(40) NOT NULL CHECK (card_type IN ('yellow', 'red', 'second_yellow')),
  source_id VARCHAR(80) NOT NULL,
  UNIQUE (source_id, external_booking_id)
);

CREATE TABLE substitutions (
  substitution_id BIGSERIAL PRIMARY KEY,
  external_substitution_id VARCHAR(120),
  match_id BIGINT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  player_out_id BIGINT REFERENCES players(player_id) ON DELETE SET NULL,
  player_in_id BIGINT REFERENCES players(player_id) ON DELETE SET NULL,
  minute SMALLINT CHECK (minute IS NULL OR minute BETWEEN 0 AND 130),
  source_id VARCHAR(80) NOT NULL,
  UNIQUE (source_id, external_substitution_id, player_out_id, player_in_id)
);

CREATE TABLE player_events (
  event_id BIGSERIAL PRIMARY KEY,
  source_id VARCHAR(80) NOT NULL,
  external_event_id VARCHAR(160) NOT NULL,
  match_id BIGINT REFERENCES matches(match_id) ON DELETE CASCADE,
  player_id BIGINT REFERENCES players(player_id) ON DELETE SET NULL,
  team_id INTEGER REFERENCES teams(team_id) ON DELETE SET NULL,
  event_type VARCHAR(80) NOT NULL,
  minute SMALLINT CHECK (minute IS NULL OR minute BETWEEN 0 AND 130),
  second SMALLINT CHECK (second IS NULL OR second BETWEEN 0 AND 59),
  outcome VARCHAR(120),
  raw_event_json JSONB,
  UNIQUE (source_id, external_event_id)
);

CREATE TABLE source_metadata (
  metadata_id BIGSERIAL PRIMARY KEY,
  source_id VARCHAR(80) NOT NULL,
  source_name VARCHAR(120) NOT NULL,
  dataset_name VARCHAR(120) NOT NULL,
  coverage_year SMALLINT CHECK (coverage_year IS NULL OR coverage_year BETWEEN 1930 AND 2100),
  competition_id INTEGER,
  season_id INTEGER,
  match_count INTEGER CHECK (match_count IS NULL OR match_count >= 0),
  file_path TEXT,
  downloaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  notes TEXT
);

CREATE TABLE data_quality_issues (
  issue_id BIGSERIAL PRIMARY KEY,
  source_id VARCHAR(80) NOT NULL,
  issue_type VARCHAR(80) NOT NULL,
  severity VARCHAR(20) NOT NULL DEFAULT 'warning',
  entity_type VARCHAR(80),
  external_id VARCHAR(160),
  description TEXT NOT NULL,
  raw_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE data_quality_metrics (
  metric_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (metric_id = 1),
  raw_records INTEGER NOT NULL CHECK (raw_records >= 0),
  cleaned_records INTEGER NOT NULL CHECK (cleaned_records >= 0),
  duplicate_records INTEGER NOT NULL CHECK (duplicate_records >= 0),
  missing_scores INTEGER NOT NULL CHECK (missing_scores >= 0),
  missing_stadiums INTEGER NOT NULL CHECK (missing_stadiums >= 0),
  alias_mappings INTEGER NOT NULL CHECK (alias_mappings >= 0),
  player_aliases_resolved INTEGER NOT NULL DEFAULT 0 CHECK (player_aliases_resolved >= 0),
  unmatched_players INTEGER NOT NULL DEFAULT 0 CHECK (unmatched_players >= 0),
  ambiguous_player_matches INTEGER NOT NULL DEFAULT 0 CHECK (ambiguous_player_matches >= 0),
  players_with_statsbomb_coverage INTEGER NOT NULL DEFAULT 0 CHECK (players_with_statsbomb_coverage >= 0),
  players_without_advanced_coverage INTEGER NOT NULL DEFAULT 0 CHECK (players_without_advanced_coverage >= 0),
  conflicting_goal_records INTEGER NOT NULL DEFAULT 0 CHECK (conflicting_goal_records >= 0),
  conflicting_appearance_records INTEGER NOT NULL DEFAULT 0 CHECK (conflicting_appearance_records >= 0),
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE data_quality_sources (
  source_file VARCHAR(160) PRIMARY KEY,
  tournament_year SMALLINT NOT NULL CHECK (tournament_year BETWEEN 1930 AND 2100),
  raw_records INTEGER NOT NULL CHECK (raw_records >= 0),
  cleaned_records INTEGER NOT NULL CHECK (cleaned_records >= 0),
  duplicate_records INTEGER NOT NULL CHECK (duplicate_records >= 0)
);

CREATE INDEX idx_team_aliases_team ON team_aliases(team_id);
CREATE UNIQUE INDEX ux_stadiums_name_city_country ON stadiums(name, city, COALESCE(country, ''));
CREATE INDEX idx_stadiums_city ON stadiums(city);
CREATE INDEX idx_matches_date ON matches(match_date);
CREATE INDEX idx_matches_tournament ON matches(tournament_id);
CREATE INDEX idx_matches_tournament_stage ON matches(tournament_id, stage);
CREATE INDEX idx_matches_stage ON matches(stage);
CREATE INDEX idx_matches_home_team ON matches(home_team_id);
CREATE INDEX idx_matches_away_team ON matches(away_team_id);
CREATE INDEX idx_matches_stadium ON matches(stadium_id);
CREATE INDEX idx_player_aliases_player ON player_aliases(player_id);
CREATE INDEX idx_player_aliases_normalized ON player_aliases(normalized_name);
CREATE INDEX idx_player_external_ids_player ON player_external_ids(player_id);
CREATE INDEX idx_player_tournaments_tournament ON player_tournaments(tournament_id);
CREATE INDEX idx_player_tournaments_team ON player_tournaments(team_id);
CREATE INDEX idx_player_appearances_player ON player_appearances(player_id);
CREATE INDEX idx_player_appearances_match ON player_appearances(match_id);
CREATE INDEX idx_player_appearances_team ON player_appearances(team_id);
CREATE INDEX idx_players_name ON players(canonical_name);
CREATE INDEX idx_players_fjelstul ON players(external_fjelstul_id);
CREATE INDEX idx_players_statsbomb ON players(external_statsbomb_id);
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_teams_name_trgm ON teams USING GIN (canonical_name gin_trgm_ops);
CREATE INDEX idx_players_name_trgm ON players USING GIN (canonical_name gin_trgm_ops);
CREATE INDEX idx_goals_player ON goals(player_id);
CREATE INDEX idx_goals_team ON goals(team_id);
CREATE INDEX idx_goals_tournament ON goals(tournament_id);
CREATE INDEX idx_player_match_stats_match ON player_match_stats(match_id);
CREATE INDEX idx_player_match_stats_source ON player_match_stats(source_id);
CREATE INDEX idx_bookings_player ON bookings(player_id);
CREATE INDEX idx_bookings_match ON bookings(match_id);
CREATE INDEX idx_substitutions_match ON substitutions(match_id);
CREATE UNIQUE INDEX ux_substitutions_source_external_players
  ON substitutions(source_id, external_substitution_id, COALESCE(player_out_id, 0), COALESCE(player_in_id, 0));
CREATE INDEX idx_player_events_match ON player_events(match_id);
CREATE INDEX idx_player_events_player ON player_events(player_id);
CREATE INDEX idx_player_events_type ON player_events(event_type);
CREATE INDEX idx_source_metadata_source ON source_metadata(source_id);
CREATE UNIQUE INDEX ux_source_metadata_coverage
  ON source_metadata(source_id, dataset_name, COALESCE(coverage_year, 0), COALESCE(competition_id, 0), COALESCE(season_id, 0));
CREATE INDEX idx_data_quality_issues_type ON data_quality_issues(issue_type);
