import { useEffect, useState } from "react";
import DataTable from "../components/DataTable";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function DataQuality() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.dataQuality().then(setData).catch((err) => setError(err.message));
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Loading data quality" />;

  const metrics = data.metrics || {};
  return (
    <div className="page-stack">
      <div className="cards">
        <Metric label="Raw records" value={metrics.raw_records} />
        <Metric label="Cleaned records" value={metrics.cleaned_records} />
        <Metric label="Duplicates" value={metrics.duplicate_records} />
        <Metric label="Missing values" value={(metrics.missing_scores || 0) + (metrics.missing_stadiums || 0)} />
        <Metric label="Player aliases" value={metrics.player_aliases_resolved} />
        <Metric label="StatsBomb players" value={metrics.players_with_statsbomb_coverage} />
      </div>
      <div className="cards">
        <Metric label="Unmatched players" value={metrics.unmatched_players} />
        <Metric label="Ambiguous matches" value={metrics.ambiguous_player_matches} />
        <Metric label="No advanced coverage" value={metrics.players_without_advanced_coverage} />
        <Metric label="Record conflicts" value={(metrics.conflicting_goal_records || 0) + (metrics.conflicting_appearance_records || 0)} />
      </div>
      <article className="panel prose">
        <h2>Entity resolution and duplicate prevention</h2>
        <p>
          The ETL keeps every raw OpenFootball file unchanged, then resolves observed team labels into canonical team entities before loading. Examples include West Germany to Germany, United States to USA, IR Iran to Iran, and Korea Republic to South Korea. Duplicate matches are blocked with a deterministic key built from tournament year, date, stage, group, and canonical home and away teams, then enforced again by a unique PostgreSQL constraint.
        </p>
      </article>
      <article className="panel">
        <h2>Source metadata</h2>
        <DataTable
          columns={[
            { key: "source_id", label: "Source" },
            { key: "dataset_name", label: "Dataset" },
            { key: "coverage_year", label: "Year", render: (row) => row.coverage_year || "All" },
            { key: "match_count", label: "Rows/matches" },
            { key: "notes", label: "Notes" },
          ]}
          rows={data.source_metadata || []}
          getKey={(row) => `${row.source_id}-${row.dataset_name}-${row.coverage_year || "all"}-${row.season_id || "all"}`}
        />
      </article>
      <article className="panel">
        <h2>Quality issues</h2>
        <DataTable
          columns={[
            { key: "issue_type", label: "Issue" },
            { key: "count", label: "Count" },
          ]}
          rows={data.issues || []}
          getKey={(row) => row.issue_type}
        />
      </article>
      <article className="panel">
        <h2>Data sources</h2>
        <DataTable
          columns={[
            { key: "source_file", label: "Source" },
            { key: "tournament_year", label: "Year" },
            { key: "raw_records", label: "Raw" },
            { key: "cleaned_records", label: "Cleaned" },
            { key: "duplicate_records", label: "Duplicates" },
          ]}
          rows={data.sources}
          getKey={(row) => row.source_file}
        />
      </article>
      <article className="panel">
        <h2>Alias mappings</h2>
        <DataTable
          columns={[
            { key: "original_name", label: "Original name" },
            { key: "canonical_name", label: "Canonical name" },
          ]}
          rows={data.alias_mappings}
          getKey={(row) => row.original_name}
        />
      </article>
      <article className="panel">
        <h2>Player aliases</h2>
        <DataTable
          columns={[
            { key: "source_id", label: "Source" },
            { key: "original_name", label: "Original name" },
            { key: "canonical_name", label: "Canonical name" },
          ]}
          rows={data.player_aliases || []}
          getKey={(row) => `${row.source_id}-${row.original_name}-${row.canonical_name}`}
        />
      </article>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <article className="kpi">
      <span>{label}</span>
      <strong>{Number(value || 0).toLocaleString()}</strong>
    </article>
  );
}
