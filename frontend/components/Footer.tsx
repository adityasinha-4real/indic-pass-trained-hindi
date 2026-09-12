export function Footer() {
  return (
    <footer className="border-t py-6 text-center text-xs text-muted">
      <p>
        IndicPass is a research project, not a production credential manager.
        Passwords typed above are analyzed in memory and never logged, stored, or
        sent anywhere but this analysis.
      </p>
      <p className="mt-1">
        Source, methodology and full results: see{" "}
        <code className="font-mono">README.md</code> and{" "}
        <code className="font-mono">docs/password_strength_design.md</code> in the
        repository.
      </p>
    </footer>
  );
}
