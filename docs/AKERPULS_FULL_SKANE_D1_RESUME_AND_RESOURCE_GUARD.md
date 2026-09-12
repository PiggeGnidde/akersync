# D1 resume/resource guard note

The D1 acquisition is designed to be safely rerunnable. Daily source tiles are cached together with request and response hashes; verified cache hits do not spend new PU.

Before the first new Process API request, the implementation checks available disk space. The intended guard is based on the remaining theoretical uncompressed bytes for missing daily source tiles plus missing snapshot tiles, with additional reserve, so an interrupted run can resume without requiring the original full-run free-space allowance.

OAuth access tokens must be refreshed periodically during the 593-request run; token refresh is not a Sentinel Hub processing request and does not consume PU.
