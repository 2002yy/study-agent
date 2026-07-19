# Python Requests Sessions and Reliability

Python Requests can issue one-off HTTP calls, but repeated calls should usually share a `requests.Session`.
A Session keeps a connection pool so compatible requests can reuse established TCP connections instead of paying setup cost every time.
Session reuse can also persist cookies and default headers, so callers should understand which state is shared across requests.
Connection reuse does not replace timeout handling. Production calls should set explicit connect and read timeouts instead of waiting forever.
Retry policy should be bounded and should treat idempotent reads differently from unsafe writes.
For many concurrent requests, a single synchronous Requests Session is not automatically an asynchronous client; concurrency architecture is a separate concern.
When explaining a library-specific API, distinguish `requests.Session` from generic transport concepts such as HTTP/2 multiplexing or DNS caching.
