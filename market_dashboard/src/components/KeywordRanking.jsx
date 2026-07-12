import { formatPrice } from "./StatCard";

export default function KeywordRanking({ statsByKeyword, selectedKeyword, onSelect }) {
  const ranking = Array.from(statsByKeyword.entries())
    .filter(([, s]) => s.median !== null)
    .sort((a, b) => a[1].median - b[1].median);

  return (
    <div className="side-col">
      <div className="col-label mono">Ranking por precio mediano</div>
      <div className="rank-panel">
        {ranking.map(([kw, s]) => (
          <div
            key={kw}
            className={`rank-row ${selectedKeyword === kw ? "active" : ""}`}
            onClick={() => onSelect(kw)}
          >
            <span className="rank-kw">{kw}</span>
            <span className="rank-price mono">{formatPrice(s.median)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
