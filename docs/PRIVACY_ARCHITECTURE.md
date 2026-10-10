# Privacy architecture

Birth time、timezone and precise coordinates are highly sensitive. The application has no account／chart
database or user cache；the bundled place SQLite contains public product data, opens read-only and stores
no queries. It adds no analytics、telemetry、APM or external lookup, disables Uvicorn access logging and
emits only validated closed-vocabulary operational events.

The supported proxy terminatesTLS、applies per-IP rate and connection limits in memory、disables access logging and does not forward
client IP headers. These controls do not prove provider、hypervisor、network、OS、browser、RAM、swap、crash
dump、backup or support-access behavior；those require deployment-specific evidence.
