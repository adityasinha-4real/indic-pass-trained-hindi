/**
 * Client for the IndicPass API adapter (`api/main.py`). This is the only
 * module that talks to the backend — every component reads results through
 * it, so the fetch/parse/error-handling logic exists in exactly one place.
 *
 * The password never touches `localStorage`, `sessionStorage`, a URL, a
 * query string, or an analytics call: it is a POST JSON body, sent to this
 * origin's configured API host only, and this module does not persist it
 * anywhere either — a rejected or resolved fetch simply drops the reference.
 */

import type { AnalyzeResponse, BaselineBlock } from "./types";

const DEFAULT_API_BASE = "http://localhost:8000";

export function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  return (configured && configured.replace(/\/+$/, "")) || DEFAULT_API_BASE;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * `json.dumps` on the Python side (see `api/main.py::_serialize`) allows the
 * bare `Infinity` / `-Infinity` / `NaN` tokens Python's json module emits for
 * a float that genuinely is one — `PasswordStrengthResult.guess_number` is
 * `math.inf` for a guess count that overflows a float (see
 * `guesses_from_log10` in `result.py`), which is exactly the "very long,
 * unstructured password" case this meter is supposed to score correctly.
 * Those tokens are not valid JSON, so a plain `JSON.parse` throws on exactly
 * that input. This swaps the bare tokens for quoted sentinels first — never
 * matching one already inside a quoted string — parses, then maps the
 * sentinels back to real `number` values.
 */
function parseIndicPassJson(text: string): unknown {
  const sentinelled = text
    .replace(/(?<!["\w])-Infinity(?!["\w])/g, '"__NEG_INFINITY__"')
    .replace(/(?<!["\w])Infinity(?!["\w])/g, '"__INFINITY__"')
    .replace(/(?<!["\w])NaN(?!["\w])/g, '"__NAN__"');

  return JSON.parse(sentinelled, (_key, value) => {
    if (value === "__INFINITY__") return Number.POSITIVE_INFINITY;
    if (value === "__NEG_INFINITY__") return Number.NEGATIVE_INFINITY;
    if (value === "__NAN__") return Number.NaN;
    return value;
  });
}

export async function analyzePassword(
  password: string,
  revealTokens: boolean,
): Promise<AnalyzeResponse> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, reveal_tokens: revealTokens }),
      // A password is meaningful only in this exchange; never let the browser
      // cache the response of an analysis.
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      "Could not reach the IndicPass API. Is the backend running at " +
        `${apiBaseUrl()}?`,
    );
  }

  const text = await response.text();

  if (!response.ok) {
    let detail = `Analysis request failed (HTTP ${response.status}).`;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Non-JSON error body (e.g. a proxy's own error page) — keep the
      // generic message rather than surfacing raw HTML to the user.
    }
    throw new ApiError(response.status, detail);
  }

  return parseIndicPassJson(text) as AnalyzeResponse;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/health`, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * The generic baseline's block is nested under a name the config chooses
 * (`config/password.yaml`'s `baseline.implementation`, "zxcvbn" today) —
 * read it through `estimators.baseline` rather than assuming the key.
 */
export function getBaselineBlock(result: AnalyzeResponse): BaselineBlock | undefined {
  const name = result.estimators?.baseline;
  if (!name) return undefined;
  const block = result[name];
  return isBaselineBlock(block) ? block : undefined;
}

function isBaselineBlock(value: unknown): value is BaselineBlock {
  return (
    typeof value === "object" &&
    value !== null &&
    "guesses" in value &&
    "log10_guesses" in value &&
    "score" in value
  );
}
