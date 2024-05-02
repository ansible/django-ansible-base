## Remote Headers

If you want to know what machine is making the request to your service you might be tempted to look at the `REMOTE_ADDR` header passed by Nginx.

If you are running behind a proxy or load balancer the value in this header could be the IP of said device thus not indicating the actual host making the request.

DAB offers two functions called `get_remote_host` and `get_remote_hosts` to help deal with this.

`get_remote_hosts` will attempt to look at the setting `REMOTE_HOST_HEADERS` (defaulted to `['REMOTE_ADDR', 'REMOTE_HOST']`). For any named header in that array the code will split the header (if present) on `,` and then return an array of all the addresses found (in order with duplicates).
Additionally if the header `HTTP_X_TRUSTED_PROXY` and is present and is properly signed with a pre-shared key, the method will automatically prepend the following to `REMOTE_HOST_HEADERS`: `['HTTP_X_FORWARDED_FOR', 'HTTP_X_ENVOY_EXTERNAL_ADDRESS']`. 

`get_remote_host` will return the first entry found by `get_remote_hosts` or None. 
