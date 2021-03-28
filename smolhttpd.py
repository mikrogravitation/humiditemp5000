from collections import namedtuple
import re as ure

TCHAR = r""
PCHAR = r"[a-zA-Z0-9-._~!$&'()*+,;=:@]|%[0-9a-fA-F][0-9a-fA-F]"

HTTPRequest = namedtuple("HTTPRequest", ("method", "uri", "headers", "buf", "content_length"))

class HTTPError(RuntimeError):
    def __init__(self, status_code, explanation=""):
        self.status_code = status_code
        self.explanation = explanation
        super().__init__(self, "{}: {}".format(status_code, explanation))

# parse the request line
# match_result = ure.match("({}+) ?((/({}|%[0-9a-fA-F][0-9a-fA-F])*)+)? ?(HTTP/([0-9]).([0-9])\r\n)?".format(TCHAR, PCHAR_WO_PCT_ENCODED), self.buffer)

token_re = ure.compile(b"[!#$%&'*+-.^_`|~0-9a-zA-Z]+$")
uri_re = ure.compile("(/({pchar})*)+(\\?({pchar}|[/?])*)?$".format(pchar=PCHAR).encode("ascii"))
percent_re = ure.compile(b"%[0-9a-fA-F][0-9a-fA-F]")
http_version_re = ure.compile(b"HTTP/([0-9]).([0-9])$")
header_value_re = ure.compile(b"[ -~\t]*$")


def validate_token(token):
    return bool(token_re.match(token))


def validate_uri(uri):
    return bool(uri_re.match(uri))


def get_http_version(http_version):
    match_result = http_version_re.match(http_version)
    if not match_result:
        return None

    major = int(match_result.group(1))
    minor = int(match_result.group(2))

    return (major, minor)


def parse_header(header_line):

    split_result = header_line.split(b":")
    if len(split_result) != 2:
        return None

    header_name, header_value = split_result

    if not validate_token(header_name):
        return None

    if not header_value_re.match(header_value):
        return None

    header_value = header_value.strip(b" \t")
    # this step is necessary since the regex does not fully
    # represent the set of valid header_values
    if header_value == b"":
        return None

    header_name = header_name.decode("ascii")
    header_value = header_value.decode("ascii")

    return (header_name, header_value)


def replace_percent(match_string):
    return bytes([int(match_string[1:3], base=16)])


def decode_percent(string):
    return percent_re.replace(replace_percent, string)


# parses an origin-form uri into path components,
# undoing any percent-encoding that was done on them.
# note that this means that
def parse_uri_into_components(uri):

    assert uri_re.match(uri)

    # now that we've verified that the uri is correct,
    # let's deconstruct it.
    path_components = [decode_percent(c) for c in uri.split(b"/")]

    return path_components


# note: the bufsize limits both the maximum length of the
# request line, and the maximum length of a single header.
#
#
def handle_request_header(socket, bufsize=10000, interesting_headers=set()):

    buf = socket.recv(bufsize)

    # parse the request line.
    # this one is simple, because it contains three components
    # separated by a single space each and terminated by crlf.
    split_result = buf.split(b"\r\n", maxsplit=1)
    del buf

    request_line = split_result[0]
    number_of_spaces = request_line.count(b" ")

    if len(split_result) == 1:
        # this means that there wasn't a terminating \r\n, which
        # probably means that the request line was too long.
        # we're going to find out which part now.

        if number_of_spaces == 0:
            # the method was too long (unlikely)
            raise HTTPError(501, "method too long")

        elif number_of_spaces == 1:
            # the URI was too long
            raise HTTPError(414, "uri too long")

        elif number_of_spaces == 2:
            # this means that the http-version thingy hasn't fit fully
            # on the line. since this part has a fixed length, we have
            # to blame it on either the uri or the request method,
            # and i'm going to blame it on the uri.
            raise HTTPError(414, "uri too long")

        else:
            # there's definitely too many spaces here
            raise HTTPError(400, "too many spaces in request line")

    if number_of_spaces != 2:
        # that's not the right amount of spaces
        raise HTTPError(400, "too many spaces in request line")

    method, uri, http_version = request_line.split(b" ")

    if not validate_token(method):
        raise HTTPError(400, "invalid request method format")

    if not validate_uri(uri):
        raise HTTPError(400, "invalid request uri format")

    version = get_http_version(http_version)
    if not version:
        raise HTTPError(400, "invalid http version string")

    major, minor = version
    if major != 1:
        return HTTPError(505, "http version not supported")

    # aaand we ignore the minor version

    ## cool! we've now parsed the request line. time for the headers!
    buf = split_result[1]
    del split_result

    # TODO: compare header names in bytes or ascii?
    interesting_headers = set(header.lower() for header in interesting_headers)
    interesting_headers.add("transfer-encoding")
    interesting_headers.add("content-length")

    # headers is a dict of lists because:
    #
    #  - the same header may appear multiple times,
    #    depending on its semantics. (some headers may not
    #    appear multiple times.) i don't want to deal with
    #    this in a fully general way, so i'm leaving just it
    #    to the higher layers to do so.
    #
    # - *if* multiple headers of the same name appear, the order
    #   of those headers matters.
    headers = {}

    while True:
        # refill the buffer
        buf += socket.recv(bufsize - len(buf))

        header_start = 0
        header_end = buf.find(b"\r\n")
        if header_end == -1:
            raise HTTPError(431, "header too long")

        headers_end = buf.find(b"\r\n\r\n")
        if headers_end == -1:
            headers_end = len(buf)
            headers_done = False
        else:
            headers_done = True

        # i am adding 2 because i want to include the first crlf
        headers_end += 2

        while header_end != -1:
            parse_result = parse_header(buf[header_start:header_end])
            if not parse_result:
                raise HTTPError(400, "invalid header format")

            header_name, header_value = parse_result
            header_name = header_name.lower()
            if header_name in interesting_headers:

                existing_values = headers.get(header_name)
                if existing_values:
                    existing_values.append(header_value)
                else:
                    headers[header_name] = [header_value]

            header_start = header_end + 2
            header_end = buf.find(b"\r\n", header_start, headers_end)

        if headers_done is True:
            # headers_end points to the final crlf of the http header.
            # to get the start of the following request body, we thus
            # have to add 2.
            buf = buf[headers_end + 2 :]
            break

        else:
            # remove all already parsed headers from the buffer.
            # the next header should have started at header_start,
            # but we didn't find a corresponding end. however,
            # everything before header_start is already parsed.
            buf = buf[header_start:]

    ## headers are done. we are now going to determine whether there
    ## is going to be a request body.
    # (section 3.3.3)

    # transfer-encoding takes priority if present
    if headers.get("transfer-encoding"):
        # we should support chunked but we currently don't
        raise HTTPError(500, "chunked transfer-encoding is not supported :/")

    if headers.get("content-length"):

        content_length_headers = headers["content-length"]
        if len(content_length_headers) > 1:
            # we could, in theory, check if all these headers have
            # the same value and, if so, merge them together. on the
            # other hand, we're still perfectly compliant if we just
            # reject the message in this case.
            raise HTTPError(400, "content-length header is defined more than once")

        if not re.match("[0-9]+$", content_length_headers[0]):
            raise HTTPError(400, "content-length header has invalid format")

        # hard-limit content-length to less than 10^9
        # (less than 2^32)
        if len(content_length_headers[0]) > 9:
            raise HTTPError(413, "request payload is too large")

        content_length = int(content_length_headers[0])

    else:

        content_length = 0

    return HTTPRequest(method, uri, headers, buf, content_length)
