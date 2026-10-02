import { afterEach, describe, expect, it } from 'vitest';
import { SUCCESSORS, successorFor } from '../src/lib/successors';

afterEach(() => {
	delete SUCCESSORS['RTX 50'];
});

describe('successorFor', () => {
	it('is null for an empty map, unknown or null series', () => {
		expect(successorFor('RTX 50')).toBeNull();
		expect(successorFor(null)).toBeNull();
		expect(successorFor('toString')).toBeNull();
	});
	it('returns the label when mapped', () => {
		SUCCESSORS['RTX 50'] = 'RTX 60';
		expect(successorFor('RTX 50')).toBe('RTX 60');
	});
});
