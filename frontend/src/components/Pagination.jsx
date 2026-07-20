export default function Pagination({ page, limit, total, onPage }) {
  const totalPages = Math.max(1, Math.ceil((total || 0) / limit));
  return (
    <div className="pagination">
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span>
        Page {page} of {totalPages} ({total || 0} records)
      </span>
      <button disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}
