// Shared runtime constants used by both server and client code.
// Kept out of $lib/server so client components can import them without
// pulling a server-only module into the browser bundle.
export const MIN_HISTORY_POINTS = 3;
