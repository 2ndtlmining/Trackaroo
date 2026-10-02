import type { DB } from '../db';
import type { AlertChannel } from '../../types';
import type { AlertRow } from '../../models';

// One alert per (product, channel). Re-arming an existing (product, channel)
// updates its target/restock flag and re-activates it rather than stacking a
// duplicate row. Cooldown columns are managed by check_alerts.py, never here.
export function upsertAlert(
	db: DB,
	productId: number,
	targetPrice: number,
	channel: AlertChannel,
	notifyOnRestock: boolean
): void {
	db.prepare(
		`INSERT INTO price_alerts (product_id, target_price, channel, notify_on_restock, active)
		 VALUES (?, ?, ?, ?, 1)
		 ON CONFLICT (product_id, channel)
		 DO UPDATE SET target_price = excluded.target_price,
		               notify_on_restock = excluded.notify_on_restock,
		               active = 1`
	).run(productId, targetPrice, channel, notifyOnRestock ? 1 : 0);
}

export function deleteAlert(db: DB, alertId: number): void {
	db.prepare('DELETE FROM price_alerts WHERE id = ?').run(alertId);
}

export function getProductAlerts(db: DB, productId: number): AlertRow[] {
	return db
		.prepare(
			`SELECT id, product_id, target_price, channel, notify_on_restock, active,
			        last_notified_at, last_notified_price, created_at
			 FROM price_alerts
			 WHERE product_id = ?
			 ORDER BY channel`
		)
		.all(productId) as AlertRow[];
}
