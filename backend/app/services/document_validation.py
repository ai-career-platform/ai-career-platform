"""Bounded structural validation; this does NOT substitute for malware scanning."""
import io
import re
import zipfile
import zlib
from xml.etree import ElementTree

from app.core.errors import AppError, ErrorCode

MAX_FILE_BYTES = 10 * 1024 * 1024
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def validate_document(filename: str, mime: str, content: bytes) -> None:
    if len(content) > MAX_FILE_BYTES:
        raise AppError(ErrorCode.FILE_TOO_LARGE)
    if not content or not filename or len(filename) > 255 or any(
        ord(c) < 32 or ord(c) == 127 or c in "/\\" for c in filename
    ) or filename in {".", ".."}:
        raise AppError(ErrorCode.VALIDATION_FAILED)
    valid = False
    if mime == PDF and filename.lower().endswith(".pdf"):
        valid = bool(re.match(rb"%PDF-\d\.\d[\r\n]", content)) and content.rstrip().endswith(b"%%EOF")
    elif mime == DOCX and filename.lower().endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos = archive.infolist()
                names = [x.filename for x in infos]
                valid = (len(names) == len(set(names)) and 0 < len(names) <= 1000
                         and sum(x.file_size for x in infos) <= 50 * 1024 * 1024
                         and all(not x.flag_bits & 1 and x.file_size <= 10 * 1024 * 1024
                                 and not x.filename.startswith(("/", "\\"))
                                 and ".." not in x.filename.replace("\\", "/").split("/")
                                 and not x.filename.lower().endswith((".bin", ".exe", ".dll"))
                                 for x in infos))
                if valid:
                    types = archive.read("[Content_Types].xml")
                    document = archive.read("word/document.xml")
                    # XML is untrusted: reject entity declarations before parsing.
                    if any(b"<!" in x or b"\x00" in x for x in (types, document)):
                        valid = False
                    else:
                        root = ElementTree.fromstring(types)
                        doc = ElementTree.fromstring(document)
                        valid = (doc.tag == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document"
                                 and any(x.get("PartName") == "/word/document.xml" and x.get("ContentType") ==
                                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                                         for x in root))
        except (zipfile.BadZipFile, KeyError, ValueError, RuntimeError, NotImplementedError,
                ElementTree.ParseError, zlib.error, EOFError, OSError):
            valid = False
    if not valid:
        raise AppError(ErrorCode.UNSUPPORTED_FILE_TYPE)
