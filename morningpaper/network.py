"""Prevent credentials from being forwarded by HTTP redirects."""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.has_header("Authorization") or (urllib.parse.urlparse(req.full_url).scheme == "https"
                                               and urllib.parse.urlparse(newurl).scheme != "https"):
            raise urllib.error.HTTPError(req.full_url, code, "Unsafe redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen(request, timeout=20):
    return urllib.request.build_opener(SafeRedirectHandler()).open(request, timeout=timeout)
