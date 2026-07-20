import { useEffect, useState } from "react";
import DataTable from "../components/DataTable";
import Pagination from "../components/Pagination";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

const emptyFilters = {
  year: "",
  team: "",
  stage: "",
  stadium: "",
  date_from: "",
  date_to: "",
  search: "",
};

export default function Matches() {
  const [filters, setFilters] = useState(emptyFilters);
  const [page, setPage] = useState(1);
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    api
      .matches({ ...filters, page, limit: 20 })
      .then(setPayload)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [filters, page]);

  function updateFilter(event) {
    setFilters((current) => ({ ...current, [event.target.name]: event.target.value }));
    setPage(1);
  }

  function reset() {
    setFilters(emptyFilters);
    setPage(1);
  }

  const columns = [
    { key: "match_date", label: "Date" },
    { key: "year", label: "Year" },
    { key: "home_team", label: "Home" },
    { key: "score", label: "Score", render: (row) => `${row.home_score ?? "-"} : ${row.away_score ?? "-"}` },
    { key: "away_team", label: "Away" },
    { key: "stage", label: "Stage" },
    { key: "stadium", label: "Stadium", render: (row) => `${row.stadium || "Unknown"}${row.city ? `, ${row.city}` : ""}` },
  ];

  return (
    <div className="page-stack">
      <div className="filters">
        <label>
          Year
          <input name="year" value={filters.year} onChange={updateFilter} inputMode="numeric" />
        </label>
        <label>
          Team
          <input name="team" value={filters.team} onChange={updateFilter} />
        </label>
        <label>
          Stage
          <input name="stage" value={filters.stage} onChange={updateFilter} />
        </label>
        <label>
          Stadium
          <input name="stadium" value={filters.stadium} onChange={updateFilter} />
        </label>
        <label>
          From
          <input type="date" name="date_from" value={filters.date_from} onChange={updateFilter} />
        </label>
        <label>
          To
          <input type="date" name="date_to" value={filters.date_to} onChange={updateFilter} />
        </label>
        <label>
          Search
          <input name="search" value={filters.search} onChange={updateFilter} />
        </label>
        <button onClick={reset}>Reset filters</button>
      </div>
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Loading matches" />}
      {!loading && !error && (
        <>
          <DataTable columns={columns} rows={payload?.results || []} getKey={(row) => row.match_id} />
          <Pagination page={page} limit={20} total={payload?.pagination?.total || 0} onPage={setPage} />
        </>
      )}
    </div>
  );
}
