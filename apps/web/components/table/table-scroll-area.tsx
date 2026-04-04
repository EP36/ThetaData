import type { CSSProperties, ReactNode } from "react";

type TableScrollAreaProps = {
  children: ReactNode;
  minWidth?: number;
  className?: string;
};

type TableScrollStyle = CSSProperties & {
  "--table-min-width"?: string;
};

export function TableScrollArea({
  children,
  minWidth = 680,
  className
}: TableScrollAreaProps) {
  const style: TableScrollStyle = {
    "--table-min-width": `${minWidth}px`
  };
  const classes = className ? `table-scroll ${className}` : "table-scroll";

  return (
    <div className={classes} style={style}>
      {children}
    </div>
  );
}
