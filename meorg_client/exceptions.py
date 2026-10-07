"""Custom exceptions."""


class RequestException(Exception):
    """Raised when a request fails.

    Parameters
    ----------
    status_code : int
        HTTP status code.
    response_text : str
        Response text.
    """

    def __init__(self, status_code, response_text):
        self.status_code = status_code
        self.response_text = response_text
        self.msg = f"Request failed with status code {status_code}: {response_text}"
        super().__init__(self.msg)


class InvalidHTTPMethodException(Exception):
    """Raised when the HTTP method is invalid.

    Parameters
    ----------
    method : str
        Invalid method name.
    """

    def __init__(self, method):
        super().__init__(f"Invalid HTTP Method {method}.")


class DownloadException(Exception):
    """Raised when a file cannot be downloaded.

    Parameters
    ----------
    msg : str
        Message. It must never hold a signed URL.
    """

    def __init__(self, msg):
        self.msg = msg
        super().__init__(msg)
