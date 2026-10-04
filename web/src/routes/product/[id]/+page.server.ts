import { error, fail, redirect } from '@sveltejs/kit';
import {
	getBestInStockPrice,
	getLatestFxRate,
	getOzbDeals,
	getProductMsrp,
	getProductAlerts,
	getProductHistory,
	getRetailerLatest,
	upsertAlert,
	deleteAlert,
	getMatchup
} from '$lib/server/repos';
import { getDb, getWriteDb } from '$lib/server/db';
import { memo } from '$lib/server/cache';
import { formatAud, melbourneTodayIso } from '$lib/formats';
import { MAX_TARGET_PRICE, parseTargetPrice } from '$lib/alertTarget';
import type { AlertChannel } from '$lib/types';

const CHANNELS: AlertChannel[] = ['discord', 'email', 'webhook'];

// A matchup failure must never 500 the product page (#60).
function safeMatchup(db: ReturnType<typeof getDb>, id: number) {
	try {
		return getMatchup(db, id);
	} catch (err) {
		console.error('getMatchup failed', id, err);
		return null;
	}
}

// The product page itself is deliberately NOT memoised or cache-control'd:
// alert state must show up immediately after the create/delete redirect back
// here. retailerLatest is the one query on this page that is day-level and
// product-independent (a full price_snapshots scan), so it alone is worth
// memoising (#28).
export function load({ params }: { params: { id: string } }) {
	const id = Number(params.id);
	if (!Number.isInteger(id) || id <= 0) {
		error(404, 'Product not found');
	}
	const db = getDb();
	const retailerLatest = memo(db, 'retailerLatest', () => getRetailerLatest(db));
	const data = getProductHistory(db, id, retailerLatest);
	if (!data) {
		error(404, 'Product not found');
	}
	const now = new Date();
	return {
		...data,
		alerts: getProductAlerts(db, id),
		fx: getLatestFxRate(db),
		msrpUsd: getProductMsrp(db, id),
		// OzBargain deals (#34). ozbBest is the Python alert's "best in stock"
		// (R1/R7), so "Below our best" here and the Discord alert agree.
		ozb: getOzbDeals(db, id, now),
		ozbBest: getBestInStockPrice(db, id),
		ozbNow: now.toISOString(),
		// Head-to-head with the nearest other-brand rival (#60); null when none qualifies.
		matchup: safeMatchup(db, id),
		// Computed once on the server so a render near Melbourne midnight cannot
		// differ between server and client (sale badge).
		today: melbourneTodayIso(new Date())
	};
}

export const actions = {
	create: async ({ request, params }) => {
		const id = Number(params.id);
		if (!Number.isInteger(id) || id <= 0) {
			error(404, 'Product not found');
		}
		const form = await request.formData();
		const target = parseTargetPrice(form.get('target_price'));
		const channel = String(form.get('channel') ?? 'discord') as AlertChannel;

		// Validation returns fail() rather than error(): error() replaces the whole
		// product page with an error screen, losing the chart, the listings and
		// whatever the user typed. fail() re-renders the page with a message.
		if (target === null) {
			return fail(400, {
				error: `Enter a target price above $0, up to ${formatAud(MAX_TARGET_PRICE)}.`,
				target_price: String(form.get('target_price') ?? ''),
				channel
			});
		}
		if (!CHANNELS.includes(channel)) {
			return fail(400, {
				error: 'Unknown notification channel.',
				target_price: String(target),
				channel: 'discord' as AlertChannel
			});
		}
		const notifyOnRestock = form.get('notify_on_restock') === 'on' || form.get('notify_on_restock') === '1';

		upsertAlert(getWriteDb(), id, target, channel, notifyOnRestock);
		redirect(303, `/product/${id}`);
	},
	delete: async ({ request, params }) => {
		const id = Number(params.id);
		if (!Number.isInteger(id) || id <= 0) {
			error(404, 'Product not found');
		}
		const form = await request.formData();
		const alertId = Number(form.get('alert_id'));
		if (Number.isInteger(alertId) && alertId > 0) {
			deleteAlert(getWriteDb(), id, alertId);
		}
		redirect(303, `/product/${id}`);
	}
};
