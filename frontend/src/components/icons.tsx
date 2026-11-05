import type { CSSProperties } from "react";
const paths: Record<string, string> = {
  home: "M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z",
  book: "M12 5v16M3 3h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3Z",
  map: "M6 6h12M6 6l6 12M18 6l-6 12M4 4h4v4H4ZM16 4h4v4h-4ZM10 16h4v4h-4Z",
  folder: "M3 7V4h7l2 3h9v13H3Z",
  chart: "M4 3v17h17M8 15v-4M13 15V7M18 15V4",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  chevron: "m9 5 7 7-7 7",
  check: "m5 12 4 4L19 6",
  clock: "M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  spark: "m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6Z",
  close: "m6 6 12 12M6 18 18 6",
  search: "m16 16 5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  leaf: "M19 3C5 3 3 9 6 16c7 3 13 1 13-13ZM5 20 15 9",
  source: "M14 3H5v18h14V8Zm0 0v5h5M8 12h8M8 16h6",
  hint: "M9 21h6M9 17v-2a7 7 0 1 1 6 0v2Z",
  reset: "M3 10a9 9 0 1 1 2 9M3 3v7h7",
  lock: "M6 10V7a6 6 0 0 1 12 0v3M4 10h16v11H4Z",
  edit: "m14 5 5 5M4 20l4.2-.9L19 8.3a2.1 2.1 0 0 0-3-3L5.2 16.1 4 20Z",
};
export function Icon({
  name,
  size = 20,
  style,
}: {
  name: string;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name] || paths.spark} />
    </svg>
  );
}
