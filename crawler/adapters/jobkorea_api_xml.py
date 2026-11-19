"""JobKorea official recruitment XML API (채용정보 XML 가이드 V4.1, 2023-04-12): response parsing only.

Pure functions: no network, no DB. The fetcher (``crawler.jobs.jobkorea_api``) passes the raw response bytes.

Response shape (guide p.45-46): ``<DataList>`` with ``<TotalSumCnt>`` (full XML only, at most 500),
``<TotalCnt>`` (items on this page, at most 100) and one ``<Items>`` element per posting holding the posting
fields as child elements. The guide states the response is EUC-KR; it is decoded as CP949 (a strict superset
of EUC-KR) so rare Hangul syllables outside KS X 1001 do not fail the whole page.

Field mapping into the existing ``NormalizedPosting`` (no new columns, nothing inferred):

    GI_No         -> external_posting_id   (digits only)
    JK_URL        -> source_url            (path only: https://www.jobkorea.co.kr/Recruit/GI_Read/<id>; the
                                            query, which carries the API identifier, is never stored)
    GI_Subject    -> title
    C_Name        -> company_name          (present in both response examples of the guide)
    AreaCode      -> location_text         (guide region codes -> region names, de-duplicated)
    GI_Job_Type   -> employment_type       (first code: 1 full_time, 2 contract, 3 intern, 7 part_time,
                                            any other code -> None)
    GI_W_Date     -> published_on          (YYYYMMDD -> ISO date)
    GI_End_Date   -> expires_on            (YYYYMMDD -> ISO date; any other value -> None)

The career condition (GI_Career) and other fields have no column in the current model; they are not stored.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from crawler.normalizer import InvalidPosting, NormalizedPosting, normalize

MAX_RESPONSE_BYTES = 5_000_000
MAX_PAGE_SIZE = 100            # guide: Size 1..100
MAX_TOTAL_RESULTS = 500        # guide: TotalSumCnt is capped at 500
_DECLARATION = re.compile(rb'^\s*<\?xml[^>]*\?>', re.S)
_DECLARED_ENCODING = re.compile(rb'encoding\s*=\s*["\']([A-Za-z0-9_.-]+)["\']')
_DETAIL_PATH = re.compile(r'/Recruit/GI_Read/([0-9]{1,12})')
_DATE = re.compile(r'^([0-9]{4})([0-9]{2})([0-9]{2})$')

# Guide p.13-14 (request variable ``area``): the region a code belongs to is named by its first character
# (``B180`` -> 경기도); 1000/2000/3000 are whole regions. ``0`` means "no region".
REGION_NAMES = {
    'I': '서울특별시', 'E': '광주광역시', 'F': '대구광역시', 'G': '대전광역시', 'H': '부산광역시',
    'J': '울산광역시', 'K': '인천광역시', 'B': '경기도', 'A': '강원도', 'C': '경상남도', 'D': '경상북도',
    'L': '전라남도', 'M': '전라북도', 'O': '충청남도', 'P': '충청북도', 'N': '제주특별자치도',
    '1': '세종특별자치시', '2': '금강산관광특구', '3': '개성공업지구', 'Q': '전국',
    'X': '중국·홍콩', 'Y': '미국', 'Z': '일본', 'R': '아시아·중동', 'S': '북아메리카', 'T': '남아메리카',
    'U': '유럽', 'V': '오세아니아', 'W': '아프리카',
}
# Guide p.18 (GI_Job_Type) mapped onto the four employment types the posting model accepts.
EMPLOYMENT_TYPES = {'1': 'full_time', '2': 'contract', '3': 'intern', '7': 'part_time'}


class ApiResponseError(ValueError):
    """The response is not a usable JobKorea XML page. ``code`` is a short, secret-free reason."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ApiPage:
    total_results: int | None      # TotalSumCnt (None in the 신입공채 XML, which has no such element)
    page_count: int                # TotalCnt
    items: tuple[dict, ...]        # one dict per <Items>: {field: text}
    encoding: str                  # declared encoding, lower case ('euc-kr' per the guide)


def _decode(data):
    if not isinstance(data, (bytes, bytearray)) or not data.strip():
        raise ApiResponseError('EMPTY_RESPONSE')
    if len(data) > MAX_RESPONSE_BYTES:
        raise ApiResponseError('RESPONSE_TOO_LARGE')
    declaration = _DECLARATION.match(data)
    declared = 'euc-kr'            # the guide: responses are EUC-KR; used when there is no declaration
    if declaration:
        found = _DECLARED_ENCODING.search(declaration.group(0))
        if found:
            declared = found.group(1).decode('ascii').lower()
    codec = {'euc-kr': 'cp949', 'euc_kr': 'cp949', 'ks_c_5601-1987': 'cp949', 'cp949': 'cp949',
             'utf-8': 'utf-8', 'utf8': 'utf-8'}.get(declared)
    if codec is None:
        raise ApiResponseError('UNSUPPORTED_ENCODING')
    body = data[declaration.end():] if declaration else data
    try:
        return body.decode(codec, errors='strict'), declared
    except UnicodeDecodeError:
        raise ApiResponseError('INVALID_ENCODING') from None


def _count(root, tag, *, required):
    node = root.find(tag)
    if node is None:
        if required:
            raise ApiResponseError('MISSING_' + tag.upper())
        return None
    text = (node.text or '').strip()
    if not text.isascii() or not text.isdigit():
        raise ApiResponseError('INVALID_' + tag.upper())
    return int(text)


def parse_api_response(data, *, require_total=True):
    """Raw response bytes -> ApiPage. Raises ApiResponseError for anything that is not a DataList page."""
    text, declared = _decode(data)
    head = text[:4096].upper()
    if '<!DOCTYPE' in head or '<!ENTITY' in text.upper():
        raise ApiResponseError('DTD_NOT_ALLOWED')     # no entity expansion of untrusted input
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise ApiResponseError('INVALID_XML') from None
    if root.tag != 'DataList':
        raise ApiResponseError('UNEXPECTED_ROOT')
    total = _count(root, 'TotalSumCnt', required=require_total)
    page_count = _count(root, 'TotalCnt', required=True)
    items = tuple({child.tag: (child.text or '').strip() for child in node} for node in root.findall('Items'))
    if page_count > MAX_PAGE_SIZE or (total is not None and total > MAX_TOTAL_RESULTS):
        raise ApiResponseError('COUNT_OUT_OF_RANGE')
    return ApiPage(total, page_count, items, declared)


def _iso_date(value):
    match = _DATE.match(value or '')
    return f'{match.group(1)}-{match.group(2)}-{match.group(3)}' if match else None


def _location(codes):
    names = []
    for code in (c.strip() for c in (codes or '').split(',')):
        if not code or code == '0':
            continue
        name = REGION_NAMES.get(code[0])
        if name and name not in names:
            names.append(name)
    return ', '.join(names) or None


def _detail_url(item, external_id):
    """The provider's own detail link without its query (which carries the API identifier)."""
    url = item.get('JK_URL') or ''
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if parts is not None and parts.hostname in {'www.jobkorea.co.kr', 'jobkorea.co.kr'}:
        match = _DETAIL_PATH.fullmatch(parts.path)
        if match:
            return 'https://www.jobkorea.co.kr/Recruit/GI_Read/' + match.group(1)
    return 'https://www.jobkorea.co.kr/Recruit/GI_Read/' + external_id


def item_posting_id(item):
    """GI_No as text, or None when it is not a plain positive integer."""
    value = (item.get('GI_No') or '').strip()
    return value if value.isascii() and value.isdigit() and not value.startswith('0') and len(value) <= 12 else None


def to_posting(item, *, source_code):
    """One ``<Items>`` dict -> NormalizedPosting. Raises InvalidPosting when a required field is missing."""
    external_id = item_posting_id(item)
    if external_id is None:
        raise InvalidPosting('Missing or invalid field: GI_No')
    job_type = (item.get('GI_Job_Type') or '').split(',')[0].strip()
    raw = {
        'external_posting_id': external_id,
        'source_url': _detail_url(item, external_id),
        'title': item.get('GI_Subject'),
        'company_name': item.get('C_Name'),
        'location_text': _location(item.get('AreaCode')),
        'employment_type': EMPLOYMENT_TYPES.get(job_type),
        'published_on': _iso_date(item.get('GI_W_Date')),
        'expires_on': _iso_date(item.get('GI_End_Date')),
        'status': 'published',
    }
    return replace(normalize(raw), source_code=source_code)


__all__ = ['ApiPage', 'ApiResponseError', 'InvalidPosting', 'NormalizedPosting', 'item_posting_id',
           'parse_api_response', 'to_posting']
