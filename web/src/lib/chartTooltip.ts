export interface TooltipRow {
	label: string;
	value: string;
}

// Builds the chart tooltip from DOM nodes with textContent (#27). Series labels
// are scraped retailer titles; the old innerHTML template turned a hostile or
// odd title into markup -- an injection sink fed by third-party data.
export function renderTooltip(el: HTMLElement, date: string, rows: TooltipRow[]): void {
	const doc = el.ownerDocument;
	const head = doc.createElement('div');
	head.className = 'mb-1 border-b border-border pb-1 text-xs font-medium text-text';
	head.textContent = date;
	const children: HTMLElement[] = [head];
	for (const r of rows) {
		const row = doc.createElement('div');
		row.className = 'flex items-center justify-between gap-4';
		const label = doc.createElement('span');
		label.className = 'text-text-muted';
		label.textContent = r.label;
		const value = doc.createElement('span');
		value.className = 'num text-text';
		value.textContent = r.value;
		row.append(label, value);
		children.push(row);
	}
	el.replaceChildren(...children);
}
