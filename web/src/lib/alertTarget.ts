// Validates the product page's alert target price (#15): a positive amount in
// whole cents, no higher than MAX_TARGET_PRICE. Null means "reject".

/** Far above any tracked part; stops a typo like 1e9 being stored as a target. */
export const MAX_TARGET_PRICE = 100_000;

export function parseTargetPrice(raw: FormDataEntryValue | string | null): number | null {
	if (typeof raw !== 'string' || raw.trim() === '') return null;
	const value = Number(raw);
	if (!Number.isFinite(value)) return null;
	const cents = Math.round(value * 100) / 100;
	return cents > 0 && cents <= MAX_TARGET_PRICE ? cents : null;
}
