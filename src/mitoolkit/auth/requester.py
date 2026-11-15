import requests, json
from mitoolkit.auth.config import loader

def parse_res(response):
    return json.loads(response.text[11:])

session = requests.Session()
session.headers.update({
    "User-Agent":      "offici5l/migate",
    "Content-Type":    "application/x-www-form-urlencoded",
    "Accept":          "application/json;charset=UTF-8",
    "Accept-Language": "en-US,en;q=0.9"
})


def get(url, **kwargs):
    return _request("GET", url, **kwargs)


def post(url, **kwargs):
    return _request("POST", url, **kwargs)


def _request(method, url, timeout=30, **kwargs):
    try:
        loader.start()
        response = session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except requests.exceptions.Timeout:
        raise ConnectionError("Request timed out") from None
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            raise ConnectionError("Access denied") from None
        raise ConnectionError(f"HTTP error: {e.response.status_code}") from None
    except Exception as e:
        # The text of a requests error contains the full URL, including one-time
        # login tokens in its query string. Report only the kind of failure, and
        # drop the chained exception so a traceback can't print the URL either.
        if "Failed to resolve" in str(e):
            raise ConnectionError("No internet connection") from None
        raise ConnectionError(f"Request failed ({type(e).__name__})") from None
    finally:
        loader.stop()