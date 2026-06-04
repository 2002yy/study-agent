# Python Requests Notes

HTTP clients should reuse sessions when making repeated requests.
Session reuse keeps connections warm and reduces repeated TCP setup.
Timeouts and retry limits should be explicit for reliable network code.
