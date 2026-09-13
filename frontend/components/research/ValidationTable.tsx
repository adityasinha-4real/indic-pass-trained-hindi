import type { EstimatorValidationRow } from "@/lib/research-data";

/**
 * Renders one estimator-vs-observed-rank validation table (Spearman,
 * Pearson, error, calibration) — the shared shape both the M4 and M5
 * sections use, transcribed from `results/reports/reference_attack_hin.md`
 * and `results/reports/milestone5_oov_attack.md` respectively.
 */
export function ValidationTable({
  rows,
  showCalibration = true,
}: {
  rows: EstimatorValidationRow[];
  showCalibration?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-3 py-2 font-medium">Estimator</th>
            <th className="px-3 py-2 font-medium text-right">n</th>
            <th className="px-3 py-2 font-medium text-right">Spearman &rho;</th>
            <th className="px-3 py-2 font-medium text-right">MAE</th>
            <th className="px-3 py-2 font-medium text-right">RMSE</th>
            <th className="px-3 py-2 font-medium text-right">&plusmn;1.0 log10</th>
            {showCalibration && <th className="px-3 py-2 font-medium text-right">calib. slope</th>}
            {showCalibration && <th className="px-3 py-2 font-medium text-right">r&sup2;</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.estimator} className="border-b last:border-b-0">
              <td className="px-3 py-2 font-medium">{row.estimator}</td>
              <td className="px-3 py-2 text-right font-mono">{row.n}</td>
              <td className="px-3 py-2 text-right font-mono">{row.spearman.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.mae.toFixed(2)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.rmse.toFixed(2)}</td>
              <td className="px-3 py-2 text-right font-mono">{(row.within1_0 * 100).toFixed(1)}%</td>
              {showCalibration && (
                <td className="px-3 py-2 text-right font-mono">{row.calibrationSlope.toFixed(3)}</td>
              )}
              {showCalibration && (
                <td className="px-3 py-2 text-right font-mono">{row.calibrationR2.toFixed(3)}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
