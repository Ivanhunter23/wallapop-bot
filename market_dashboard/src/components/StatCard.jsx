export function formatPrice(p) {
  if (p === null || p === undefined) return "—";
  return (
    p.toLocaleString("es-ES", { minimumFractionDigits: 0, maximumFractionDigits: 2 }) +
    " €"
  );
}

export function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export default function StatCard({ label, value, accent }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value mono" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
    </div>
  );
}
