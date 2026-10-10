# Known limitations

- Open source and bounded reviews do not prove absence of vulnerabilities or calculation errors.
- The service cannot control browser history、autofill、extensions、screenshots、clipboard or saved downloads.
- Provider network metadata、hypervisor memory、support access and storage remain provider-layer risks.
- The container health check (with automatic restart) and external uptime monitoring detect selected availability
  failures；they do not guarantee uptime, complete failure detection or data recovery. A failure outside the
  container (DNS, TLS, the edge or the host) is only reported by the external monitor; nothing restarts it automatically.
- The service is not professional advice；calculation correctness does not validate an astrological method.
- Published security evidence is scoped and is not whole-product approval or a substitute for independent review.
