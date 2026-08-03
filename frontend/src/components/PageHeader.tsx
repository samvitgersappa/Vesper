import type { ReactNode } from "react";

type Props = {
  title: string;
  subtitle?: string;
  accent?: string;
  accentB?: string;
  actions?: ReactNode;
};

export default function PageHeader({
  title,
  subtitle,
  accent = "var(--dash-a)",
  accentB = "var(--dash-b)",
  actions,
}: Props) {
  return (
    <div
      className="page-head"
      style={
        {
          "--ph-a": accent,
          "--ph-b": accentB,
        } as React.CSSProperties
      }
    >
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-sub">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
