import pytest

from smolhttpd import handle_request_header, HTTPError

simple_get_request = b"GET /index.html HTTP/1.1\r\nHost: example.com\r\nUser-Agent: test\r\nAccept: */*\r\n\r\n"
large_header_get_request = simple_get_request[:-2] + b"x-random-header: this is just a very very large header to test some features\r\n\r\n"

class MockReceiver(object):

    def __init__(self, data):

        self.data = data
        self.pos = 0

    def recv(self, num_bytes):

        return_bytes = self.data[self.pos : self.pos + num_bytes]
        self.pos += len(return_bytes)
        return return_bytes

def test_simple_get():

    result = handle_request_header(MockReceiver(simple_get_request))
    assert result.method == b"GET"
    assert result.uri == b"/index.html"
    assert len(result.buf) == 0
    assert result.content_length == 0

def test_small_buffers_get():

    result = handle_request_header(MockReceiver(simple_get_request), bufsize=30)
    assert result.method == b"GET"
    assert result.uri == b"/index.html"
    assert len(result.buf) == 0
    assert result.content_length == 0

def test_uri_too_long():

    with pytest.raises(HTTPError, match="414"):
        result = handle_request_header(MockReceiver(simple_get_request), bufsize=20)

def test_header_too_long():

    with pytest.raises(HTTPError, match="431"):
        result = handle_request_header(MockReceiver(large_header_get_request), bufsize=30)

def test_headers():

    result = handle_request_header(MockReceiver(simple_get_request), bufsize=30, interesting_headers=set(("ACCEPT", "Host")))
    assert result.method == b"GET"
    assert result.uri == b"/index.html"
    assert len(result.buf) == 0
    assert result.content_length == 0
    assert result.headers["host"] == ["example.com"]
    assert result.headers["accept"] == ["*/*"]
    
def test_large_header():

    result = handle_request_header(MockReceiver(large_header_get_request), bufsize=100, interesting_headers=set(("ACCEPT", "Host", "x-random-header")))
    assert result.method == b"GET"
    assert result.uri == b"/index.html"
    assert len(result.buf) == 0
    assert result.content_length == 0
    assert result.headers["host"] == ["example.com"]
    assert result.headers["accept"] == ["*/*"]
    assert result.headers["x-random-header"] == ["this is just a very very large header to test some features"]
    
