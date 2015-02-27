import cgi
import json
from treq._utils import default_reactor

from twisted.internet.defer import Deferred, succeed

from twisted.internet.protocol import Protocol
from twisted.web.client import ResponseDone
from twisted.web.http import PotentialDataLoss


def _encoding_from_headers(headers):
    content_types = headers.getRawHeaders('content-type')

    if content_types is None:
        return None

    # This seems to be the choice browsers make when encountering multiple
    # content-type headers.
    content_type, params = cgi.parse_header(content_types[-1])

    if 'charset' in params:
        return params.get('charset').strip("'\"")


class _BodyCollector(Protocol):
    def __init__(self, finished, collector):
        self.finished = finished
        self.collector = collector

    def dataReceived(self, data):
        self.collector(data)

    def connectionLost(self, reason):
        if reason.check(ResponseDone):
            self.finished.callback(None)
        elif reason.check(PotentialDataLoss):
            # http://twistedmatrix.com/trac/ticket/4840
            self.finished.callback(None)
        else:
            self.finished.errback(reason)


def collect(response, request_kwargs, collector):
    """
    Incrementally collect the body of the response.

    This function may only be called **once** for a given response.

    :param IResponse response: The HTTP response to collect the body from.
    :param collector: A callable to be called each time data is available
        from the response body.
    :type collector: single argument callable

    :rtype: Deferred that fires with None when the entire body has been read.
    """
    if response.length == 0:
        return succeed(None)

    d = Deferred()
    response.deliverBody(_BodyCollector(d, collector))
    if request_kwargs.get('timeout'):
        delayedCall = default_reactor(request_kwargs.get('reactor')).callLater(
            request_kwargs.get('timeout'), d.cancel)

        def gotResult(result):
            if delayedCall.active():
                delayedCall.cancel()
            return result

        d.addBoth(gotResult)
    return d


def content(response, request_kwargs):
    """
    Read the contents of an HTTP response.

    This function may be called multiple times for a response, it uses a
    ``WeakKeyDictionary`` to cache the contents of the response.

    :param IResponse response: The HTTP Response to get the contents of.

    :rtype: Deferred that fires with the content as a str.
    """
    _content = []
    d = collect(response, request_kwargs, _content.append)
    d.addCallback(lambda _: ''.join(_content))
    return d


def json_content(response, request_kwargs):
    """
    Read the contents of an HTTP response and attempt to decode it as JSON.

    This function relies on :py:func:`content` and so may be called more than
    once for a given response.

    :param IResponse response: The HTTP Response to get the contents of.

    :rtype: Deferred that fires with the decoded JSON.
    """
    d = content(response, request_kwargs)
    d.addCallback(json.loads)
    return d


def text_content(response, request_kwargs, encoding='ISO-8859-1'):
    """
    Read the contents of an HTTP response and decode it with an appropriate
    charset, which may be guessed from the ``Content-Type`` header.

    :param IResponse response: The HTTP Response to get the contents of.
    :param str encoding: An valid charset, such as ``UTF-8`` or ``ISO-8859-1``.

    :rtype: Deferred that fires with a unicode.
    """
    def _decode_content(c):
        e = _encoding_from_headers(response.headers)

        if e is not None:
            return c.decode(e)

        return c.decode(encoding)

    d = content(response, request_kwargs)
    d.addCallback(_decode_content)
    return d
