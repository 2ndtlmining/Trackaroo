import { error, fail, redirect } from '@sveltejs/kit';
import { getProductAlerts, getProductHistory, upsertAlert, deleteAlert } from '$lib/server/repos';
import { getDb, getWriteDb } from '$lib/server/db';
import type { AlertChannel } from '$lib/types';

const CHANNELS: AlertChannel[] = ['discord', 'email', 'webhook'];

export function load({ params }: { params: { id: string } }) {
	const id = Number(params.id);
	if (!Number.isInteger(id) || id <= 0) {
		error(404, 'Product not found');
	}
	const data = getProductHistory(getDb(), id);
	if (!data) {
		error(404, 'Product not found');
	}
	return { ...data, alerts: getProductAlerts(getDb(), id) };
}

export const actions = {
	create: async ({ request, params }) => {
		const id = Number(params.id);
		if (!Number.isInteger(id) || id <= 0) {
			error(404, 'Product not found');
		}
		const form = await request.formData();
		const rawTarget = Number(form.get('target_price'));
		const channel = String(form.get('channel') ?? 'discord') as AlertChannel;

		// Validation returns fail() rather than error(): error() replaces the whole
		// product page with an error screen, losing the chart, the listings and
		// whatever the user typed. fail() re-renders the page with a message.
		if (!Number.isFinite(rawTarget) || rawTarget <= 0) {
			return fail(400, {
				error: 'Enter a target price above zero.',
				target_price: String(form.get('target_price') ?? ''),
				channel
			});
		}
		if (!CHANNELS.includes(channel)) {
			return fail(400, {
				error: 'Unknown notification channel.',
				target_price: String(rawTarget),
				channel: 'discord' as AlertChannel
			});
		}
		const notifyOnRestock = form.get('notify_on_restock') === 'on' || form.get('notify_on_restock') === '1';

		upsertAlert(getWriteDb(), id, rawTarget, channel, notifyOnRestock);
		redirect(303, `/product/${id}`);
	},
	delete: async ({ request, params }) => {
		const id = Number(params.id);
		const form = await request.formData();
		const alertId = Number(form.get('alert_id'));
		if (Number.isInteger(alertId) && alertId > 0) {
			deleteAlert(getWriteDb(), alertId);
		}
		redirect(303, `/product/${id}`);
	}
};
