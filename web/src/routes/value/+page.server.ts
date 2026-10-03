import { getValueData, getValueRows } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { METRICS, metricsFor, parseMetric, sourceCitation } from '$lib/perfIndex';
import { bestPerBudget, paretoFrontier, perfPerKilo } from '$lib/value';
import { buildDisplayNames } from '$lib/displayName';

// /value (#33): price against performance for one category and metric. Every
// control lives in the URL (?category=gpu|cpu&metric=…&no8gb=1), so a link
// reproduces the view and the page renders whole on the server.
export function load({ url, setHeaders }: { url: URL; setHeaders: (headers: Record<string, string>) => void }) {
	const category = url.searchParams.get('category') === 'cpu' ? 'cpu' : 'gpu';
	const metric = parseMetric(category, url.searchParams.get('metric'));
	const exclude8gb = category === 'gpu' && url.searchParams.get('no8gb') === '1';
	const db = getDb();
	setHeaders({
		'cache-control': 'public, max-age=60, stale-while-revalidate=300'
	});

	const { points, coverage, required, retailers } = getValueData(db, category, metric);
	// "GeForce RTX 5060 Ti" reads as "... 16GB" beside its 8GB sibling.
	const names = buildDisplayNames(getValueRows(db, category).map((r) => ({ ...r, category })));
	const named = points.map((p) => ({ ...p, name: names.get(p.id) ?? p.name }));

	return {
		wide: true,
		category,
		metric,
		metrics: metricsFor(category),
		metricInfo: METRICS[metric],
		citation: sourceCitation(metric),
		points: named.map((p) => ({ ...p, perKilo: perfPerKilo(p.price, p.perf) })),
		frontier: paretoFrontier(named),
		budgets: bestPerBudget(named, { exclude8gb }),
		exclude8gb,
		excluded: coverage.noPrice,
		coverage,
		required,
		retailers
	};
}
