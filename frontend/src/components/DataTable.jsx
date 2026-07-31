import { EmptyState } from "./StateView";
import { hasValue } from "../utils/format";

export default function DataTable({ columns, rows, getKey, onRowClick, selectedKey, emptyLabel, caption }) {
  if (!rows?.length) return <EmptyState label={emptyLabel} />;
  const visibleColumns = columns.filter((column) => {
    if (!column.optional) return true;
    return rows.some((row) => column.isAvailable ? column.isAvailable(row) : hasValue(row[column.key]));
  });
  return <div className="table-wrap"><table>{caption && <caption>{caption}</caption>}<thead><tr>{visibleColumns.map((column) => <th key={column.key} className={column.align === "right" ? "align-right" : ""}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row,index)=>{const rowKey=getKey?getKey(row):index;const clickable=Boolean(onRowClick);return <tr key={rowKey} className={`${clickable?"clickable-row":""} ${String(selectedKey)===String(rowKey)?"selected-row":""}`.trim()} onClick={clickable?()=>onRowClick(row):undefined} tabIndex={clickable?0:undefined} onKeyDown={clickable?(event)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();onRowClick(row);}}:undefined}>{visibleColumns.map((column)=>{const available=column.isAvailable?column.isAvailable(row):hasValue(row[column.key]);const value=column.render?column.render(row):row[column.key];return <td key={column.key} className={column.align==="right"?"align-right":""}>{available||!column.optional?value:null}</td>;})}</tr>;})}</tbody></table></div>;
}
