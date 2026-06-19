#!/usr/bin/env -S gjs -m

import { formatResetTime } from '../lib/time.js';

let passed = 0;
let failed = 0;

function assertEqual(actual, expected, message) {
    if (actual === expected) {
        passed++;
        return;
    }

    failed++;
    print(`FAIL: ${message} - expected ${expected}, got ${actual}`);
}

const now = new Date(2026, 0, 1, 0, 0, 0);

assertEqual(
    formatResetTime(new Date(2026, 0, 1, 1, 59, 30), 'countdown', now),
    'Resets in 1h 59m',
    'countdown includes hours and minutes'
);

assertEqual(
    formatResetTime(new Date(2026, 0, 1, 1, 59, 0), 'time', now),
    'Resets at 1:59 AM',
    'same-day expiration time omits date'
);

assertEqual(
    formatResetTime(new Date(2026, 0, 2, 1, 59, 0), 'time', now),
    'Resets at Jan 2, 1:59 AM',
    'future-day expiration time includes date'
);

print(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0)
    imports.system.exit(1);
