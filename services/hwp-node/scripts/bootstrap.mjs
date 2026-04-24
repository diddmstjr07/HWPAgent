// This file must run before any @rhwp/core document operations.
globalThis.measureTextWidth = (_font, text) => text.length * 7;
