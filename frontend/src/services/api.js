const API_URL = import.meta.env.VITE_API_URL || "http://localhost:3001/api";

function buildQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, value);
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request(path, params) {
  const response = await fetch(`${API_URL}${path}${buildQuery(params)}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || "Request failed");
  }
  return payload;
}

export const api = {
  dashboard: () => request("/dashboard"),
  tournaments: () => request("/tournaments"),
  tournament: (year) => request(`/tournaments/${year}`),
  teams: (params) => request("/teams", params),
  team: (teamId) => request(`/teams/${teamId}`),
  matches: (params) => request("/matches", params),
  topScorers: (params) => request("/players/top-scorers", params),
  playerList: (params) => request("/players", params),
  player: (playerId) => request(`/players/${playerId}`),
  playerMatches: (playerId, params) => request(`/players/${playerId}/matches`, params),
  playerLeaderboards: (params) => request("/players/leaderboards", params),
  comparePlayers: (player1, player2) => request("/players/compare", { player1, player2 }),
  compare: (team1, team2) => request("/compare", { team1, team2 }),
  dataQuality: () => request("/data-quality"),
};
