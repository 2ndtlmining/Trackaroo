// The build stamp (#3, #9): docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD)
// bakes it in as TRACKAROO_VERSION. /healthz and the footer both read it here.
export function buildVersion(): string {
	return process.env.TRACKAROO_VERSION?.trim() || 'dev';
}
