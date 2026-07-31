const paths = {
  overview: ["M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z"],
  matches: ["M7 3v2M17 3v2M4 8h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z", "M8 12h3v3H8zM14 12h2M14 16h2"],
  teams: ["M16 20v-1.5A4.5 4.5 0 0 0 11.5 14h-3A4.5 4.5 0 0 0 4 18.5V20M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM17 11a3 3 0 1 0 0-6M18 14a4 4 0 0 1 4 4v2"],
  players: ["M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9ZM4 21a8 8 0 0 1 16 0"],
  leaderboard: ["M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0V4ZM7 6H4v1a4 4 0 0 0 4 4M17 6h3v1a4 4 0 0 1-4 4"],
  tournaments: ["M12 3 9.8 7.6 5 8.3l3.5 3.4-.8 4.8 4.3-2.3 4.3 2.3-.8-4.8L19 8.3l-4.8-.7L12 3Z", "M5 21h14M8 18h8"],
  compare: ["M7 3v18M17 3v18M3 7h8M13 17h8M4 7l3-3 3 3M14 17l3 3 3-3"],
  playerCompare: ["M8 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM2.5 20a5.5 5.5 0 0 1 11 0M17 10a3 3 0 1 0 0-6M14 15a5 5 0 0 1 7.5 4.3"],
  quality: ["M12 3 4 7v5c0 5 3.4 8.2 8 9 4.6-.8 8-4 8-9V7l-8-4Z", "m8.5 12 2.2 2.2L15.5 9.5"],
  menu: ["M4 7h16M4 12h16M4 17h16"], close: ["m6 6 12 12M18 6 6 18"], search: ["m21 21-4.35-4.35M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z"],
  reset: ["M4 4v6h6M20 20v-6h-6", "M5.6 15A8 8 0 0 0 19 8M18.4 9A8 8 0 0 0 5 16"], arrowLeft: ["m15 18-6-6 6-6"], arrowRight: ["m9 18 6-6-6-6"], chevron: ["m9 18 6-6-6-6"],
  database: ["M20 6c0 1.7-3.6 3-8 3S4 7.7 4 6s3.6-3 8-3 8 1.3 8 3Z", "M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"],
  goal: ["M12 3 9.5 7.2 4.7 8.3 8 11.6l-.5 4.9L12 14.3l4.5 2.2-.5-4.9 3.3-3.3-4.8-1.1L12 3Z"], stadium: ["M4 8c0-2.2 3.6-4 8-4s8 1.8 8 4-3.6 4-8 4-8-1.8-8-4Z", "M4 8v8c0 2.2 3.6 4 8 4s8-1.8 8-4V8M8 11v8M16 11v8"], info: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z", "M12 10v6M12 7h.01"],
};
export default function Icon({ name, size = 20, className = "" }) {
  const iconPaths = paths[name] || paths.info;
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{iconPaths.map((path, index) => <path key={index} d={path} />)}</svg>;
}
