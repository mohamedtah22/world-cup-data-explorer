import { useEffect, useId, useRef, useState } from "react";

export default function AsyncEntityAutocomplete({ label, value, onChange, search, excludeId, placeholder }) {
  const id = useId();
  const rootRef = useRef(null);
  const [text, setText] = useState(value?.label || "");
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    setText(value?.label || "");
  }, [value?.id, value?.label]);

  useEffect(() => {
    function onDocumentClick(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocumentClick);
    return () => document.removeEventListener("mousedown", onDocumentClick);
  }, []);

  useEffect(() => {
    const query = text.trim();
    if (value?.label === text || query.length < 1) {
      setItems([]);
      setLoading(false);
      setError("");
      return undefined;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      search({ q: query, limit: 10 }, { signal: controller.signal })
        .then((rows) => {
          setItems(rows.filter((row) => String(row.id) !== String(excludeId)));
          setActiveIndex(-1);
          setOpen(true);
        })
        .catch((err) => {
          if (err.name !== "AbortError") setError(err.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 275);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [text, value?.label, search, excludeId]);

  function selectItem(item) {
    onChange(item);
    setText(item.label);
    setOpen(false);
    setItems([]);
  }

  function onInput(event) {
    const next = event.target.value;
    setText(next);
    if (value?.id) onChange(null);
    setOpen(true);
  }

  function onKeyDown(event) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open && ["ArrowDown", "ArrowUp"].includes(event.key)) {
      setOpen(true);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => Math.min(items.length - 1, current + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(0, current - 1));
    } else if (event.key === "Enter" && activeIndex >= 0 && items[activeIndex]) {
      event.preventDefault();
      selectItem(items[activeIndex]);
    }
  }

  const listId = `${id}-listbox`;
  return (
    <label className="autocomplete" ref={rootRef}>
      {label}
      <input
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        value={text}
        placeholder={placeholder}
        onChange={onInput}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <div className="autocomplete-menu" role="listbox" id={listId}>
          {loading && <div className="autocomplete-state">Loading...</div>}
          {error && <div className="autocomplete-state autocomplete-error">{error}</div>}
          {!loading && !error && text.trim() && items.length === 0 && <div className="autocomplete-state">No results</div>}
          {!loading && !error && items.map((item, index) => (
            <button
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              id={`${listId}-${index}`}
              key={item.id}
              className={index === activeIndex ? "active-suggestion" : ""}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectItem(item)}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </label>
  );
}
