// The build stamp (#3, #9): docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD)
// bakes it in as TRACKAROO_VERSION. /healthz and the footer both read it here.
export function buildVersion(): string {
	return process.env.TRACKAROO_VERSION?.trim() || 'dev';
}

// The human release number (web/package.json, via vite `define`), shown in the
// footer next to the build stamp and reported by /healthz as `release`.
export function releaseVersion(): string {
	return __APP_RELEASE__;
}
