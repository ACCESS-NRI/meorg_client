import os

"""Constants."""

# Valid HTTP methods
HTTP_POST = "POST"
HTTP_PUT = "PUT"
HTTP_GET = "GET"
HTTP_DELETE = "DELETE"
HTTP_PUT = "PUT"
HTTP_PATCH = "PATCH"
VALID_METHODS = [HTTP_PUT, HTTP_GET, HTTP_DELETE, HTTP_PUT, HTTP_POST, HTTP_PATCH]

# Methods that interpolate parameters into the URL
INTERPOLATING_METHODS = [HTTP_GET, HTTP_PUT, HTTP_PATCH, HTTP_DELETE]

# RFC 2616 states status in the 2xx range are considered successful
HTTP_STATUS_SUCCESS_RANGE = range(200, 300)

# Production URL
MEORG_BASE_URL_PROD = "https://modelevaluation.org/api"

# Connect and read timeouts (seconds) for signed URL downloads
DOWNLOAD_TIMEOUT = (10, 120)
