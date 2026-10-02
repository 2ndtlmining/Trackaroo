// Shared SQL fragments for the price queries (#30 Task 4). Each builder emits
// the same SQL its call sites used to spell out by hand -- token for token,
// aliases and join order included -- so the query plans (and with them float
// summation order inside AVG and the bare-column pick under GROUP BY p.id) do
// not move. Options exist to keep the real differences between call sites,
// not to paper over them. Nothing here interpolates user input: windows are
// bound parameters ('?' / '@window') or fixed literals.

// Excludes CPU+motherboard bundle listings (e.g. Scorptec "... power bundle")
// from product pricing. Bundles price the whole combo, not the component alone,
// so they'd throw off CPU-only price listings, movers, and history.
export function notBundle(alias: string): string {
	return `
	lower(${alias}.variant_name) NOT LIKE '%bundle%'
	AND lower(${alias}.variant_name) NOT LIKE '%combo%'
	AND lower(${alias}.listing_url) NOT LIKE '%bundle%'
	AND lower(${alias}.listing_url) NOT LIKE '%bdl-%'
`;
}

/** The latest snapshot date in the whole DB, the anchor every window counts back from. */
export const MAX_SNAPSHOT_DATE = '(SELECT MAX(snapshot_date) FROM price_snapshots)';

export interface DailyCheapestOpts {
	/**
	 * 'standalone': `FROM retailer_listings l JOIN price_snapshots s` (top-level
	 * subqueries and CTEs). 'correlated': `FROM price_snapshots ps3 JOIN
	 * retailer_listings l3`, the per-product correlated form nested inside the
	 * cheapest-listing queries, whose outer aliases are p / l / ps.
	 */
	form: 'standalone' | 'correlated';
	/**
	 * The modifier for `date(anchor, window)`: a bound parameter placeholder or
	 * a fixed day-count literal. null keeps the latest day only
	 * (`snapshot_date = anchor`) instead of a trailing window.
	 */
	window: '?' | '@window' | `'-${number} days'` | null;
	/** Right-hand side of the `product_id` test (e.g. '= ?', '= p.id', 'IN (?,?)'); omit for every product. */
	product?: string;
	/** Also select and group by `product_id` (one row per product per day). */
	perProduct?: boolean;
	/** Output name of the date column; default keeps `snapshot_date`. */
	dateAs?: 'date';
	/** Select the date only, no MIN(price) column (for COUNT(*) of days). */
	dateOnly?: boolean;
	/** Anchor date expression; default MAX_SNAPSHOT_DATE. */
	anchor?: string;
}

// Per day (per product with perProduct), the cheapest in-stock non-bundle
// price: SELECT [product_id,] snapshot_date [AS date][, MIN(price_aud) AS price].
export function dailyCheapestInStock(opts: DailyCheapestOpts): string {
	const [l, s] = opts.form === 'standalone' ? ['l', 's'] : ['l3', 'ps3'];
	const from =
		opts.form === 'standalone'
			? `retailer_listings ${l}
	JOIN price_snapshots ${s} ON ${s}.retailer_listing_id = ${l}.id`
			: `price_snapshots ${s}
	JOIN retailer_listings ${l} ON ${l}.id = ${s}.retailer_listing_id`;
	const anchor = opts.anchor ?? MAX_SNAPSHOT_DATE;

	const columns: string[] = [];
	if (opts.perProduct) columns.push(`${l}.product_id`);
	columns.push(`${s}.snapshot_date${opts.dateAs ? ` AS ${opts.dateAs}` : ''}`);
	if (!opts.dateOnly) columns.push(`MIN(${s}.price_aud) AS price`);

	const where: string[] = [];
	if (opts.product !== undefined) where.push(`${l}.product_id ${opts.product}`);
	where.push(`${s}.stock_status = 'in_stock'`);
	where.push(notBundle(l));
	where.push(
		opts.window === null
			? `${s}.snapshot_date = ${anchor}`
			: `${s}.snapshot_date >= date(${anchor}, ${opts.window})`
	);

	const groupBy = opts.perProduct ? `${l}.product_id, ${s}.snapshot_date` : `${s}.snapshot_date`;

	return `SELECT ${columns.join(', ')}
	FROM ${from}
	WHERE ${where.join('\n\t  AND ')}
	GROUP BY ${groupBy}`;
}

// The cheapest in-stock active listing per tracked product on the latest
// snapshot date (one row per product, ordered by model). `columns` is the
// select list (outer aliases p / l / ps); `where` adds conditions ahead of
// p.tracked = 1, as getCheapestPerModel's category filter sat.
export function cheapestListingPerProduct(columns: string, where?: string): string {
	return `SELECT
		${columns}
	FROM products p
	JOIN retailer_listings l ON l.product_id = p.id AND l.status = 'active'
	JOIN price_snapshots ps
	  ON ps.retailer_listing_id = l.id
	  AND ps.snapshot_date = ${MAX_SNAPSHOT_DATE}
	  AND ps.stock_status = 'in_stock'
	WHERE ${where ? `${where}\n\t  AND ` : ''}p.tracked = 1
	  AND ${notBundle('l')}
	  AND ps.price_aud = (
		SELECT MIN(ps2.price_aud)
		FROM price_snapshots ps2
		JOIN retailer_listings l2 ON l2.id = ps2.retailer_listing_id
		WHERE l2.product_id = p.id
		  AND l2.status = 'active'
		  AND ${notBundle('l2')}
		  AND ps2.snapshot_date = ps.snapshot_date
		  AND ps2.stock_status = 'in_stock'
	  )
	GROUP BY p.id
	ORDER BY p.model COLLATE NOCASE ASC`;
}
