import type { DB } from '../db';
import type { FxRate } from '../../models';

// Newest cached AUD/USD rate. The table is written by the Python pipeline, so
// an older DB may not have it yet: that is "no rate", never an error.
export function getLatestFxRate(db: DB): FxRate | null {
	try {
		const row = db
			.prepare(
				`SELECT rate_date AS rateDate, aud_per_usd AS audPerUsd, source
				 FROM fx_rates ORDER BY rate_date DESC LIMIT 1`
			)
			.get() as FxRate | undefined;
		return row ?? null;
	} catch {
		return null;
	}
}
