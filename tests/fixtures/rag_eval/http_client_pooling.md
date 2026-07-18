# HTTP Client Pooling and Transport Notes

Connection reuse is a transport concern shared by many HTTP client libraries, not only Python Requests.
A pool keeps established TCP or TLS connections available so later requests can avoid a full handshake.
HTTP keep-alive and connection pooling reduce setup cost, but they do not remove the need for explicit timeouts.
Retries should distinguish idempotent operations from unsafe writes, and retry budgets must be bounded.
HTTP/2 can multiplex several streams over one connection, which changes the relationship between request concurrency and socket count.
DNS caching, proxy configuration and TLS session resumption also affect end-to-end latency.
These transport concepts are generic; library-specific APIs such as `requests.Session` belong in the Requests documentation.
