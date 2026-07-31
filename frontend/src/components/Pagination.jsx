import Icon from "./Icon";

export default function Pagination({ page, limit, total, onPage }) {
  const totalPages = Math.max(1, Math.ceil((total || 0) / limit));
  const first = total ? (page - 1) * limit + 1 : 0;
  const last = Math.min(page * limit, total || 0);

  return (
    <div className="pagination">
      <span className="pagination-summary">
        {total ? `${first}–${last} of ${Number(total).toLocaleString()}` : "No records"}
      </span>
      <div className="pagination-controls">
        <button aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <Icon name="arrowLeft" size={17} />
        </button>
        <span>Page <b>{page}</b> of {totalPages}</span>
        <button aria-label="Next page" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
          <Icon name="arrowRight" size={17} />
        </button>
      </div>
    </div>
  );
}
