import { useEffect, useRef } from "react";

export interface MenuItem {
  readonly label: string;
  readonly onClick: () => void;
  readonly danger?: boolean;
  readonly divider?: boolean;
}

interface ContextMenuProps {
  readonly x: number;
  readonly y: number;
  readonly items: readonly MenuItem[];
  readonly onClose: () => void;
}

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as globalThis.Node)) {
        onClose();
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-[100] bg-white rounded-lg shadow-xl border border-gray-200 py-1 min-w-[160px]"
      style={{ left: x, top: y }}
    >
      {items.map((item, i) => (
        <div key={i}>
          {item.divider && <div className="border-t border-gray-100 my-1" />}
          <button
            onClick={() => {
              item.onClick();
              onClose();
            }}
            className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-100 ${
              item.danger ? "text-red-600" : "text-gray-700"
            }`}
          >
            {item.label}
          </button>
        </div>
      ))}
    </div>
  );
}
